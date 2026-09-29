"""Crew Call: profiles, rules, the database, and the button flow with fake Discord objects."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from plunderbot import games
from plunderbot.crew_logic import expired, iso, render_card, voice_channel_name, voice_cleanup_due
from plunderbot.db import Database

T0 = datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------ profiles
def test_profiles_are_consistent():
    assert len(games.GAMES) == 17
    assert len({g.key for g in games.GAMES}) == 17
    assert sum(g.crew_call for g in games.GAMES) == 16  # "Server event" is only for Voyages
    for g in games.GAMES:
        assert g.sizes and g.tags
        assert g.open_ended or all(2 <= s.capacity <= 25 for s in g.sizes)
        assert len(g.sizes) <= 25 and len(g.tags) <= 25  # Discord autocomplete limit
        assert len(g.name) <= 100
    sot = games.get("sot")
    assert [s.capacity for s in sot.sizes] == [2, 3, 4]
    assert sot.size("galleon").capacity == 4 and sot.size(None).label == "Galleon"
    assert sot.size("rowboat") is None
    assert sot.tag("tall tales") == "Tall Tales" and sot.tag("Heists") is None


def test_voice_channel_names_fit():
    name = voice_channel_name(games.get("artemis"), "6 players", "A" * 200)
    assert len(name) <= 100
    assert voice_channel_name(games.get("sot"), "Sloop", "Boxer") == "⛵ | Boxer's Sloop"
    assert voice_channel_name(games.get("sot"), "Galleon", "Boxer") == "🚢 | Boxer's Galleon"
    assert voice_channel_name(games.get("fortnite"), "Squad", "Boxer") == "🪂 | Boxer's Fortnite Squad"
    assert voice_channel_name(games.get("helldivers"), "4 players", "Boxer") == "🪖 | Boxer's Helldivers"
    assert voice_channel_name(games.get("hangout"), "Hangout", "Boxer") == "🛋️ | Boxer's 1 Player Hangout"
    assert voice_channel_name(games.get("sot"), "Sloop", "Boxer", "🏴‍☠️") == "🏴‍☠️ | Boxer's Sloop"


# ------------------------------------------------------------ database
@pytest.fixture
async def db(tmp_path):
    d = Database(tmp_path / "crew.db")
    await d.connect()
    yield d
    await d.close()


async def make_crew(db, capacity=2, captain=1, expires=T0 + timedelta(hours=1)):
    return await db.create_crew(guild_id=10, channel_id=20, captain_id=captain, game_key="sot",
                                size_label="Sloop", capacity=capacity, activity="Fort", note=None,
                                created_at=iso(T0), expires_at=iso(expires))


async def test_seats_fill_and_free(db):
    crew = await make_crew(db, capacity=2)
    assert crew.members == [1] and not crew.full
    assert await db.add_crew_member(crew.id, 2, iso(T0))
    assert not await db.add_crew_member(crew.id, 3, iso(T0))  # full
    assert not await db.add_crew_member(crew.id, 2, iso(T0))  # already aboard
    assert (await db.get_crew(crew.id)).full
    assert await db.remove_crew_member(crew.id, 2)
    assert await db.add_crew_member(crew.id, 3, iso(T0))
    assert (await db.get_crew(crew.id)).members == [1, 3]


async def test_closed_crews_take_no_one(db):
    crew = await make_crew(db, capacity=4)
    await db.update_crew(crew.id, status="closed")
    assert not await db.add_crew_member(crew.id, 2, iso(T0))
    assert await db.active_crews() == []
    assert await db.active_crew_led_by(10, 1) is None


async def test_ping_roles(db):
    await db.set_game_ping_role(10, "sot", 555)
    await db.set_game_ping_role(10, "lol", 666)
    await db.set_game_ping_role(10, "lol", None)
    assert await db.game_ping_roles(10) == {"sot": 555}


# ------------------------------------------------------------ rules
async def test_expiry_and_voice_cleanup(db):
    crew = await make_crew(db)
    assert not expired(crew, T0 + timedelta(minutes=59))
    assert expired(crew, T0 + timedelta(hours=1))
    sailing = await db.update_crew(crew.id, status="sailing", voice_channel_id=99,
                                   voice_empty_since=iso(T0))
    assert not expired(sailing, T0 + timedelta(days=1))  # a sailing crew with voice never "expires"
    # Nobody has joined yet: 15 minutes of grace even with a 5-minute cleanup.
    assert not voice_cleanup_due(sailing, 0, T0 + timedelta(minutes=14), 5)
    assert voice_cleanup_due(sailing, 0, T0 + timedelta(minutes=15), 5)
    occupied = await db.update_crew(crew.id, voice_occupied=1, voice_empty_since=iso(T0))
    assert not voice_cleanup_due(occupied, 0, T0 + timedelta(minutes=4), 5)
    assert voice_cleanup_due(occupied, 0, T0 + timedelta(minutes=5), 5)
    assert not voice_cleanup_due(occupied, 2, T0 + timedelta(hours=5), 5)


async def test_card_renders(db):
    crew = await make_crew(db, capacity=4)
    embed = render_card(crew, games.get("sot"))
    seats = next(f.value for f in embed.fields if f.name == "Seats")
    assert "<@1> (captain)" in seats and seats.count("open seat") == 3
    assert len(embed) <= 6000


# ------------------------------------------------------------ the flow, with fakes
class FakeResponse:
    def __init__(self):
        self.messages, self.deferred = [], False

    async def send_message(self, content=None, **kw):
        self.messages.append(content)

    async def defer(self, **kw):
        self.deferred = True

    def is_done(self):
        return bool(self.messages) or self.deferred


class FakeMessage:
    def __init__(self, mid):
        self.id, self.edits = mid, []

    async def edit(self, **kw):
        self.edits.append(kw)


class FakeTextChannel:
    def __init__(self, cid):
        self.id, self.sent, self.category, self.messages = cid, [], None, {}

    async def send(self, content=None, **kw):
        msg = FakeMessage(1000 + len(self.sent))
        self.messages[msg.id] = msg
        self.sent.append((content, kw))
        return msg

    def get_partial_message(self, mid):
        return self.messages.setdefault(mid, FakeMessage(mid))


class FakeVoice:
    def __init__(self, vid, name):
        self.id, self.name, self.members, self.deleted = vid, name, [], False
        self.mention = f"<#{vid}>"

    async def delete(self, reason=None):
        self.deleted = True


class FakeGuild:
    def __init__(self, gid, text):
        self.id, self.text, self.voices, self.members = gid, text, {}, {}

    def get_channel(self, cid):
        if cid == self.text.id:
            return self.text
        v = self.voices.get(cid)
        return None if v is None or v.deleted else v

    def get_member(self, uid):
        return self.members.get(uid)

    def get_role(self, rid):
        return None

    async def create_voice_channel(self, name, category=None, user_limit=None, reason=None):
        vc = FakeVoice(5000 + len(self.voices), name)
        vc.user_limit = user_limit
        self.voices[vc.id] = vc
        return vc


def interaction_for(guild, uid, perms=None):
    user = SimpleNamespace(id=uid, mention=f"<@{uid}>", display_name=f"U{uid}",
                           guild_permissions=perms or SimpleNamespace(manage_channels=False, manage_guild=False,
                                                                      administrator=False))
    return SimpleNamespace(user=user, guild=guild, guild_id=guild.id, response=FakeResponse())


@pytest.fixture
async def crew_env(tmp_path):
    from tests.test_bot import make_config
    from plunderbot.bot import COGS, PlunderBot
    bot = PlunderBot(make_config(tmp_path))
    await bot.db.connect()
    for cog in COGS:
        await bot.load_extension(cog)
    bot.get_cog("Birthdays").announcer.cancel()
    cog = bot.get_cog("CrewCall")
    cog.upkeep.cancel()
    bot.get_cog("Voyages").clock.cancel()
    bot.get_cog("Gangplank").upkeep.cancel()
    text = FakeTextChannel(20)
    guild = FakeGuild(10, text)
    guild.members[1] = SimpleNamespace(id=1, display_name="Boxer")
    yield bot, cog, guild, text
    await bot.db.close()


async def test_full_crew_sails_and_cleans_up(crew_env):
    bot, cog, guild, text = crew_env
    crew = await make_crew(bot.db, capacity=2)
    await bot.db.update_crew(crew.id, message_id=1000)

    stranger = interaction_for(guild, 3)
    await cog.on_button(stranger, "sail", crew.id)
    assert "captain" in stranger.response.messages[0].lower()

    joiner = interaction_for(guild, 2)
    await cog.on_button(joiner, "join", crew.id)  # fills the sloop, so it sails itself
    crew = await bot.db.get_crew(crew.id)
    assert crew.status == "sailing" and crew.voice_channel_id
    vc = guild.voices[crew.voice_channel_id]
    assert vc.name == "⛵ | Boxer's Sloop" and vc.user_limit is None
    assert any("<@2>" in (c or "") for c, _ in text.sent)  # the crew is pinged with the channel

    late = interaction_for(guild, 4)
    await cog.on_button(late, "join", crew.id)
    assert "full" in late.response.messages[0].lower()

    # Somebody hops in, then everyone leaves; the channel goes after the cleanup wait.
    vc.members = ["someone"]
    await cog._upkeep_one(guild, crew, T0)
    crew = await bot.db.get_crew(crew.id)
    assert crew.voice_occupied == 1
    vc.members = []
    await cog._upkeep_one(guild, crew, T0 + timedelta(minutes=1))
    crew = await bot.db.get_crew(crew.id)
    await cog._upkeep_one(guild, crew, T0 + timedelta(minutes=3))
    assert not vc.deleted
    await cog._upkeep_one(guild, crew, T0 + timedelta(minutes=6, seconds=1))
    assert vc.deleted and (await bot.db.get_crew(crew.id)).status == "closed"


async def test_leave_close_and_expiry(crew_env):
    bot, cog, guild, text = crew_env
    crew = await make_crew(bot.db, capacity=4)
    await bot.db.update_crew(crew.id, message_id=1000)
    joiner = interaction_for(guild, 2)
    await cog.on_button(joiner, "join", crew.id)
    captain = interaction_for(guild, 1)
    await cog.on_button(captain, "leave", crew.id)
    assert "captain" in captain.response.messages[0].lower()
    await cog.on_button(joiner, "leave", crew.id)
    assert (await bot.db.get_crew(crew.id)).members == [1]

    # A member can't close it; a mod can.
    await cog.on_button(joiner, "close", crew.id)
    assert (await bot.db.get_crew(crew.id)).status == "open"
    mod = interaction_for(guild, 9, SimpleNamespace(manage_channels=True, manage_guild=False, administrator=False))
    await cog.on_button(mod, "close", crew.id)
    assert (await bot.db.get_crew(crew.id)).status == "closed"

    other = await make_crew(bot.db, capacity=4, captain=7)
    await cog._upkeep_one(guild, other, T0 + timedelta(hours=2))
    assert (await bot.db.get_crew(other.id)).status == "expired"
    edits = text.get_partial_message(1000).edits
    assert edits and edits[-1]["view"].children[0].item.disabled  # buttons switched off


async def test_closing_while_the_channel_is_made_leaves_nothing_behind(crew_env):
    bot, cog, guild, text = crew_env
    crew = await make_crew(bot.db, capacity=4)
    await bot.db.update_crew(crew.id, message_id=1000)
    real_create = guild.create_voice_channel

    async def create_then_close(*a, **kw):
        vc = await real_create(*a, **kw)
        await bot.db.update_crew(crew.id, status="closed")  # the captain pressed Close meanwhile
        return vc

    guild.create_voice_channel = create_then_close
    await cog.on_button(interaction_for(guild, 1), "sail", crew.id)
    (vc,) = guild.voices.values()
    assert vc.deleted
    assert not any("voice channel" in (c or "") for c, _ in text.sent)  # nobody pinged


async def test_ping_role_cooldown_and_threads(crew_env):
    import discord
    bot, cog, guild, text = crew_env
    from datetime import timedelta as td
    from plunderbot.crew_logic import PING_COOLDOWN
    assert PING_COOLDOWN == td(minutes=15)
    thread_inter = interaction_for(guild, 1)
    thread_inter.channel = discord.Thread.__new__(discord.Thread)
    game = SimpleNamespace(value="sot", name="Sea of Thieves")
    await cog.start.callback(cog, thread_inter, game)
    assert "thread" in thread_inter.response.messages[0].lower()


def test_role_names_match_games():
    from plunderbot.games import GAMES
    names = ["Sea of Thieves", "Fortnite", "Deep Rock Galactic", "Plate Up!", "Void Crew", "1 Player Hangout",
             "Jump Space", "Helldivers", "ARTEMIS", "Moderators", "Ale and Tale Tavern"]
    found = {g.key: next((n for n in names if g.matches_role_name(n)), None) for g in GAMES}
    assert found["sot"] == "Sea of Thieves" and found["plateup"] == "Plate Up!"
    assert found["drg"] == "Deep Rock Galactic" and found["jumpspace"] == "Jump Space"
    assert found["helldivers"] == "Helldivers" and found["artemis"] == "ARTEMIS"
    assert found["lol"] is None and found["aletale"] == "Ale and Tale Tavern"
    assert found["hangout"] == "1 Player Hangout"
    assert not any(g.matches_role_name("Moderators") for g in GAMES)



async def test_hangout_opens_voice_at_once_and_never_fills(crew_env):
    bot, cog, guild, text = crew_env
    host = interaction_for(guild, 1)
    host.channel = text
    host.followup = SimpleNamespace(send=None)
    text.permissions_for = lambda me: SimpleNamespace(view_channel=True, send_messages=True, embed_links=True)
    guild.me = SimpleNamespace()
    game = SimpleNamespace(value="hangout", name="1 Player Hangout")
    await cog.start.callback(cog, host, game)
    crew = await bot.db.active_crew_led_by(10, 1)
    assert crew.status == "sailing" and crew.voice_channel_id and crew.capacity >= 99
    vc = guild.voices[crew.voice_channel_id]
    assert vc.user_limit is None
    for uid in range(2, 30):
        await cog.on_button(interaction_for(guild, uid), "join", crew.id)
    crew = await bot.db.get_crew(crew.id)
    assert len(crew.members) == 29 and crew.status == "sailing"
    embed = render_card(crew, games.get("hangout"))
    assert len(embed) <= 6000 and all(len(f.value) <= 1024 for f in embed.fields)
    from plunderbot.cogs.crew import card_view
    assert [c.action for c in card_view(crew).children] == ["join", "leave", "close"]



def test_emoji_rules():
    from plunderbot import crew_emoji as ce
    assert ce.is_custom("<:galleon:123456789012345678>") and ce.is_custom("<a:wave:123456789012345678>")
    assert not ce.is_custom(":galleon:")
    for good in ("⛵", "🚢", "🏴‍☠️", "🛥️", "🇺🇸", "👍🏽"):
        assert ce.is_standard(good), good
    for bad in ("sloop", "a⛵", "", "<:x:1>", "⛵" * 13):
        assert not ce.is_standard(bad), bad
    sot = games.get("sot")
    assert ce.resolve(sot, "Galleon", {}) == ("🚢", "🚢")
    picks = {("sot", ""): ("🏴‍☠️", None), ("sot", "Galleon"): (None, "<:galleon:123456789012345678>")}
    # Galleon: size-specific server emoji on the card; channel falls back to the game-wide standard pick.
    assert ce.resolve(sot, "Galleon", picks) == ("🏴‍☠️", "<:galleon:123456789012345678>")
    assert ce.resolve(sot, "Sloop", picks) == ("🏴‍☠️", "🏴‍☠️")


async def test_emoji_storage(db):
    await db.set_crew_emoji(10, "sot", "Galleon", standard="🚢")
    await db.set_crew_emoji(10, "sot", "Galleon", server="<:galleon:123456789012345678>")
    assert await db.crew_emoji(10) == {("sot", "Galleon"): ("🚢", "<:galleon:123456789012345678>")}
    await db.set_crew_emoji(10, "sot", "Galleon", standard=None, server=None)
    assert await db.crew_emoji(10) == {}


async def test_named_sessions(db):
    from plunderbot.crew_logic import clean_title
    assert clean_title("  Fort   Night\n with `the` crew ") == "Fort Night with 'the' crew"
    assert clean_title("   ") is None and len(clean_title("x" * 200)) == 60
    sot = games.get("sot")
    assert voice_channel_name(sot, "Galleon", "Boxer", None, "Fort Night") == "🚢 | Fort Night"
    crew = await db.create_crew(guild_id=10, channel_id=20, captain_id=1, game_key="sot", size_label="Galleon",
                                capacity=4, activity=None, note=None, created_at=iso(T0),
                                expires_at=iso(T0 + timedelta(hours=1)), title="Fort Night")
    embed = render_card(crew, sot)
    assert embed.title == "🚢 Fort Night" and "Sea of Thieves: Galleon" in embed.description
    crew = await db.update_crew(crew.id, title=None)
    assert render_card(crew, sot).title == "🚢 Sea of Thieves: Galleon"
