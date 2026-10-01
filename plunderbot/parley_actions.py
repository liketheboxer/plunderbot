"""Parley's hands: what members can ask PlunderBot to do in plain speech, done as the member who asked.

1.3.1 started this with voyages, crews and a song. 1.6.0 covers everything a member can do with a slash
command or a button (admin and moderation aside), in eight grouped tools: voyage, crew, music, me (time
zone and birthday), follow, roles, ship and pirate. Each action goes through the same code as the slash
command or button it stands for, with the same checks for the member who asked (never anyone else), and
returns a short plain result for Claude to put in its own words. Members still on the Gangplank can't act.

Two actions notify other people or can't be undone from chat, so PlunderBot asks first: cancelling a voyage
(or a whole series) and retiring a ship. The reply carries Confirm and Cancel buttons only the member who
asked can press (see CONFIRM and cogs/parley.py). Lyrics stay with /music lyrics, which answers privately.
"""
from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import discord

from . import games
from .crew_logic import clean_title, now_utc
from .voyage_logic import (ParseError, format_reminders, is_weekday_name, parse_date, parse_reminders, parse_time,
                           resolve_repeat, split_zone, to_utc, zone_label)

log = logging.getLogger("plunderbot.parley")

CONFIRM_SECONDS = 600
REPEAT_HELP = ("'none', 'weekly', 'biweekly', 'every 3 weeks' (up to the limit), 'monthly' (the same date each "
               "month), 'nth' (the same weekday of each month, like the 2nd Saturday) or 'nth:last' (the last one)")

ACTION_TOOLS = [
    {"name": "voyage",
     "description": "Scheduled voyages (planned sessions people sign up for), as the person asking. action: "
                    "'plan' a new one with them as organizer (needs title, date and time; make a short title up "
                    "if they didn't give one, but ask for a missing date or time instead of guessing); 'answer' "
                    "one (answer: aboard, maybe, cant or clear); 'edit' one they organized (only the fields they "
                    "asked to change); 'series' to see a repeating voyage's coming dates; 'skip_date' or "
                    "'restore_date' for one date of a series they organized; 'cancel' one they organized "
                    "(whole_series: true stops a repeating one for good). Get the voyage's number from "
                    "upcoming_voyages first. Cancelling asks them to confirm with a button.",
     "input_schema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["plan", "answer", "edit", "series", "skip_date", "restore_date",
                                               "cancel"]},
         "voyage": {"type": "integer", "description": "The voyage's number (#12 in upcoming_voyages); not for plan."},
         "title": {"type": "string"},
         "date": {"type": "string", "description": "As they said it: 'friday', 'tomorrow', '10/3'. For "
                                                    "skip_date/restore_date, the date to skip or put back."},
         "time": {"type": "string", "description": "As they said it: '8pm', '20:30', '8pm ET'."},
         "game": {"type": "string", "description": "plan only: the game, or leave out for a general server event."},
         "size": {"type": "string", "description": "plan only: crew size if they said one, e.g. 'Galleon'."},
         "seats": {"type": "integer", "description": "Only if they asked for a number of seats."},
         "details": {"type": "string"},
         "repeat": {"type": "string", "description": f"Only if they asked: {REPEAT_HELP}."},
         "repeat_ends": {"type": "string", "description": "The last date a series runs, or 'never'."},
         "reminders": {"type": "string", "description": "Only if they asked, e.g. '1d, 1h' or 'none'."},
         "answer": {"type": "string", "enum": ["aboard", "maybe", "cant", "clear"]},
         "whole_series": {"type": "boolean"}},
         "required": ["action"]}},
    {"name": "crew",
     "description": "Crew calls (playing right now), as the person asking. action: 'start' one with them as "
                    "captain (needs game); 'join' or 'leave' one (get its number from open_crews); 'close' the "
                    "one they captain (its voice channel goes too); 'rename' the session they captain (leave "
                    "name out to go back to the default).",
     "input_schema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["start", "join", "leave", "close", "rename"]},
         "crew": {"type": "integer", "description": "The crew's number (#7 in open_crews), for join and leave."},
         "game": {"type": "string"},
         "size": {"type": "string", "description": "e.g. 'Sloop'; leave out for the game's usual size."},
         "activity": {"type": "string", "description": "e.g. 'Fort', only if they said."},
         "note": {"type": "string"},
         "name": {"type": "string", "description": "A session name, only if they gave one."}},
         "required": ["action"]}},
    {"name": "music",
     "description": "Music in voice, as the person asking (they must be in the voice channel; with a DJ role "
                    "set, some controls are the DJ's). action: 'play' a song or playlist link (query; if they "
                    "want you to choose, pick one real, well-known song and search 'Artist - Title'; next: true "
                    "only if they ask for it next); 'queue' to see what's playing, the volume and what's next; "
                    "'skip', 'pause', 'resume', 'stop' (stops, clears and leaves), 'clear' (empties the queue), "
                    "'shuffle'; 'remove' or 'move' a track by its number in the queue (position, and to for "
                    "move); 'repeat' with mode off, one or all; 'seek' to a point (at: '1:30'); 'volume' with "
                    "percent (1 to 150) or change (+/- points, e.g. -20 for 'a bit quieter'). You can't give "
                    "lyrics: point them to /music lyrics.",
     "input_schema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["play", "queue", "skip", "pause", "resume", "stop", "clear", "shuffle",
                                               "remove", "move", "repeat", "seek", "volume"]},
         "query": {"type": "string"}, "next": {"type": "boolean"},
         "position": {"type": "integer"}, "to": {"type": "integer"},
         "mode": {"type": "string", "enum": ["off", "one", "all"]},
         "at": {"type": "string"}, "percent": {"type": "integer"}, "change": {"type": "integer"}},
         "required": ["action"]}},
    {"name": "me",
     "description": "The person asking's own settings. action: 'timezone_set' (zone: 'Pacific', 'Eastern', 'ET', "
                    "or the IANA name, like 'America/Denver' for a city they named), 'timezone_show', "
                    "'timezone_clear'; 'birthday_set' (month "
                    "1 to 12 and day; never a year), 'birthday_show', 'birthday_remove'.",
     "input_schema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["timezone_set", "timezone_show", "timezone_clear", "birthday_set",
                                               "birthday_show", "birthday_remove"]},
         "zone": {"type": "string"}, "month": {"type": "integer"}, "day": {"type": "integer"}},
         "required": ["action"]}},
    {"name": "follow",
     "description": "Following games (their ping role and forum thread), for the person asking. action: 'list' "
                    "the games they can follow and the ones they do; 'follow' or 'unfollow' games by name.",
     "input_schema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["list", "follow", "unfollow"]},
         "games": {"type": "array", "items": {"type": "string"}}},
         "required": ["action"]}},
    {"name": "roles",
     "description": "The roles members pick for themselves from the server's role menus (regions, platforms "
                    "and so on), for the person asking. action: 'list' the menus, their roles and what they "
                    "wear; 'add' or 'remove' roles by name. Only roles on a posted menu; nothing else.",
     "input_schema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["list", "add", "remove"]},
         "roles": {"type": "array", "items": {"type": "string"}}},
         "required": ["action"]}},
    {"name": "ship",
     "description": "Sea of Thieves ships in the Ship's Ledger. action: 'mine' (their ships), 'show' a ship's "
                    "profile (ship: a name; leave out for their own), 'register' a ship of theirs (name and "
                    "kind: Sloop, Brigantine or Galleon; motto optional), 'edit' one of theirs (ship, then "
                    "name, kind or motto; motto '-' clears it), 'retire' one of theirs (asks them to confirm "
                    "with a button). Pictures need /ship register or /ship edit.",
     "input_schema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["mine", "show", "register", "edit", "retire"]},
         "ship": {"type": "string", "description": "The ship's name, for show, edit and retire."},
         "name": {"type": "string"}, "kind": {"type": "string", "enum": ["Sloop", "Brigantine", "Galleon"]},
         "motto": {"type": "string"}},
         "required": ["action"]}},
    {"name": "pirate",
     "description": "Pirate profiles. action: 'profile' to see one (member: their name or mention; leave out for "
                    "the person asking), 'set' the person asking's gamertag and/or motto ('-' clears one).",
     "input_schema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["profile", "set"]},
         "member": {"type": "string"}, "gamertag": {"type": "string"}, "motto": {"type": "string"}},
         "required": ["action"]}},
]
ACTION_NAMES = {t["name"] for t in ACTION_TOOLS}
CONFIRM = {("voyage", "cancel"), ("ship", "retire")}   # asked about with buttons first


@dataclass
class Pending:
    """An action waiting for the member who asked to press Confirm."""
    token: str
    guild_id: int
    user_id: int
    tool: str
    args: dict
    what: str
    expires: float


@dataclass
class Turn:
    """What one Parley answer collected along the way: actions waiting on Confirm, and background work."""
    pending: list[Pending] = field(default_factory=list)
    spawn: object = None   # callable(coroutine) for work that shouldn't hold up the reply


def find_game(text: str | None, crew_call: bool = False):
    """A game from how someone named it ("SoT", "sea of thieves", "helldivers")."""
    if not text:
        return None
    want = games.normalise(text)
    pool = [g for g in games.GAMES if g.crew_call or not crew_call]
    for g in pool:
        if want in (games.normalise(g.name), games.normalise(g.short), g.key):
            return g
    initials = {g: "".join(w[0] for w in g.name.lower().split() if w[0].isalnum()) for g in pool}
    for g, ini in initials.items():
        if want == ini:
            return g
    hits = [g for g in pool if want and (want in games.normalise(g.name) or games.normalise(g.name) in want)]
    return hits[0] if len(hits) == 1 else None


def game_list(crew_call: bool = False) -> str:
    return ", ".join(g.name for g in games.GAMES if g.crew_call or not crew_call)


def _norm(text) -> str:
    return games.normalise(str(text or ""))


def _match_names(wanted: list, options: list[tuple[str, object]]) -> tuple[list, list[str]]:
    """Pick options by how people name them: exactly first, then a unique partial match.
    Returns (picked, names that matched nothing or too much)."""
    picked, unknown = [], []
    if isinstance(wanted, str):
        wanted = [wanted]
    for w in wanted or []:
        n, raw = _norm(w), " ".join(str(w).casefold().split())
        if not raw:
            continue
        exact = [o for name, o in options if " ".join(str(name).casefold().split()) == raw]
        exact = exact or ([o for name, o in options if _norm(name) and _norm(name) == n] if n else [])
        part = exact or ([o for name, o in options if _norm(name) and (n in _norm(name) or _norm(name) in n)]
                         if n else [])
        if len(part) == 1:
            if part[0] not in picked:
                picked.append(part[0])
        else:
            unknown.append(str(w))
    return picked, unknown


def _public(guild, channel_id) -> bool:
    """Only what's posted where everyone can see it (as Parley's look-ups, 1.4.1)."""
    from .cogs.parley import Parley
    return Parley.public_channel(guild, channel_id)


REPEAT_WORDS = {"every week": "weekly", "each week": "weekly", "every other week": "biweekly",
                "every two weeks": "biweekly", "every 2 weeks": "biweekly", "fortnightly": "biweekly",
                "every month": "monthly", "each month": "monthly", "never": "none", "no": "none",
                "doesn't repeat": "none", "once": "none"}


def _repeat_word(text) -> str | None:
    if text is None:
        return None
    t = " ".join(str(text).lower().split())
    return REPEAT_WORDS.get(t, t)


def _embed_text(embed: discord.Embed) -> str:
    """An embed card as plain lines, for Claude to read."""
    out = [x for x in (embed.title, embed.description) if x]
    for f in embed.fields:
        out.append(f"{f.name}: {f.value}")
    if embed.footer and embed.footer.text:
        out.append(embed.footer.text)
    return "\n".join(out)[:3000]


async def act(bot, guild: discord.Guild, author, channel, name: str, args: dict, turn: Turn | None = None,
              confirmed: bool = False) -> str:
    """Do one action for the member who asked. Returns what happened, for Claude to relay."""
    if author is None or not hasattr(author, "voice"):
        return "Only a server member can ask for that."
    s = await bot.db.get_settings(guild.id)
    if s.pending_role_id and any(r.id == s.pending_role_id for r in getattr(author, "roles", [])):
        return "They're still on the Gangplank; a Harbormaster has to let them aboard first."
    handler = _TOOLS.get(name)
    if handler is None:
        return f"Unknown action {name}."
    action = str((args or {}).get("action") or "")
    try:
        if not confirmed and ((name, action) in CONFIRM or await _skips_this_one(bot, guild, args or {}, name)):
            return await _ask_first(bot, guild, author, name, args or {}, turn)
        return await handler(bot, guild, author, channel, s, args or {}, turn or Turn())
    except (ValueError, TypeError) as e:
        return f"That didn't work: {e}"


async def _skips_this_one(bot, guild, a: dict, name: str) -> bool:
    """Skipping a series' date that is this very voyage cancels it (everyone signed up is told), so it's
    confirmed like a cancel."""
    if name != "voyage" or a.get("action") != "skip_date" or not a.get("date"):
        return False
    v = await bot.db.get_voyage(int(a.get("voyage") or 0))
    cog = bot.get_cog("Voyages")
    if v is None or cog is None or v.guild_id != guild.id or v.status != "scheduled" or v.repeat == "none":
        return False
    from .cogs.voyages import _day
    tz = await cog.tz(v.guild_id)
    try:
        return _day(str(a["date"]), datetime.now(tz).date()) == datetime.fromisoformat(v.starts_at).astimezone(tz).date()
    except ParseError:
        return False


async def _ask_first(bot, guild, author, name, a, turn: Turn | None) -> str:
    """Check the action could be done, then hold it for the member's Confirm button."""
    if name == "voyage":
        v, problem = await _my_voyage(bot, guild, author, a)
        if problem:
            return problem
        if a.get("action") == "skip_date":
            what = f"skip \"{v.title}\" (#{v.id}) this time; the series carries on"
            args = {"action": "skip_date", "voyage": v.id, "date": str(a["date"])}
        else:
            series = bool(a.get("whole_series")) and v.repeat != "none"
            what = f"cancel {'the whole series of ' if series else ''}\"{v.title}\" (#{v.id})"
            args = {"action": "cancel", "voyage": v.id, "whole_series": series}
    else:
        ledger = bot.get_cog("ShipLedger")
        if ledger is None:
            return "The Ship's Ledger isn't running."
        ship, problem = await ledger.editable_ship(guild.id, author, a.get("ship"), retiring=True, own_only=True)
        if problem:
            return problem
        what = f"retire {ship.name} (her ledger stays)"
        args = {"action": "retire", "ship": str(ship.id)}
    if turn is None:
        return "That needs a Confirm button, which only works in chat."
    if any(p.tool == name and p.args == args for p in turn.pending):
        return f"Already waiting for them to confirm: {what}."
    if len(turn.pending) >= 3:
        return "Too many things waiting to be confirmed at once; ask them to do one at a time."
    turn.pending.append(Pending(token=secrets.token_hex(6), guild_id=guild.id, user_id=author.id, tool=name,
                                args=args, what=what, expires=time.time() + CONFIRM_SECONDS))
    return (f"Not done yet: your reply will carry Confirm and Cancel buttons for them to {what}. Tell them to "
            "press Confirm to go ahead (only they can, within 10 minutes). Don't say it's done.")


# ================================================================ voyages
async def _my_voyage(bot, guild, author, a: dict):
    """(the voyage, None) when the member organized it, else (None, why not)."""
    v = await bot.db.get_voyage(int(a.get("voyage") or 0))
    if v is None or v.guild_id != guild.id or v.status != "scheduled" or not _public(guild, v.channel_id):
        return None, "There's no upcoming voyage with that number; check upcoming_voyages."
    if v.organizer_id != author.id:
        # Mods can still change anyone's voyage with /voyage edit; by chat it's only your own, so text
        # slipped into a conversation can't steer a mod into changing someone else's.
        return None, "Only its organizer can change it by asking (mods can use /voyage edit or /voyage cancel)."
    return v, None


async def _voyage(bot, guild, author, channel, s, a: dict, turn: Turn) -> str:
    cog = bot.get_cog("Voyages")
    if cog is None:
        return "Voyages are switched off."
    action = a.get("action")
    if action == "plan":
        return await _plan_voyage(bot, cog, guild, author, channel, s, a)
    if action == "answer":
        v = await bot.db.get_voyage(int(a.get("voyage") or 0))
        if v is None or v.guild_id != guild.id or not _public(guild, v.channel_id):
            return "There's no voyage with that number; check upcoming_voyages."
        answer = a.get("answer")
        if answer not in ("aboard", "maybe", "cant", "clear"):
            return "The answer must be aboard, maybe, cant or clear."
        ok, reply = await cog.rsvp_as(guild, v.id, author.id, None if answer == "clear" else answer)
        return reply if ok else "That voyage has already started or ended."
    if action == "series":
        v = await bot.db.get_voyage(int(a.get("voyage") or 0))
        if v is None or v.guild_id != guild.id or v.status != "scheduled" or not _public(guild, v.channel_id):
            return "There's no upcoming voyage with that number."
        if v.repeat == "none":
            return f"\"{v.title}\" doesn't repeat."
        return cog.series_text(v, await cog.series_dates(v))
    v, problem = await _my_voyage(bot, guild, author, a)
    if problem:
        return problem
    if action == "cancel":
        whole = bool(a.get("whole_series")) and v.repeat != "none"
        if not await cog.apply_cancel(guild, v.id, whole):
            return "It has already started or ended."
        return (f"Cancelled {'the whole series of ' if whole else ''}\"{v.title}\"; everyone who signed up was told."
                + (" The next one in the series is still on." if v.repeat != "none" and not whole else ""))
    from .cogs.voyages import EditRefused
    from . import voice
    fields = {}
    if action == "edit":
        fields = dict(title=a.get("title"), date=a.get("date"), time=a.get("time"), description=a.get("details"),
                      reminders=a.get("reminders"), seats=a.get("seats"), repeat=_repeat_word(a.get("repeat")),
                      repeat_ends=a.get("repeat_ends"))
    elif action in ("skip_date", "restore_date"):
        if v.repeat == "none":
            return f"\"{v.title}\" doesn't repeat, so there are no dates to skip; cancel it instead."
        if not a.get("date"):
            return "Which date? Ask them."
        fields = {"skip" if action == "skip_date" else "unskip": str(a["date"])}
    else:
        return f"I don't know how to {action} a voyage."
    try:
        changes, skip_this, tz, whose, starts = await cog.plan_edit(v, author.id, **fields)
    except EditRefused as e:
        return voice.say(e.key, **e.kw)
    if not changes and not skip_this:
        return "Nothing to change; ask them what they want different."
    v2 = await cog.apply_series(guild, v, changes, skip_this)
    if v2 is None:
        return "It has already started."
    return await cog.edit_text(v2, changes, skip_this, tz, whose, starts)


async def _plan_voyage(bot, cog, guild, author, channel, s, a: dict) -> str:
    title = " ".join(str(a.get("title") or "").split())[:80]
    if not title:
        return "It needs a title."
    if not a.get("date") or not a.get("time"):
        return "It needs a date and a time; ask them."
    profile = None
    if a.get("game"):
        profile = find_game(a["game"])
        if profile is None:
            return f"I don't know the game \"{a['game']}\". The games are: {game_list()}."
    tz, whose = await cog.reading_zone(author.id, guild.id)
    now = now_utc()
    try:
        time_text, typed = split_zone(str(a.get("time") or ""))
        if typed is not None:
            tz, whose = typed, "typed"
        day = parse_date(str(a.get("date") or ""), datetime.now(tz).date())
        starts = to_utc(day, parse_time(time_text), tz)
        if starts <= now and is_weekday_name(str(a.get("date") or "")):
            starts = to_utc(day + timedelta(days=7), parse_time(time_text), tz)
        minutes = parse_reminders(a.get("reminders") or None)
        local_day = starts.astimezone(tz).date()
        repeat = resolve_repeat(_repeat_word(a.get("repeat")) or "none", local_day)
        until = cog.read_until(a.get("repeat_ends"), repeat, local_day, tz)
    except ParseError as e:
        return f"That didn't work: {e}"
    if starts <= now + timedelta(minutes=1) or starts > now + timedelta(days=366):
        return "That time is in the past (or more than a year away); ask them for another."
    size_label, capacity = None, a.get("seats") if isinstance(a.get("seats"), int) and 1 <= a["seats"] <= 99 else None
    if profile is not None:
        chosen = profile.size(a.get("size"))
        if chosen is None:
            return f"{profile.name} crews are {', '.join(z.label for z in profile.sizes)}; ask which."
        size_label = chosen.label
        if capacity is None and not profile.open_ended:
            capacity = chosen.capacity
    channel_to = cog.voyage_channel(guild, s) or channel
    if channel_to is None or isinstance(channel_to, discord.Thread):
        return "There's no voyage channel to post in; a Quartermaster sets one with /admin voyages channel."
    v = await cog.launch(guild, channel_to, author.id, title=title,
                         description=(str(a.get("details") or "").strip()[:1000] or None), profile=profile,
                         size_label=size_label, capacity=capacity, starts=starts, duration=120, minutes=minutes,
                         repeat=repeat, ping_role="posted", repeat_until=until)
    if v is None:
        return "PlunderBot couldn't post the voyage card."
    link = f"https://discord.com/channels/{v.guild_id}/{v.channel_id}/{v.message_id}"
    read_as = "their own time zone" if whose == "yours" else ("the zone they typed" if whose == "typed"
                                                               else f"the server's time zone ({zone_label(tz, starts)})")
    from .voyage_logic import describe_repeat
    return (f"Planned voyage #{v.id} \"{title}\"{f' ({profile.name} {size_label})' if profile else ''} at "
            f"<t:{int(starts.timestamp())}:F> (the time was read in {read_as}), with them Aboard. Reminders: "
            f"{format_reminders(minutes)}."
            + (f" Repeats: {describe_repeat(repeat)}." if repeat != "none" else "")
            + f" Card: {link}. They can change it by asking, or with /voyage edit.")


# ================================================================ crews
async def _crew(bot, guild, author, channel, s, a: dict, turn: Turn) -> str:
    cog = bot.get_cog("CrewCall")
    if cog is None:
        return "Crew calls are switched off."
    action = a.get("action")
    if action == "start":
        profile = find_game(a.get("game"), crew_call=True)
        if profile is None:
            return f"I don't know the game \"{a.get('game')}\". Crew calls are for: {game_list(crew_call=True)}."
        ships = await bot.db.ships(guild.id, author.id) if profile.key == "sot" else []
        ship = ships[0] if len(ships) == 1 else None
        size = profile.size(a.get("size") or (ship.kind if ship else None))
        if size is None:
            return f"{profile.name} crews are {', '.join(z.label for z in profile.sizes)}; ask which."
        tag = profile.tag(a.get("activity"))
        channel_to = cog.crew_channel(guild, s) or channel
        if channel_to is None or isinstance(channel_to, discord.Thread):
            return "There's no crew channel to post in; a Quartermaster sets one with /admin crew channel."
        note = (" ".join(str(a.get("note") or "").split())[:200]) or None
        crew, problem = await cog.open_call(guild, channel_to, author.id, profile, size, tag, note,
                                            clean_title(a.get("name")), None, True, ship.id if ship else None)
        if problem == "crew_one_at_a_time":
            return "They're already captaining a crew; they need to close it first."
        if problem:
            return "PlunderBot couldn't post the crew card."
        if profile.open_ended or crew.full:
            await cog.sail(guild, crew.id)
        link = f"https://discord.com/channels/{crew.guild_id}/{crew.channel_id}/{crew.message_id}"
        return (f"Called crew #{crew.id}: {profile.name} {size.label}{f' on {ship.name}' if ship else ''}, with them "
                f"as captain. The card is up at {link}; the game's ping role was tagged.")
    if action in ("join", "leave"):
        crew = await bot.db.get_crew(int(a.get("crew") or 0))
        if crew is None or crew.guild_id != guild.id or not _public(guild, crew.channel_id):
            return "There's no crew with that number; check open_crews."
        _, reply = await cog.join_leave_as(guild, crew.id, author.id, action)
        return reply
    if action == "close":
        crew = await bot.db.active_crew_led_by(guild.id, author.id)
        if crew is None:
            return "They aren't captaining a crew."
        await cog.end(guild, crew.id, "closed")
        return "Closed their crew, and its voice channel."
    if action == "rename":
        _, reply = await cog.rename_as(guild, author, a.get("name") or None)
        return reply
    return f"I don't know how to {action} a crew."


# ================================================================ music
async def _music(bot, guild, author, channel, s, a: dict, turn: Turn) -> str:
    music = bot.get_cog("Music")
    if music is None:
        return "Music isn't running."
    action = a.get("action")
    if action == "queue":
        return music.summary(guild.id, upcoming=10)
    if action == "play":
        query = " ".join(str(a.get("query") or "").split())[:200]
        if not query:
            return "Say what to play."
        ok, text, start = await music.enqueue(guild, author, channel, query, bool(a.get("next")))
        if ok and start and turn.spawn is not None:   # start playing without holding up the reply
            turn.spawn(music.advance(guild, music.players[guild.id]))
        return ("Done: " if ok else "It didn't work: ") + text
    from .music_logic import parse_position
    kw: dict = {}
    if action in ("remove", "move"):
        if not isinstance(a.get("position"), int):
            return "Which number in the queue? Look it up with action 'queue'."
        kw["position"] = a["position"]
        if action == "move":
            kw["to"] = a.get("to") if isinstance(a.get("to"), int) else 1
    elif action == "repeat":
        kw["mode"] = a.get("mode") or "cycle"
    elif action == "seek":
        kw["seconds"] = parse_position(str(a.get("at") or ""))
    elif action == "volume":
        if isinstance(a.get("percent"), int):
            kw["percent"] = a["percent"]
        elif isinstance(a.get("change"), int):
            p = music.players.get(guild.id)
            now = round((p.volume if p else 0.6) * 100)
            kw["percent"] = max(1, min(150, now + a["change"]))
        else:
            return "How loud? Give a percent or a change."
    ok, text = await music.control(guild, author, action, **kw)
    return ("Done: " if ok else "It didn't work: ") + text


# ================================================================ the member's own settings
async def _me(bot, guild, author, channel, s, a: dict, turn: Turn) -> str:
    action = a.get("action") or ""
    if action.startswith("timezone"):
        core = bot.get_cog("Core")
        if core is None:
            return "That isn't running."
        if action == "timezone_set":
            if not a.get("zone"):
                return "Which time zone? Ask them."
            return await core.tz_set_as(author, str(a["zone"])[:60])
        if action == "timezone_show":
            return await core.tz_show_as(author, guild.id)
        return await core.tz_clear_as(author)
    cog = bot.get_cog("Birthdays")
    if cog is None:
        return "Birthdays are switched off."
    if action == "birthday_set":
        m, d = a.get("month"), a.get("day")
        if not isinstance(m, int) or not isinstance(d, int) or not 1 <= m <= 12 or not 1 <= d <= 31:
            return "It needs a month (1 to 12) and a day; ask them (never the year)."
        return await cog.set_as(guild.id, author.id, m, d)
    if action == "birthday_show":
        return await cog.mine_as(guild.id, author.id)
    if action == "birthday_remove":
        return await cog.remove_as(guild.id, author.id)
    return f"I don't know how to {action}."


# ================================================================ following games
async def _follow(bot, guild, author, channel, s, a: dict, turn: Turn) -> str:
    board = bot.get_cog("Noticeboard")
    if board is None:
        return "Following games isn't running."
    entries, mine = await board.following(guild, author)
    if not entries:
        return "There are no games to follow yet."
    action = a.get("action")
    if action == "list":
        return ("Games to follow: " + ", ".join(e["name"] for e in entries) + ". They follow: "
                + (", ".join(e["name"] for e in mine) if mine else "none yet") + ".")
    by_key = {e["key"]: e for e in entries}
    picked, rest = [], []
    wanted = a.get("games") or []
    for w in [wanted] if isinstance(wanted, str) else wanted:          # "SoT", "helldivers": the game list's own names first
        g = find_game(str(w))
        if g is not None and g.key in by_key:
            if by_key[g.key] not in picked:
                picked.append(by_key[g.key])
        else:
            rest.append(w)
    more, unknown = _match_names(rest, [(e["name"], e) for e in entries])
    picked += [e for e in more if e not in picked]
    if unknown:
        return (f"I can't tell which game {', '.join(repr(u) for u in unknown)} is. Games to follow: "
                + ", ".join(e["name"] for e in entries) + ".")
    if not picked:
        return "Which games? Ask them."
    keys = {e["key"] for e in mine}
    keys = keys | {e["key"] for e in picked} if action == "follow" else keys - {e["key"] for e in picked}
    _, text = await board.follow_as(guild, author, sorted(keys))
    return text


# ================================================================ self-serve roles
async def _roles(bot, guild, author, channel, s, a: dict, turn: Turn) -> str:
    cog = bot.get_cog("Colours")
    if cog is None:
        return "Role menus aren't running."
    menus = [m for m in await bot.db.menus(guild.id) if m.message_id and _public(guild, m.channel_id)]
    wearing = {r.id for r in getattr(author, "roles", [])}
    options = []   # (role name, (menu, role))
    for m in menus:
        for o in m.options:
            role = guild.get_role(o.role_id)
            if role is not None:
                options.append((o.label or role.name, (m, role)))
                if o.label and o.label != role.name:
                    options.append((role.name, (m, role)))
    if not options:
        return "There are no role menus to pick from."
    action = a.get("action")
    if action == "list":
        lines = []
        for m in menus:
            names = [f"{(o.label or guild.get_role(o.role_id).name)}{' (wearing)' if o.role_id in wearing else ''}"
                     for o in m.options if guild.get_role(o.role_id) is not None]
            lines.append(f"- {m.title} ({'pick one' if m.mode == 'single' else 'pick any'}): {', '.join(names)}")
        return "\n".join(lines)
    picked, unknown = _match_names(a.get("roles") or [], options)
    if unknown:
        return (f"{', '.join(repr(u) for u in unknown)} isn't on a role menu (or matches several). "
                "Use action 'list' to see the roles they can pick.")
    if not picked:
        return "Which roles? Ask them."
    out = []
    for m in {id(menu): menu for menu, _ in picked}.values():
        mine = {o.role_id for o in m.options if o.role_id in wearing}
        these = {role.id for menu, role in picked if menu is m}
        if action == "add":
            chosen = list(these)[:1] if m.mode == "single" else list(mine | these)
        else:
            chosen = list(mine - these)
        _, text, zones = await cog.apply_as(guild, author, m, chosen)
        if zones:
            text += (" That region spans several time zones: ask which is closest ("
                     + ", ".join(label for label, _ in zones) + ") and set it with me/timezone_set.")
        out.append(text)
    return " ".join(out)


# ================================================================ ships and pirates
async def _ship(bot, guild, author, channel, s, a: dict, turn: Turn) -> str:
    ledger = bot.get_cog("ShipLedger")
    if ledger is None:
        return "The Ship's Ledger isn't running."
    action = a.get("action")
    if action == "mine":
        ships = await bot.db.ships(guild.id, author.id)
        return ("Their ships: " + ", ".join(f"{x.name} ({x.kind})" for x in ships)) if ships else \
            "They haven't registered a ship. They can ask you to, or use /ship register."
    if action == "show":
        if a.get("ship"):
            ship = await ledger.find_ship(guild.id, str(a["ship"]))
            if ship is None:
                return f"There's no ship called \"{a['ship']}\" (or more than one)."
        else:
            mine = await bot.db.ships(guild.id, author.id)
            if not mine:
                return "They haven't registered a ship."
            ship = mine[0]
        return _embed_text(await ledger.ship_embed(guild, ship))
    if action == "register":
        if not a.get("name") or not a.get("kind"):
            return "It needs her name and whether she's a Sloop, Brigantine or Galleon; ask them."
        _, text = await ledger.register_as(guild.id, author.id, str(a["name"]), str(a["kind"]), a.get("motto"))
        return text
    if action == "edit":
        _, text = await ledger.edit_as(guild.id, author, a.get("ship"), name=a.get("name"), kind=a.get("kind"),
                                       motto=a.get("motto"), own_only=True)
        return text
    if action == "retire":
        _, text = await ledger.retire_as(guild.id, author, a.get("ship"), own_only=True)
        return text
    return f"I don't know how to {action} a ship."


async def _pirate(bot, guild, author, channel, s, a: dict, turn: Turn) -> str:
    ledger = bot.get_cog("ShipLedger")
    if ledger is None:
        return "The Ship's Ledger isn't running."
    if a.get("action") == "set":
        if a.get("gamertag") is None and a.get("motto") is None:
            return "Set what? A gamertag, a motto or both."
        return await ledger.pirate_set_as(guild.id, author.id, a.get("gamertag"), a.get("motto"))
    who = author
    wanted = str(a.get("member") or "").strip()
    if wanted:
        import re
        m = re.fullmatch(r"<@!?(\d+)>", wanted)
        if m:
            who = guild.get_member(int(m.group(1)))
        else:
            members = [x for x in getattr(guild, "members", []) if not getattr(x, "bot", False)]
            hits, _ = _match_names([wanted], [(x.display_name, x) for x in members]
                                   + [(x.name, x) for x in members if x.name != x.display_name])
            who = hits[0] if hits else None
        if who is None:
            return f"I can't find one member called \"{wanted}\"."
    return _embed_text(await ledger.pirate_embed(guild.id, who))


_TOOLS = {"voyage": _voyage, "crew": _crew, "music": _music, "me": _me, "follow": _follow, "roles": _roles,
          "ship": _ship, "pirate": _pirate}
