"""Parley's hands (1.3.1): voyages, crews and music done in plain speech, for the member who asked.

Each action goes through the same code as the slash command or button it stands for, as the member who
asked (never anyone else), and returns a short plain result for Claude to put in its own words. Members
still on the Gangplank can't act.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import discord

from . import games
from .crew_logic import clean_title, now_utc
from .voyage_logic import (REPEATS, ParseError, format_reminders, is_weekday_name, parse_date, parse_reminders,
                           parse_time, split_zone, to_utc, zone_label)

log = logging.getLogger("plunderbot.parley")

ACTION_TOOLS = [
    {"name": "plan_voyage",
     "description": "Schedule a voyage (a planned session) with the person asking as organizer, like /voyage create. "
                    "Only when they clearly ask you to plan or schedule one. You need at least a title (make a short "
                    "one up from what they said if they didn't give one), a date and a time; ask for a missing date "
                    "or time instead of guessing.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string"},
         "date": {"type": "string", "description": "As they said it: 'friday', 'tomorrow', '10/3', 'today'."},
         "time": {"type": "string", "description": "As they said it: '8pm', '20:30', '8pm ET'."},
         "game": {"type": "string", "description": "The game's name, or leave out for a general server event."},
         "size": {"type": "string", "description": "Crew size if they said one, e.g. 'Galleon'."},
         "seats": {"type": "integer", "description": "Only if they asked for a specific number of seats."},
         "details": {"type": "string"},
         "repeat": {"type": "string", "enum": list(REPEATS), "description": "Only if they asked for it to repeat."},
         "reminders": {"type": "string", "description": "Only if they asked, e.g. '1h' or 'none'."}},
         "required": ["title", "date", "time"]}},
    {"name": "answer_voyage",
     "description": "Sign the person asking up for a voyage (or take their answer back), like its buttons. Get the "
                    "voyage's number from upcoming_voyages first.",
     "input_schema": {"type": "object", "properties": {
         "voyage": {"type": "integer", "description": "The voyage's number (#12 in upcoming_voyages)."},
         "answer": {"type": "string", "enum": ["aboard", "maybe", "cant", "clear"]}},
         "required": ["voyage", "answer"]}},
    {"name": "cancel_voyage",
     "description": "Cancel a voyage the person asking organized (everyone who signed up is told). Only when they "
                    "clearly ask to cancel it.",
     "input_schema": {"type": "object", "properties": {"voyage": {"type": "integer"}}, "required": ["voyage"]}},
    {"name": "start_crew",
     "description": "Call a crew for playing right now, with the person asking as captain, like /crew start. Only "
                    "when they clearly ask for one.",
     "input_schema": {"type": "object", "properties": {
         "game": {"type": "string"},
         "size": {"type": "string", "description": "e.g. 'Sloop'; leave out for the game's usual size."},
         "activity": {"type": "string", "description": "e.g. 'Fort', only if they said."},
         "note": {"type": "string"},
         "name": {"type": "string", "description": "A session name, only if they gave one."}},
         "required": ["game"]}},
    {"name": "join_crew",
     "description": "Put the person asking aboard a crew that's mustering or sailing (get its number from open_crews), "
                    "or take them off it with leave: true.",
     "input_schema": {"type": "object", "properties": {
         "crew": {"type": "integer", "description": "The crew's number (#7 in open_crews)."},
         "leave": {"type": "boolean"}},
         "required": ["crew"]}},
    {"name": "close_crew",
     "description": "Close the crew the person asking is captain of (its voice channel goes too).",
     "input_schema": {"type": "object", "properties": {}}},
]
ACTION_NAMES = {t["name"] for t in ACTION_TOOLS}


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


async def act(bot, guild: discord.Guild, author, channel, name: str, args: dict) -> str:
    """Do one action for the member who asked. Returns what happened, for Claude to relay."""
    if author is None or not hasattr(author, "voice"):
        return "Only a server member can ask for that."
    s = await bot.db.get_settings(guild.id)
    if s.pending_role_id and any(r.id == s.pending_role_id for r in getattr(author, "roles", [])):
        return "They're still on the Gangplank; a Harbormaster has to let them aboard first."
    try:
        return await _ACTIONS[name](bot, guild, author, channel, s, args)
    except (ValueError, TypeError) as e:
        return f"That didn't work: {e}"


async def _plan_voyage(bot, guild, author, channel, s, a: dict) -> str:
    cog = bot.get_cog("Voyages")
    if cog is None:
        return "Voyages are switched off."
    title = " ".join(str(a.get("title") or "").split())[:80]
    if not title:
        return "It needs a title."
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
    repeat = a.get("repeat") if a.get("repeat") in REPEATS else "none"
    channel_to = cog.voyage_channel(guild, s) or channel
    if channel_to is None or isinstance(channel_to, discord.Thread):
        return "There's no voyage channel to post in; a Quartermaster sets one with /admin voyages channel."
    v = await cog.launch(guild, channel_to, author.id, title=title,
                         description=(str(a.get("details") or "").strip()[:1000] or None), profile=profile,
                         size_label=size_label, capacity=capacity, starts=starts, duration=120, minutes=minutes,
                         repeat=repeat, ping_role="posted")
    if v is None:
        return "PlunderBot couldn't post the voyage card."
    link = f"https://discord.com/channels/{v.guild_id}/{v.channel_id}/{v.message_id}"
    read_as = "their own time zone" if whose == "yours" else ("the zone they typed" if whose == "typed"
                                                               else f"the server's time zone ({zone_label(tz, starts)})")
    return (f"Planned voyage #{v.id} \"{title}\"{f' ({profile.name} {size_label})' if profile else ''} at "
            f"<t:{int(starts.timestamp())}:F> (the time was read in {read_as}), with them Aboard. Reminders: "
            f"{format_reminders(minutes)}. Card: {link}. They can change it with /voyage edit.")


async def _answer_voyage(bot, guild, author, channel, s, a: dict) -> str:
    cog = bot.get_cog("Voyages")
    v = await bot.db.get_voyage(int(a.get("voyage") or 0))
    if cog is None or v is None or v.guild_id != guild.id:
        return "There's no voyage with that number; check upcoming_voyages."
    answer = a.get("answer")
    if answer not in ("aboard", "maybe", "cant", "clear"):
        return "The answer must be aboard, maybe, cant or clear."
    ok, reply = await cog.rsvp_as(guild, v.id, author.id, None if answer == "clear" else answer)
    return reply if ok else "That voyage has already started or ended."


async def _cancel_voyage(bot, guild, author, channel, s, a: dict) -> str:
    cog = bot.get_cog("Voyages")
    v = await bot.db.get_voyage(int(a.get("voyage") or 0))
    if cog is None or v is None or v.guild_id != guild.id:
        return "There's no voyage with that number."
    if v.organizer_id != author.id:
        return "Only its organizer can cancel it (or a mod with /voyage cancel)."
    if not await cog.apply_cancel(guild, v.id):
        return "It has already started or ended."
    return f"Cancelled \"{v.title}\"; everyone who signed up was told."


async def _start_crew(bot, guild, author, channel, s, a: dict) -> str:
    cog = bot.get_cog("CrewCall")
    if cog is None:
        return "Crew calls are switched off."
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
        return "They're already captaining a crew; they need to close it first (close_crew)."
    if problem:
        return "PlunderBot couldn't post the crew card."
    if profile.open_ended or crew.full:
        await cog.sail(guild, crew.id)
    link = f"https://discord.com/channels/{crew.guild_id}/{crew.channel_id}/{crew.message_id}"
    return (f"Called crew #{crew.id}: {profile.name} {size.label}{f' on {ship.name}' if ship else ''}, with them as "
            f"captain. The card is up at {link}; the game's ping role was tagged.")


async def _join_crew(bot, guild, author, channel, s, a: dict) -> str:
    cog = bot.get_cog("CrewCall")
    crew = await bot.db.get_crew(int(a.get("crew") or 0))
    if cog is None or crew is None or crew.guild_id != guild.id:
        return "There's no crew with that number; check open_crews."
    _, reply = await cog.join_leave_as(guild, crew.id, author.id, "leave" if a.get("leave") else "join")
    return reply


async def _close_crew(bot, guild, author, channel, s, a: dict) -> str:
    cog = bot.get_cog("CrewCall")
    crew = await bot.db.active_crew_led_by(guild.id, author.id)
    if cog is None or crew is None:
        return "They aren't captaining a crew."
    await cog.end(guild, crew.id, "closed")
    return "Closed their crew, and its voice channel."


_ACTIONS = {"plan_voyage": _plan_voyage, "answer_voyage": _answer_voyage, "cancel_voyage": _cancel_voyage,
            "start_crew": _start_crew, "join_crew": _join_crew, "close_crew": _close_crew}
