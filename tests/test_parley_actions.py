"""Parley's hands: 1.3.1 planned voyages and called crews in plain speech; 1.6.0 covers everything a member can
do with a command or a button, as whoever asked, with Confirm buttons for cancelling a voyage and retiring a ship."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from plunderbot.parley_actions import ACTION_TOOLS, CONFIRM, Turn, act, find_game
from tests.test_daisho import Role, env  # noqa: F401


class Mate(SimpleNamespace):
    """A member who can be given roles."""

    def __init__(self, uid, roles=(), mod=False, name=None):
        perms = SimpleNamespace(manage_events=mod, manage_guild=mod, administrator=False, manage_channels=mod,
                                manage_messages=mod, manage_roles=mod)
        super().__init__(id=uid, display_name=name or f"m{uid}", name=name or f"m{uid}", voice=None, bot=False,
                         roles=[r if isinstance(r, Role) else Role(r, "r") for r in roles], guild_permissions=perms,
                         display_avatar=None)

    async def add_roles(self, *roles, reason=None):
        self.roles += [r for r in roles if r not in self.roles]

    async def remove_roles(self, *roles, reason=None):
        self.roles = [r for r in self.roles if r not in roles]


def who(uid, roles=(), mod=False):
    return Mate(uid, roles, mod)


def test_names_are_matched_carefully():
    from plunderbot.parley_actions import _match_names
    opts = [("🇺🇸", "flag"), ("Europe", "eu"), ("North America - East", "na-e"), ("North America - West", "na-w")]
    assert _match_names(["Moderator"], opts) == ([], ["Moderator"])      # an emoji name never matches everything
    assert _match_names(["🇺🇸"], opts) == (["flag"], [])                     # but can be asked for exactly
    assert _match_names("europe", opts) == (["eu"], [])                     # a lone string is one name
    assert _match_names(["north america"], opts) == ([], ["north america"])  # two matches: ask, don't guess


def T(name):
    return next(t for t in ACTION_TOOLS if t["name"] == name)


def test_eight_grouped_tools_and_games_by_name():
    assert find_game("SoT").key == "sot" and find_game("sea of thieves").key == "sot"
    assert find_game("nope") is None and find_game(None) is None
    assert find_game("Server event").key == "event" and find_game("Server event", crew_call=True) is None
    assert {t["name"] for t in ACTION_TOOLS} == {"voyage", "crew", "music", "me", "follow", "roles", "ship", "pirate"}
    assert set(T("voyage")["input_schema"]["properties"]["action"]["enum"]) == {
        "plan", "answer", "edit", "series", "skip_date", "restore_date", "cancel"}
    assert set(T("music")["input_schema"]["properties"]["action"]["enum"]) >= {
        "play", "queue", "skip", "pause", "resume", "stop", "clear", "shuffle", "remove", "move", "repeat", "seek",
        "volume"}
    assert "lyrics" not in json.dumps(T("music")["input_schema"])          # lyrics stay with /music lyrics
    assert CONFIRM == {("voyage", "cancel"), ("ship", "retire")}
    for t in ACTION_TOOLS:                                                  # every tool is valid JSON Schema-ish
        assert t["input_schema"]["required"] == ["action"] and len(t["description"]) < 1200


async def _setup(env, monkeypatch):
    bot, cog, guild = env

    async def no_event(*a, **kw):
        return None
    monkeypatch.setattr(bot.get_cog("Voyages"), "sync_event", no_event)
    guild.default_role = guild.roles[0]          # everyone can see the test channels
    await bot.db.update_settings(10, voyage_channel_id=21, crew_channel_id=20, pending_role_id=50,
                                 timezone="America/Los_Angeles")
    return bot, guild, guild.chans[20]


async def test_voyages_plan_answer_edit_skip_and_cancel_with_confirm(env, monkeypatch):
    bot, guild, here = await _setup(env, monkeypatch)
    boxer, twiddles, newbie, mod = who(1), who(2), who(3, roles=[50]), who(4, mod=True)
    out = await act(bot, guild, newbie, here, "voyage", {"action": "plan", "title": "x", "date": "tomorrow", "time": "8pm"})
    assert "Gangplank" in out
    assert "date and a time" in await act(bot, guild, boxer, here, "voyage", {"action": "plan", "title": "x"})
    out = await act(bot, guild, boxer, here, "voyage", {"action": "plan", "title": "Fort Night", "date": "tomorrow",
                                                        "time": "8pm", "game": "SoT", "size": "Galleon", "repeat": "weekly"})
    assert out.startswith("Planned voyage #") and "server's time zone" in out and "Repeats: Every week" in out, out
    v = (await bot.db.voyages_with_status("scheduled", guild_id=10))[0]
    assert (v.organizer_id, v.capacity, v.channel_id, v.game_key, v.repeat) == (1, 4, 21, "sot", "weekly")
    assert "past" in await act(bot, guild, boxer, here, "voyage", {"action": "plan", "title": "x", "date": "today",
                                                                   "time": "12:01am"})
    assert "don't know the game" in await act(bot, guild, boxer, here, "voyage", {
        "action": "plan", "title": "x", "date": "tomorrow", "time": "8pm", "game": "Tetris 99"})
    # answers
    await act(bot, guild, twiddles, here, "voyage", {"action": "answer", "voyage": v.id, "answer": "aboard"})
    assert (await bot.db.rsvps(v.id)).aboard == [1, 2]
    # edits: only the organizer (or a mod), and only what was asked
    assert "Only its organizer" in await act(bot, guild, twiddles, here, "voyage",
                                             {"action": "edit", "voyage": v.id, "time": "9pm"})
    out = await act(bot, guild, boxer, here, "voyage", {"action": "edit", "voyage": v.id, "time": "9pm", "seats": 3})
    v2 = await bot.db.get_voyage(v.id)
    assert v2.capacity == 3 and v2.title == "Fort Night" and v2.starts_at != v.starts_at, out
    assert "Nothing to change" in await act(bot, guild, boxer, here, "voyage", {"action": "edit", "voyage": v.id})
    # by chat it's the organizer's alone, even for a mod (who still has /voyage edit)
    out = await act(bot, guild, mod, here, "voyage", {"action": "edit", "voyage": v.id, "title": "Fort Night II"})
    assert "/voyage edit" in out and (await bot.db.get_voyage(v.id)).title == "Fort Night"
    await act(bot, guild, boxer, here, "voyage", {"action": "edit", "voyage": v.id, "title": "Fort Night II"})
    assert (await bot.db.get_voyage(v.id)).title == "Fort Night II"
    # the series, and skipping a date
    assert "week" in (await act(bot, guild, twiddles, here, "voyage", {"action": "series", "voyage": v.id})).lower()
    later = (datetime.fromisoformat(v2.starts_at) + timedelta(days=14)).astimezone(
        timezone(timedelta(hours=-7))).date().isoformat()
    await act(bot, guild, boxer, here, "voyage", {"action": "skip_date", "voyage": v.id, "date": later})
    assert later in ((await bot.db.get_voyage(v.id)).skips or "")
    await act(bot, guild, boxer, here, "voyage", {"action": "restore_date", "voyage": v.id, "date": later})
    assert later not in ((await bot.db.get_voyage(v.id)).skips or "")
    # cancelling waits for the organizer's Confirm button
    assert "Only its organizer" in await act(bot, guild, twiddles, here, "voyage", {"action": "cancel", "voyage": v.id},
                                             Turn())
    turn = Turn()
    out = await act(bot, guild, boxer, here, "voyage", {"action": "cancel", "voyage": v.id, "whole_series": True}, turn)
    assert out.startswith("Not done yet") and len(turn.pending) == 1
    assert (await bot.db.get_voyage(v.id)).status == "scheduled"
    p = turn.pending[0]
    assert p.user_id == 1 and p.args == {"action": "cancel", "voyage": v.id, "whole_series": True} and "whole series" in p.what
    out = await act(bot, guild, boxer, here, p.tool, p.args, confirmed=True)
    assert "Cancelled the whole series" in out and (await bot.db.get_voyage(v.id)).status == "cancelled"


async def test_crews_start_join_leave_rename_close(env, monkeypatch):
    bot, guild, here = await _setup(env, monkeypatch)
    boxer, twiddles = who(1), who(2)
    out = await act(bot, guild, twiddles, here, "crew", {"action": "start", "game": "sea of thieves", "size": "Galleon",
                                                         "note": "chill"})
    assert out.startswith("Called crew #"), out
    crew = (await bot.db.active_crews(10))[0]
    assert (crew.captain_id, crew.capacity, crew.note) == (2, 4, "chill")
    assert "already captaining" in await act(bot, guild, twiddles, here, "crew", {"action": "start", "game": "SoT"})
    await act(bot, guild, boxer, here, "crew", {"action": "join", "crew": crew.id})
    assert 1 in (await bot.db.get_crew(crew.id)).members
    await act(bot, guild, boxer, here, "crew", {"action": "leave", "crew": crew.id})
    assert 1 not in (await bot.db.get_crew(crew.id)).members
    assert "aren't captaining" in await act(bot, guild, boxer, here, "crew", {"action": "close"})
    await act(bot, guild, boxer, here, "crew", {"action": "rename", "name": "Nope"})
    assert (await bot.db.get_crew(crew.id)).title is None                    # not their crew
    await act(bot, guild, twiddles, here, "crew", {"action": "rename", "name": "Rum Runners"})
    assert (await bot.db.get_crew(crew.id)).title == "Rum Runners"
    assert "Closed" in await act(bot, guild, twiddles, here, "crew", {"action": "close"})
    assert not (await bot.db.get_crew(crew.id)).active


async def test_their_own_time_zone_and_birthday(env, monkeypatch):
    bot, guild, here = await _setup(env, monkeypatch)
    boxer = who(1)
    out = await act(bot, guild, boxer, here, "me", {"action": "timezone_set", "zone": "America/Denver"})
    assert await bot.db.member_timezone(1) == "America/Denver", out
    assert "M" in await act(bot, guild, boxer, here, "me", {"action": "timezone_show"})   # Mountain time
    assert "Narnia" in await act(bot, guild, boxer, here, "me", {"action": "timezone_set", "zone": "Narnia"})
    await act(bot, guild, boxer, here, "me", {"action": "timezone_clear"})
    assert await bot.db.member_timezone(1) is None
    assert "month" in await act(bot, guild, boxer, here, "me", {"action": "birthday_set", "month": 13, "day": 1})
    await act(bot, guild, boxer, here, "me", {"action": "birthday_set", "month": 3, "day": 3})
    assert await bot.db.get_birthday(10, 1) == (3, 3)
    assert "March 3" in await act(bot, guild, boxer, here, "me", {"action": "birthday_show"})
    await act(bot, guild, boxer, here, "me", {"action": "birthday_remove"})
    assert await bot.db.get_birthday(10, 1) is None


async def test_following_games_and_picking_roles(env, monkeypatch):
    bot, guild, here = await _setup(env, monkeypatch)
    sot, hd, xbox, pc, eu, mods = (Role(60, "Sea of Thieves"), Role(61, "Helldivers 2"), Role(70, "Xbox"),
                                   Role(71, "PC"), Role(72, "Europe"), Role(73, "Mods"))
    mods.permissions = __import__("discord").Permissions(manage_messages=True)
    for r in (sot, hd, xbox, pc, eu, mods):
        r.mention = f"<@&{r.id}>"
    guild.roles += [sot, hd, xbox, pc, eu, mods]
    board = bot.get_cog("Noticeboard")

    async def entries(g, with_threads=True):
        return [{"key": "sot", "name": "Sea of Thieves", "role_id": 60, "thread": None},
                {"key": "hd2", "name": "Helldivers 2", "role_id": 61, "thread": None}]
    monkeypatch.setattr(board, "game_entries", entries)
    boxer = who(1)
    out = await act(bot, guild, boxer, here, "follow", {"action": "follow", "games": ["helldivers"]})
    assert [r.id for r in boxer.roles] == [61], out
    await act(bot, guild, boxer, here, "follow", {"action": "follow", "games": ["SoT", "Sea of Thieves"]})
    assert {r.id for r in boxer.roles} == {60, 61}
    assert "They follow: Sea of Thieves, Helldivers 2" in await act(bot, guild, boxer, here, "follow", {"action": "list"})
    await act(bot, guild, boxer, here, "follow", {"action": "unfollow", "games": ["helldivers 2"]})
    assert {r.id for r in boxer.roles} == {60}
    assert "can't tell which game" in await act(bot, guild, boxer, here, "follow", {"action": "follow", "games": ["Tetris"]})
    # role menus: only roles on a posted menu, single-pick menus swap
    plat = await bot.db.create_menu(10, "platform", "Platform", None, "multi")
    region = await bot.db.create_menu(10, "region", "Region", None, "single")
    for m, rid in ((plat, 70), (plat, 71), (region, 72), (region, 73)):
        await bot.db.set_menu_option(m.id, rid, None, None, None)
    await bot.db.update_menu(plat.id, channel_id=20, message_id=9001)
    assert "no role menus" not in await act(bot, guild, boxer, here, "roles", {"action": "list"})
    assert "isn't on a role menu" in await act(bot, guild, boxer, here, "roles", {"action": "add", "roles": ["Europe"]})
    await bot.db.update_menu(region.id, channel_id=20, message_id=9002)
    await act(bot, guild, boxer, here, "roles", {"action": "add", "roles": ["xbox", "pc"]})
    assert {70, 71} <= {r.id for r in boxer.roles}
    await act(bot, guild, boxer, here, "roles", {"action": "remove", "roles": ["Xbox"]})
    assert 70 not in {r.id for r in boxer.roles} and 71 in {r.id for r in boxer.roles}
    await act(bot, guild, boxer, here, "roles", {"action": "add", "roles": ["Europe"]})
    assert 72 in {r.id for r in boxer.roles}
    out = await act(bot, guild, boxer, here, "roles", {"action": "add", "roles": ["Mods"]})
    assert 73 not in {r.id for r in boxer.roles} and "couldn't" in out.lower(), out   # never a moderator role
    assert "(wearing)" in await act(bot, guild, boxer, here, "roles", {"action": "list"})


async def test_ships_and_pirates(env, monkeypatch):
    bot, guild, here = await _setup(env, monkeypatch)
    boxer, twiddles = who(1), who(2)
    assert "Sloop, Brigantine or Galleon" in await act(bot, guild, boxer, here, "ship", {"action": "register",
                                                                                        "name": "Salty Mermaid"})
    out = await act(bot, guild, boxer, here, "ship", {"action": "register", "name": "Salty Mermaid", "kind": "Galleon",
                                                      "motto": "Arr"})
    assert "Salty Mermaid" in out and "Salty Mermaid (Galleon)" in await act(bot, guild, boxer, here, "ship",
                                                                            {"action": "mine"})
    dup = await act(bot, guild, boxer, here, "ship", {"action": "register", "name": "salty mermaid", "kind": "Sloop"})
    assert len(await bot.db.ships(10, 1)) == 1, dup
    assert "Salty Mermaid" in await act(bot, guild, twiddles, here, "ship", {"action": "show", "ship": "salty mermaid"})
    assert "not" in (await act(bot, guild, twiddles, here, "ship", {"action": "edit", "ship": "Salty Mermaid",
                                                                    "kind": "Sloop"})).lower()
    mod = who(4, mod=True)                        # by chat, a mod's own ships only (they have /ship edit)
    assert "not" in (await act(bot, guild, mod, here, "ship", {"action": "edit", "ship": "Salty Mermaid",
                                                               "kind": "Sloop"})).lower()
    assert (await bot.db.ships(10, 1))[0].kind == "Galleon"
    await act(bot, guild, boxer, here, "ship", {"action": "edit", "ship": "Salty Mermaid", "kind": "Brigantine",
                                                "motto": "-"})
    ship = (await bot.db.ships(10, 1))[0]
    assert (ship.kind, ship.motto) == ("Brigantine", None)
    turn = Turn()
    assert "not" in (await act(bot, guild, twiddles, here, "ship", {"action": "retire", "ship": "Salty Mermaid"},
                               turn)).lower() and not turn.pending
    out = await act(bot, guild, boxer, here, "ship", {"action": "retire", "ship": "Salty Mermaid"}, turn)
    assert out.startswith("Not done yet") and not (await bot.db.ships(10, 1))[0].retired
    p = turn.pending[0]
    await act(bot, guild, boxer, here, p.tool, p.args, confirmed=True)
    assert await bot.db.ships(10, 1) == []
    # pirate profiles
    await act(bot, guild, boxer, here, "pirate", {"action": "set", "gamertag": "BoxerTheBold", "motto": "Yo ho"})
    assert await bot.db.pirate_profile(10, 1) == ("BoxerTheBold", "Yo ho")
    assert "BoxerTheBold" in await act(bot, guild, twiddles, here, "pirate", {"action": "profile", "member": "<@1>"})
    assert "can't find" in await act(bot, guild, twiddles, here, "pirate", {"action": "profile", "member": "<@404>"})


async def test_confirm_buttons_only_answer_the_member_who_asked(env, monkeypatch):
    bot, guild, here = await _setup(env, monkeypatch)
    boxer = who(1)
    await act(bot, guild, boxer, here, "voyage", {"action": "plan", "title": "Fort Night", "date": "tomorrow",
                                                  "time": "8pm"})
    v = (await bot.db.voyages_with_status("scheduled", guild_id=10))[0]
    parley = bot.get_cog("Parley")
    turn = Turn()
    await act(bot, guild, boxer, here, "voyage", {"action": "cancel", "voyage": v.id}, turn)
    held = parley.hold(turn.pending)
    from plunderbot.cogs.parley import confirm_view
    view = confirm_view(held)
    assert [c.custom_id for c in view.children] == [f"parley:ok:{held[0].token}", f"parley:no:{held[0].token}"]
    assert view.children[0].item.label.startswith("Yes, cancel \"Fort Night\"")

    class Response:
        def __init__(self):
            self.sent = []

        async def send_message(self, text, **kw):
            self.sent.append(text)

        async def defer(self):
            pass

    class Message:
        content = "Want me to cancel Fort Night?"

        def __init__(self):
            self.edits = []

        async def edit(self, **kw):
            self.edits.append(kw)

    def press(member):
        return SimpleNamespace(user=member, guild=guild, channel=here, response=Response(), message=Message())

    stranger = press(who(2))
    await parley.on_confirm(stranger, "ok", held[0].token)
    assert "Only <@1>" in stranger.response.sent[0] and (await bot.db.get_voyage(v.id)).status == "scheduled"
    mine = press(boxer)
    await parley.on_confirm(mine, "ok", held[0].token)
    assert (await bot.db.get_voyage(v.id)).status == "cancelled"
    assert "✅ Cancelled" in mine.message.edits[0]["content"] and mine.message.edits[0]["view"] is None
    again = press(boxer)
    await parley.on_confirm(again, "ok", held[0].token)                       # used up
    assert "run out of time" in again.response.sent[0]
    # No leaves it as it was
    await act(bot, guild, boxer, here, "voyage", {"action": "plan", "title": "Skull Fort", "date": "tomorrow",
                                                  "time": "9pm"})
    v2 = next(x for x in await bot.db.voyages_with_status("scheduled", guild_id=10) if x.title == "Skull Fort")
    turn = Turn()
    await act(bot, guild, boxer, here, "voyage", {"action": "cancel", "voyage": v2.id}, turn)
    token = parley.hold(turn.pending)[0].token
    no = press(boxer)
    await parley.on_confirm(no, "no", token)
    assert (await bot.db.get_voyage(v2.id)).status == "scheduled" and "Left as it was" in no.message.edits[0]["content"]
    # and a held action runs out
    turn = Turn()
    await act(bot, guild, boxer, here, "voyage", {"action": "cancel", "voyage": v2.id}, turn)
    held = parley.hold(turn.pending)
    held[0].expires = 0
    late = press(boxer)
    await parley.on_confirm(late, "ok", held[0].token)
    assert "run out of time" in late.response.sent[0] and (await bot.db.get_voyage(v2.id)).status == "scheduled"


async def test_parley_offers_the_actions_and_caches_them(env):
    bot, cog, guild = env
    parley = bot.get_cog("Parley")
    out = await parley.run_tool(guild, await bot.db.get_settings(10), "crew", {"action": "close"}, "2026-09-30",
                                who(9), None)
    assert "aren't captaining" in out
    from plunderbot.parley_logic import TOOLS, system_blocks, system_prompt
    assert not {"play_music", "music_queue"} & {t["name"] for t in TOOLS}
    rules, moment = system_blocks(server="B", now_local=datetime.now(), zone_label="PDT", asker="Boxer", asker_zone="",
                                  lookups_left=None, cusses=["Sink me!"])
    assert "never for anyone else" in rules and "Boxer" not in rules and "Boxer" in moment
    assert "can't search the web" in moment and "/music lyrics" in rules
    assert "Boxer" in system_prompt(server="B", now_local=datetime.now(), zone_label="PDT", asker="Boxer",
                                    asker_zone="", lookups_left=None, cusses=["Sink me!"])
    # the Claude client marks the tools and the rules for caching
    from plunderbot.ai import Claude
    sent = {}

    class Resp:
        status = 200

        async def json(self, content_type=None):
            return {"content": [], "stop_reason": "end_turn", "usage": {}}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class Session:
        closed = False

        def post(self, url, json=None, headers=None):
            sent.update(json)
            return Resp()

    c = Claude("k", "claude-haiku-4-5")
    c._session = Session()
    await c.create(system=[rules, moment], messages=[{"role": "user", "content": "hi"}],
                   tools=TOOLS + ACTION_TOOLS, cache=True)
    assert sent["system"][0]["cache_control"] == {"type": "ephemeral"} and "cache_control" not in sent["system"][1]
    assert sent["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert all("cache_control" not in t for t in sent["tools"][:-1]) and "cache_control" not in ACTION_TOOLS[-1]
    await c.create(system="plain", messages=[], tools=TOOLS)
    assert sent["system"] == "plain" and "cache_control" not in sent["tools"][-1]


async def test_skipping_this_very_date_is_confirmed_and_staff_cards_stay_private(env, monkeypatch):
    bot, guild, here = await _setup(env, monkeypatch)
    from tests.test_daisho import Text

    class Staff(Text):
        def permissions_for(self, who):
            return SimpleNamespace(view_channel=False, send_messages=True, embed_links=True, attach_files=True)
    guild.chans[22] = Staff(22, "quartermasters")
    boxer, twiddles = who(1), who(2)
    out = await act(bot, guild, boxer, here, "voyage", {"action": "plan", "title": "Fort Night", "date": "tomorrow",
                                                        "time": "8pm", "repeat": "every other week"})
    v = (await bot.db.voyages_with_status("scheduled", guild_id=10))[0]
    assert v.repeat == "biweekly", out
    own = datetime.fromisoformat(v.starts_at).astimezone(timezone(timedelta(hours=-7))).date().isoformat()
    turn = Turn()
    out = await act(bot, guild, boxer, here, "voyage", {"action": "skip_date", "voyage": v.id, "date": own}, turn)
    assert out.startswith("Not done yet") and "the series carries on" in turn.pending[0].what
    assert (await bot.db.get_voyage(v.id)).status == "scheduled"
    p = turn.pending[0]
    await act(bot, guild, boxer, here, p.tool, p.args, confirmed=True)
    assert (await bot.db.get_voyage(v.id)).status == "cancelled"
    # a voyage posted in a staff channel can't be answered by number
    await bot.db.update_voyage(v.id, status="scheduled", channel_id=22)
    assert "no voyage" in await act(bot, guild, twiddles, here, "voyage", {"action": "answer", "voyage": v.id,
                                                                           "answer": "aboard"})
    assert 2 not in (await bot.db.rsvps(v.id)).aboard
