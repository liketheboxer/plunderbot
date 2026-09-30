"""The Ship's Ledger: ships, Captain's Log readings and pirate profiles. Claude is faked; no network, no money."""
import io
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from plunderbot import ledger_logic as L
from plunderbot.crew_logic import iso

T0 = datetime(2026, 9, 29, 20, tzinfo=timezone.utc)


# ------------------------------------------------------------ rules
def test_parse_number():
    assert L.parse_number("12,345") == 12345
    assert L.parse_number("12 345 gold") == 12345
    assert L.parse_number("12.345") == 12345
    assert L.parse_number("12.3k") == 12300
    assert L.parse_number("1.2m") == 1_200_000
    assert L.parse_number("0") == 0
    assert L.parse_number("lots") is None and L.parse_number(None) is None


def test_tool_input_is_tidied():
    haul = L.from_tool_input({"is_captains_log": True, "gold": "48,210", "doubloons": -3, "emissary": " Gold  Hoarders `5` ",
                              "reputation": [{"company": "Merchant Alliance", "amount": "1,200"}, {"amount": 5}],
                              "stats": [{"label": "Islands visited", "value": 6}] * 20, "notes": ""})
    assert haul.gold == 48210 and haul.doubloons == 0
    assert haul.emissary == "Gold Hoarders '5'"
    assert haul.reputation == [("Merchant Alliance", 1200)]
    assert len(haul.stats) == L.MAX_ROWS and haul.stats[0] == ("Islands visited", "6")
    assert haul.notes is None and haul.is_log
    assert L.read_response({"content": [{"type": "text", "text": "hm"}]}) is None


def test_form_text_round_trips():
    rows = [("Merchant Alliance", 1200), ("Order of Souls", 800)]
    assert L.parse_reputation(L.reputation_text(rows)) == rows
    assert L.parse_stats("Islands visited: 6\nnonsense\nShips sunk = 2") == [("Islands visited", "6"), ("Ships sunk", "2")]
    assert L.load_rows(L.dump_rows(rows)) == rows and L.load_rows("not json") == []


def _png(w, h):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (w, h), (30, 60, 90)).save(out, "PNG")
    return out.getvalue()


def test_big_screenshots_are_scaled_down():
    import base64
    from PIL import Image
    kind, b64 = L.prepare_image(_png(3840, 2160))
    assert kind == "image/jpeg"
    with Image.open(io.BytesIO(base64.b64decode(b64))) as img:
        assert max(img.size) == L.MAX_IMAGE_EDGE
    kind, _ = L.prepare_image(_png(800, 450))
    assert kind == "image/png"
    from plunderbot.images import ImageError
    with pytest.raises(ImageError):
        L.prepare_image(b"%PDF-1.4 not a picture")


def crewlike(**kw):
    base = dict(id=1, game_key="sot", status="closed", sailed_at=iso(T0 - timedelta(hours=1)), voice_channel_id=9,
                voice_occupied=1, captain_id=1, members=[1, 2], title=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_who_is_asked_and_when():
    assert L.ask_at_end(crewlike(), T0)
    assert not L.ask_at_end(crewlike(game_key="fortnite"), T0)
    assert not L.ask_at_end(crewlike(status="expired"), T0)
    assert not L.ask_at_end(crewlike(voice_occupied=0), T0)
    assert not L.ask_at_end(crewlike(sailed_at=iso(T0 - timedelta(minutes=5))), T0)
    ship = SimpleNamespace(owner_id=2)
    assert L.log_keeper(crewlike(), ship) == 2
    assert L.log_keeper(crewlike(members=[1, 3]), ship) == 1 and L.log_keeper(crewlike(), None) == 1
    older, newer = crewlike(id=1, sailed_at=iso(T0 - timedelta(hours=5))), crewlike(id=2, sailed_at=iso(T0 - timedelta(hours=1)))
    assert L.pick_crew([older, newer], T0).id == 2
    assert L.pick_crew([crewlike(sailed_at=iso(T0 - timedelta(days=2)))], T0) is None


# ------------------------------------------------------------ the flow, with fakes
class FakeClaude:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    async def create(self, **kw):
        self.calls.append(kw)
        return self.script.pop(0)

    async def close(self):
        pass


def reading(**fields):
    data = {"is_captains_log": True, "gold": 48210, "doubloons": 35, "emissary": "Gold Hoarders, grade 5",
            "reputation": [{"company": "Gold Hoarders", "amount": 2400}],
            "stats": [{"label": "Islands visited", "value": "7"}]}
    data.update(fields)
    return {"content": [{"type": "tool_use", "id": "t", "name": "record_captains_log", "input": data}],
            "usage": {"input_tokens": 1800, "output_tokens": 150}}


class Resp:
    def __init__(self):
        self.sent, self.edits, self.modal, self.done = [], [], None, False

    async def defer(self, **kw):
        self.done = True

    async def send_message(self, content=None, **kw):
        self.sent.append(content)
        self.done = True

    async def edit_message(self, **kw):
        self.edits.append(kw)
        self.done = True

    async def send_modal(self, modal):
        self.modal = modal
        self.done = True

    def is_done(self):
        return self.done


class Followup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kw):
        self.sent.append((content, kw))


def interaction(guild, uid, mod=False):
    perms = SimpleNamespace(manage_guild=mod, manage_messages=mod, administrator=False, manage_channels=mod)
    user = SimpleNamespace(id=uid, display_name=f"U{uid}", mention=f"<@{uid}>", guild_permissions=perms,
                           display_avatar=None)
    return SimpleNamespace(user=user, guild=guild, guild_id=guild.id, response=Resp(), followup=Followup(),
                           channel=guild.text)


def screenshot(data):
    async def read():
        return data
    return SimpleNamespace(size=len(data), read=read, content_type="image/png")


@pytest.fixture
async def env(tmp_path):
    from dataclasses import replace
    from tests.test_bot import make_config
    from tests.test_crew import FakeGuild, FakeTextChannel
    from plunderbot.bot import COGS, PlunderBot
    bot = PlunderBot(replace(make_config(tmp_path), anthropic_api_key="sk-test"))
    await bot.db.connect()
    for cog in COGS:
        await bot.load_extension(cog)
    for name, loop in (("Birthdays", "announcer"), ("CrewCall", "upkeep"), ("Voyages", "clock"),
                       ("Gangplank", "upkeep"), ("ShipsLog", "clock"), ("CrowsNest", "watch")):
        getattr(bot.get_cog(name), loop).cancel()
    text = FakeTextChannel(20)
    guild = FakeGuild(10, text)
    guild.members[1] = SimpleNamespace(id=1, display_name="Boxer")
    guild.me = SimpleNamespace(id=999)
    text.permissions_for = lambda who: SimpleNamespace(view_channel=True, send_messages=True, embed_links=True,
                                                       attach_files=True)
    yield bot, bot.get_cog("ShipLedger"), guild, text
    await bot.db.close()


async def sailed_crew(bot, guild, ship=None, members=(1, 2, 3)):
    crew = await bot.db.create_crew(guild_id=guild.id, channel_id=guild.text.id, captain_id=members[0], game_key="sot",
                                    size_label="Galleon", capacity=4, activity=None, note=None,
                                    created_at=iso(T0 - timedelta(hours=2)), expires_at=iso(T0 + timedelta(hours=1)))
    for uid in members[1:]:
        await bot.db.add_crew_member(crew.id, uid, iso(T0 - timedelta(hours=2)))
    return await bot.db.update_crew(crew.id, message_id=1000, status="sailing", ship_id=ship.id if ship else None,
                                    sailed_at=iso(datetime.now(timezone.utc) - timedelta(hours=1)), voice_occupied=1)


async def test_sail_and_port_reminders_ping_the_log_keeper(env):
    bot, cog, guild, text = env
    ship = await bot.db.create_ship(guild_id=10, owner_id=2, name="The Brimstone Belle", kind="Galleon", motto=None,
                                    image=None, created_at=iso(T0))
    crew = await sailed_crew(bot, guild, ship)
    await cog.on_crew_sailed(guild, crew)
    content, kw = text.sent[-1]
    assert "<@2>" in content and "Captain's Log" in content and "reference" not in kw
    crew = await bot.db.update_crew(crew.id, status="closed")
    await cog.on_crew_ended(guild, crew)
    content, kw = text.sent[-1]
    assert "/ship log" in content and "<@2>" in content and kw["reference"].message_id == 1000
    before = len(text.sent)
    await bot.db.update_settings(10, ledger_reminders=0)
    await cog.on_crew_sailed(guild, crew)
    await cog.on_crew_ended(guild, crew)
    assert len(text.sent) == before


async def test_crew_call_reminds_sea_of_thieves_crews_only(env):
    bot, cog, guild, text = env
    crew_cog = bot.get_cog("CrewCall")
    crew = await bot.db.create_crew(guild_id=10, channel_id=20, captain_id=1, game_key="sot", size_label="Sloop",
                                    capacity=2, activity=None, note=None, created_at=iso(T0),
                                    expires_at=iso(T0 + timedelta(hours=1)))
    await crew_cog.sail(guild, crew.id)
    assert any("Captain's Log" in (c or "") for c, _ in text.sent)
    other = await bot.db.create_crew(guild_id=10, channel_id=20, captain_id=5, game_key="fortnite", size_label="Duo",
                                     capacity=2, activity=None, note=None, created_at=iso(T0),
                                     expires_at=iso(T0 + timedelta(hours=1)))
    before = sum("Captain's Log" in (c or "") for c, _ in text.sent)
    await crew_cog.sail(guild, other.id)
    assert sum("Captain's Log" in (c or "") for c, _ in text.sent) == before


async def test_screenshot_is_read_confirmed_and_credited_to_everyone_aboard(env):
    bot, cog, guild, text = env
    ship = await bot.db.create_ship(guild_id=10, owner_id=1, name="Sea Biscuit", kind="Galleon", motto="Yo ho",
                                    image=None, created_at=iso(T0))
    crew = await sailed_crew(bot, guild, ship)
    bot.get_cog("Parley").claude = FakeClaude([reading()])

    i = interaction(guild, 2)
    await cog.ship_log.callback(cog, i, screenshot=screenshot(_png(1920, 1080)))
    call = bot.get_cog("Parley").claude.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": "record_captains_log"}
    assert call["messages"][0]["content"][0]["type"] == "image"
    content, kw = i.followup.sent[-1]
    embed = kw["embed"]
    assert "48,210" in embed.description and "Sea Biscuit" in embed.title and kw["ephemeral"]
    entry_id = int(kw["view"].children[0].custom_id.split(":")[-1])
    entry = await bot.db.get_log(entry_id)
    assert entry.status == "pending" and entry.crew_id == crew.id and entry.ship_id == ship.id
    assert entry.pirates == [1, 2, 3]
    _, month, _ = bot.get_cog("Parley").today(await bot.db.get_settings(10))
    assert (await bot.db.parley_spend(10, month))[1] == 1  # the reading counts toward the budget

    stranger = interaction(guild, 3)
    await cog.on_button(stranger, "ok", entry_id)
    assert "Only the pirate" in stranger.response.sent[0]

    ok = interaction(guild, 2)
    await cog.on_button(ok, "ok", entry_id)
    assert (await bot.db.get_log(entry_id)).status == "confirmed" and ok.response.edits[0]["view"] is None
    content, kw = text.sent[-1]
    assert "48,210" in content and kw["reference"].message_id == 1000
    for uid in (1, 2, 3):
        t = await bot.db.ledger_totals(10, user_id=uid)
        assert (t.logs, t.gold, t.doubloons) == (1, 48210, 35)
    assert (await bot.db.ledger_totals(10, ship_id=ship.id)).gold == 48210
    card = text.messages[1000].edits[-1]["embed"]
    assert any(f.name == "Ship" and "Sea Biscuit" in f.value for f in card.fields)

    # A closed crew's card shows its haul.
    crew = await bot.db.update_crew(crew.id, status="closed")
    await bot.get_cog("CrewCall").refresh_card(guild, crew)
    card = text.messages[1000].edits[-1]["embed"]
    assert any(f.name == "Haul" and "48,210" in f.value for f in card.fields)

    await cog.on_button(ok, "ok", entry_id)
    assert "drifted off" in ok.response.sent[-1]


async def test_edit_fixes_a_misread_and_cancel_throws_it_away(env):
    bot, cog, guild, text = env
    crew = await sailed_crew(bot, guild)
    bot.get_cog("Parley").claude = FakeClaude([reading(gold=4821), reading(is_captains_log=False, gold=0, doubloons=0,
                                                                          emissary="", reputation=[], stats=[])])
    i = interaction(guild, 1)
    await cog.ship_log.callback(cog, i, screenshot=screenshot(_png(800, 450)))
    entry_id = int(i.followup.sent[-1][1]["view"].children[0].custom_id.split(":")[-1])

    e = interaction(guild, 1)
    await cog.on_button(e, "edit", entry_id)
    form = e.response.modal
    assert form.gold.default == "4,821"
    f = interaction(guild, 1)
    await cog.apply_form(f, entry_id, gold="nope", doubloons="", emissary="", reputation="", stats="")
    assert "couldn't read" in f.response.sent[0]
    f = interaction(guild, 1)
    await cog.apply_form(f, entry_id, gold="48,210", doubloons="", emissary="Gold Hoarders, grade 5",
                         reputation="Gold Hoarders: 2,400", stats="Islands visited: 7\nShips sunk: 1")
    entry = await bot.db.get_log(entry_id)
    assert (entry.gold, entry.doubloons) == (48210, 0)
    assert json.loads(entry.stats) == [["Islands visited", "7"], ["Ships sunk", "1"]]
    assert "48,210" in f.response.edits[0]["embed"].description

    # Not a Captain's Log: nothing to confirm until it's typed in.
    j = interaction(guild, 1)
    await cog.ship_log.callback(cog, j, screenshot=screenshot(_png(800, 450)))
    content, kw = j.followup.sent[-1]
    assert "doesn't look like" in content and kw["view"].children[0].item.disabled
    other_id = int(kw["view"].children[0].custom_id.split(":")[-1])
    c = interaction(guild, 1)
    await cog.on_button(c, "drop", other_id)
    assert await bot.db.get_log(other_id) is None


async def test_one_haul_per_crew_and_who_may_replace_it(env):
    bot, cog, guild, text = env
    crew = await sailed_crew(bot, guild)
    bot.get_cog("Parley").claude = FakeClaude([reading(), reading(gold=50000), reading(gold=1)])
    first = interaction(guild, 2)
    await cog.ship_log.callback(cog, first, screenshot=screenshot(_png(800, 450)))
    first_id = int(first.followup.sent[-1][1]["view"].children[0].custom_id.split(":")[-1])
    await cog.on_button(interaction(guild, 2), "ok", first_id)

    nobody = interaction(guild, 3)  # aboard, but neither captain, owner nor the logger
    await cog.ship_log.callback(cog, nobody, screenshot=screenshot(_png(800, 450)))
    assert "already in the ledger" in nobody.followup.sent[-1][0]

    captain = interaction(guild, 1)
    await cog.ship_log.callback(cog, captain, screenshot=screenshot(_png(800, 450)))
    second_id = int(captain.followup.sent[-1][1]["view"].children[0].custom_id.split(":")[-1])
    await cog.on_button(interaction(guild, 1), "ok", second_id)
    assert await bot.db.get_log(first_id) is None
    assert (await bot.db.confirmed_log_for_crew(crew.id)).gold == 50000
    assert (await bot.db.ledger_totals(10, user_id=2)).logs == 1


async def test_typed_in_without_a_screenshot_or_a_key(env):
    bot, cog, guild, text = env
    bot.get_cog("Parley").claude = None
    i = interaction(guild, 7)  # no crew lately: logged just for them
    await cog.ship_log.callback(cog, i)
    content, kw = i.followup.sent[-1]
    assert "Edit" in content and kw["view"].children[0].item.disabled
    entry_id = int(kw["view"].children[0].custom_id.split(":")[-1])
    await cog.apply_form(interaction(guild, 7), entry_id, gold="1.5k", doubloons="", emissary="", reputation="", stats="")
    ok = interaction(guild, 7)
    await cog.on_button(ok, "ok", entry_id)
    assert (await bot.db.get_log(entry_id)).pirates == [7]
    assert "1,500" in text.sent[-1][0]  # posted where /ship log was used


async def test_spent_budget_means_typing_it_in(env):
    bot, cog, guild, text = env
    await sailed_crew(bot, guild)
    parley = bot.get_cog("Parley")
    parley.claude = FakeClaude([])
    _, month, _ = parley.today(await bot.db.get_settings(10))
    await bot.db.add_parley_spend(10, month, 5.0, 0, 0)
    i = interaction(guild, 1)
    await cog.ship_log.callback(cog, i, screenshot=screenshot(_png(800, 450)))
    assert "budget" in i.followup.sent[-1][0] and parley.claude.calls == []


async def test_ships_profiles_and_the_fleet(env):
    bot, cog, guild, text = env
    i = interaction(guild, 1)
    await cog.ship_register.callback(cog, i, name="Sea  Biscuit", kind=SimpleNamespace(value="Sloop"))
    assert "Sea Biscuit" in i.followup.sent[-1][0]
    again = interaction(guild, 1)
    await cog.ship_register.callback(cog, again, name="sea biscuit", kind=SimpleNamespace(value="Sloop"))
    assert "already have" in again.response.sent[0]
    (ship,) = await bot.db.ships(10, 1)

    thief = interaction(guild, 2)
    await cog.ship_edit.callback(cog, thief, ship=str(ship.id), name="Mine Now")
    assert "not your ship" in thief.response.sent[0]
    await cog.ship_edit.callback(cog, interaction(guild, 1), ship=str(ship.id), kind=SimpleNamespace(value="Galleon"),
                                 motto="Crumbs ahoy")
    ship = await bot.db.get_ship(ship.id)
    assert ship.kind == "Galleon" and ship.motto == "Crumbs ahoy"

    # /crew start sails the captain's only ship, and a galleon musters a galleon's crew.
    crew_cog = bot.get_cog("CrewCall")
    start = interaction(guild, 1)
    start.channel = text
    await crew_cog.start.callback(crew_cog, start, game=SimpleNamespace(value="sot"))
    crew = await bot.db.active_crew_led_by(10, 1)
    assert crew.ship_id == ship.id and crew.size_label == "Galleon"

    entry = await bot.db.create_log(guild_id=10, crew_id=crew.id, ship_id=ship.id, logged_by=1, created_at=iso(T0),
                                    source="manual", gold=10000, doubloons=0, emissary=None, reputation="[]",
                                    stats="[]", pirates=[1, 4])
    await bot.db.update_log(entry.id, status="confirmed", confirmed_at=iso(T0))
    embed = await cog.ship_embed(guild, ship)
    assert any(f.name == "Plunder" and "10,000" in f.value for f in embed.fields)
    assert any(f.name == "Trusted crew" and "<@4>" in f.value for f in embed.fields)

    await cog.pirate_set.callback(cog, interaction(guild, 4), gamertag="Barnacle Bess", motto=None)
    who = SimpleNamespace(id=4, display_name="Bess", display_avatar=None)
    embed = await cog.pirate_embed(10, who)
    assert any(f.name == "Gamertag" and f.value == "Barnacle Bess" for f in embed.fields)
    assert any(f.name == "Sea of Thieves plunder" and "10,000" in f.value for f in embed.fields)

    fleet = await cog.fleet_embed(10)
    assert "Sea Biscuit" in fleet.fields[0].value and "<@1>" in fleet.fields[1].value
    assert "10,000" in await cog.summary(10)
    parley = bot.get_cog("Parley")
    assert "Sea Biscuit" in await parley.run_tool(guild, await bot.db.get_settings(10), "ship_ledger", {}, "2026-09-29")

    await cog.ship_retire.callback(cog, interaction(guild, 1), ship=str(ship.id))
    assert await bot.db.ships(10, 1) == []
    assert "Sea Biscuit" in (await cog.fleet_embed(10)).fields[0].value  # her ledger stays


async def test_weekly_roundup_counts_the_plunder(env):
    bot, cog, guild, text = env
    guild.members_list = []
    now = datetime.now(timezone.utc)
    for gold in (1000, 25000):
        e = await bot.db.create_log(guild_id=10, crew_id=None, ship_id=None, logged_by=1, created_at=iso(now),
                                    source="manual", gold=gold, doubloons=5, emissary=None, reputation="[]",
                                    stats="[]", pirates=[1])
        await bot.db.update_log(e.id, status="confirmed", confirmed_at=iso(now - timedelta(hours=1)))
    lines = L.week_lines(await bot.db.logs_between(10, iso(now - timedelta(days=7)), iso(now)), {})
    assert "2 voyages logged" in lines[0] and "26,000" in lines[0] and "25,000" in lines[1]


async def test_admin_remove_takes_the_post_down(env):
    bot, cog, guild, text = env
    e = await bot.db.create_log(guild_id=10, crew_id=None, ship_id=None, logged_by=1, created_at=iso(T0),
                                source="manual", gold=5, doubloons=0, emissary=None, reputation="[]", stats="[]",
                                pirates=[1])
    await bot.db.update_log(e.id, status="confirmed", confirmed_at=iso(T0), channel_id=20, message_id=1234)
    deleted = []

    class Posted:
        async def delete(self):
            deleted.append(True)

    text.get_partial_message = lambda mid: Posted()
    admin = bot.get_cog("Admin")
    i = interaction(guild, 1, mod=True)
    await admin.ledger_remove.callback(admin, i, entry=e.id)
    assert await bot.db.get_log(e.id) is None and deleted and "gone" in i.response.sent[0]


# ------------------------------------------------------------ a screenshot posted to PlunderBot in chat
BOT_ID = 999


class Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def chat_message(guild, author_id, content, pics=1, reply_to=None):
    async def read():
        return _png(800, 450)
    attachments = [SimpleNamespace(content_type="image/png", filename="log.png", size=10, read=read)
                   for _ in range(pics)]
    ref = SimpleNamespace(resolved=reply_to) if reply_to is not None else None
    msg = SimpleNamespace(guild=guild, author=SimpleNamespace(id=author_id, bot=False, display_name="Boxer"),
                          content=content, attachments=attachments, reference=ref,
                          raw_mentions=[BOT_ID] if f"<@{BOT_ID}>" in content else [],
                          channel=SimpleNamespace(id=guild.text.id, typing=lambda: Typing()), replies=[])

    async def reply(text, **kw):
        msg.replies.append((text, kw))
        return SimpleNamespace(id=4242)
    msg.reply = reply
    return msg


def bot_said(text, embeds=()):
    import discord
    m = object.__new__(discord.Message)
    m.author = SimpleNamespace(id=BOT_ID)
    m.content, m.embeds = text, list(embeds)
    return m


@pytest.fixture
def as_bot(env, monkeypatch):
    bot = env[0]
    monkeypatch.setattr(type(bot), "user", property(lambda self: SimpleNamespace(id=BOT_ID)))
    return env


async def test_which_chat_screenshots_are_captains_logs(as_bot):
    bot, cog, guild, text = as_bot
    nudge = bot_said("📸 Ledger duty! Screenshot the Captain's Log ... `/ship log`.")
    assert cog.wants(chat_message(guild, 1, "Here are my stats!", reply_to=nudge))
    assert cog.wants(chat_message(guild, 1, f"<@{BOT_ID}>"))
    assert cog.wants(chat_message(guild, 1, f"<@{BOT_ID}> Add these captains log stats to my last voyage"))
    assert cog.wants(chat_message(guild, 1, "", reply_to=bot_said("Ahoy! You rang?")))
    assert not cog.wants(chat_message(guild, 1, f"<@{BOT_ID}> what island is this?"))
    assert not cog.wants(chat_message(guild, 1, f"<@{BOT_ID}> my stats", pics=0))
    assert not cog.wants(chat_message(guild, 1, "my stats"))  # not addressed to PlunderBot


async def test_a_reply_with_a_screenshot_is_read_and_confirmed_in_place(as_bot):
    bot, cog, guild, text = as_bot
    crew = await sailed_crew(bot, guild)
    parley = bot.get_cog("Parley")
    parley.claude = FakeClaude([reading(gold=392040, doubloons=0)])
    await bot.db.update_settings(10, parley_enabled=1)
    msg = chat_message(guild, 1, "Here are my stats!", reply_to=bot_said("Ledger duty ... Captain's Log"))
    await parley.on_message(msg)   # Parley stays out of it...
    await cog.on_message(msg)      # ...and the ledger reads it
    assert len(parley.claude.calls) == 1 and len(msg.replies) == 1
    reply, kw = msg.replies[0]
    assert "392,040" in kw["embed"].description
    entry_id = int(kw["view"].children[0].custom_id.split(":")[-1])

    stranger = interaction(guild, 3)
    await cog.on_button(stranger, "ok", entry_id)
    assert "Only the pirate" in stranger.response.sent[0]

    ok = interaction(guild, 1)
    ok.message = SimpleNamespace(id=4242, flags=SimpleNamespace(ephemeral=False))
    before = len(text.sent)
    await cog.on_button(ok, "ok", entry_id)
    entry = await bot.db.get_log(entry_id)
    assert entry.status == "confirmed" and entry.message_id == 4242
    assert "392,040" in ok.response.edits[0]["content"] and len(text.sent) == before  # no second post
    assert (await bot.db.ledger_totals(10, user_id=2)).gold == 392040
