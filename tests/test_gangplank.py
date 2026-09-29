"""Gangplank: the airlock. Yar lets people aboard, Nar turns them away, silence gets a nudge then the door."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import discord
import pytest

from plunderbot.crew_logic import iso
from plunderbot.gangplank_logic import due, emoji_key, verdict

T0 = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
YAR, NAR, OTHER = 111, 222, 333


# ------------------------------------------------------------ rules
def test_emoji_key():
    assert emoji_key("<:Yar:111>") == "111"
    assert emoji_key("<a:Yar:111>") == "111"
    assert emoji_key("111") == "111"
    assert emoji_key("✅") == "✅"
    assert emoji_key(":yar:") is None
    assert emoji_key("  ") is None


def test_verdict_defaults_to_emoji_named_yar_and_nar():
    assert verdict(YAR, "Yar", None, None) == "approve"
    assert verdict(NAR, "NAR", None, None) == "reject"
    assert verdict(OTHER, "heart", None, None) is None
    assert verdict(None, "yar", None, None) is None  # a standard emoji can't be named Yar


def test_verdict_with_configured_emoji():
    assert verdict(OTHER, "Aye", str(OTHER), None) == "approve"
    assert verdict(YAR, "Yar", str(OTHER), None) is None  # configured replaces the default
    assert verdict(None, "✅", "✅", "❌") == "approve"
    assert verdict(None, "❌", "✅", "❌") == "reject"


def test_due():
    j = iso(T0)
    assert due(j, None, None, T0 + timedelta(days=2), 3, 7) is None
    assert due(j, None, None, T0 + timedelta(days=3), 3, 7) == "remind"
    assert due(j, None, iso(T0 + timedelta(days=3)), T0 + timedelta(days=5), 3, 7) is None
    assert due(j, None, iso(T0 + timedelta(days=3)), T0 + timedelta(days=7), 3, 7) == "kick"
    assert due(j, None, None, T0 + timedelta(days=8), 3, 7) == "kick"  # overslept the reminder: kick wins
    assert due(j, iso(T0), None, T0 + timedelta(days=30), 3, 7) is None  # introduced: Harbormasters decide


# ------------------------------------------------------------ fakes
class Role(SimpleNamespace):
    def __ge__(self, other):
        return self.position >= other.position


class Member:
    def __init__(self, guild, uid, *roles, bot=False):
        self.guild, self.id, self.bot, self.roles = guild, uid, bot, list(roles)
        self.mention, self.kicked, self.dms = f"<@{uid}>", None, []
        guild.members_by_id[uid] = self
        for r in roles:
            r.members.append(self)

    def __str__(self):
        return f"user{self.id}"

    def get_role(self, rid):
        return next((r for r in self.roles if r.id == rid), None)

    async def add_roles(self, role, reason=None):
        if role not in self.roles:
            self.roles.append(role)
            role.members.append(self)

    async def remove_roles(self, role, reason=None):
        self.roles.remove(role)
        role.members.remove(self)

    async def kick(self, reason=None):
        self.kicked = reason
        self.guild.members_by_id.pop(self.id, None)

    async def send(self, text):
        self.dms.append(text)


class Channel:
    def __init__(self, cid, history=()):
        self.id, self.sent, self._history = cid, [], list(history)

    async def send(self, text, **kw):
        self.sent.append(text)
        return SimpleNamespace(id=9000 + len(self.sent))

    async def history(self, limit=None):
        for m in self._history:
            yield m


class Guild:
    def __init__(self):
        self.id, self.name, self.members_by_id = 5, "Brimstone Hill Fortress", {}
        self.pending = Role(id=50, members=[], position=1)
        self.harbor = Role(id=60, members=[], position=2)
        self.intro, self.alerts = Channel(70), Channel(80)

    def get_role(self, rid):
        return {50: self.pending, 60: self.harbor}.get(rid)

    def get_member(self, uid):
        return self.members_by_id.get(uid)

    def get_channel(self, cid):
        return {70: self.intro, 80: self.alerts}.get(cid)


def reaction(guild, by, message_id, author_id, emoji_id, name):
    return SimpleNamespace(guild_id=guild.id, channel_id=70, member=by, user_id=by.id, message_id=message_id,
                           message_author_id=author_id, emoji=SimpleNamespace(id=emoji_id, name=name))


def intro_message(guild, member, channel_id=70):
    return SimpleNamespace(guild=guild, author=member, channel=SimpleNamespace(id=channel_id),
                           jump_url="https://discord.com/x")


@pytest.fixture
async def env(tmp_path, monkeypatch):
    from tests.test_bot import make_config
    from plunderbot.bot import PlunderBot
    bot = PlunderBot(make_config(tmp_path))
    await bot.db.connect()
    await bot.load_extension("plunderbot.cogs.gangplank")
    cog = bot.get_cog("Gangplank")
    cog.upkeep.cancel()
    guild = Guild()
    monkeypatch.setattr(bot, "get_guild", lambda gid: guild if gid == guild.id else None)
    monkeypatch.setattr(discord, "Member", Member)  # isinstance checks in on_message
    await bot.db.update_settings(guild.id, gangplank_enabled=1, intro_channel_id=70, pending_role_id=50,
                                 harbormaster_role_id=60, rules_channel_id=71, orientation_channel_id=72,
                                 gangplank_alert_channel_id=80)
    yield bot, cog, guild
    await bot.db.close()


# ------------------------------------------------------------ the flow
async def test_join_welcome_intro_and_yar(env):
    bot, cog, guild = env
    newbie = Member(guild, 1)
    harbormaster = Member(guild, 2, guild.harbor)
    await cog.on_member_join(newbie)
    assert guild.pending in newbie.roles
    assert "<@1>" in guild.intro.sent[0] and "<#71>" in guild.intro.sent[0]
    await cog.on_message(intro_message(guild, newbie))
    assert (await bot.db.get_boarding(5, 1)).responded_at is not None
    assert "introduced themselves" in guild.alerts.sent[-1]
    await cog.on_raw_reaction_add(reaction(guild, harbormaster, 555, newbie.id, YAR, "Yar"))
    assert guild.pending not in newbie.roles
    assert await bot.db.get_boarding(5, 1) is None
    assert "<#72>" in guild.intro.sent[-1] and "<@1>" in guild.intro.sent[-1]


async def test_yar_on_the_welcome_message_works_too(env):
    bot, cog, guild = env
    newbie = Member(guild, 1)
    harbormaster = Member(guild, 2, guild.harbor)
    await cog.on_member_join(newbie)
    prompt = (await bot.db.get_boarding(5, 1)).prompt_message_id
    await cog.on_raw_reaction_add(reaction(guild, harbormaster, prompt, bot_id := 999, YAR, "Yar"))
    assert guild.pending not in newbie.roles


async def test_nar_kicks(env):
    bot, cog, guild = env
    newbie = Member(guild, 1)
    harbormaster = Member(guild, 2, guild.harbor)
    await cog.on_member_join(newbie)
    await cog.on_raw_reaction_add(reaction(guild, harbormaster, 555, 1, NAR, "Nar"))
    assert "turned away" in newbie.kicked
    assert await bot.db.get_boarding(5, 1) is None


async def test_only_harbormasters_and_only_pending_members(env):
    bot, cog, guild = env
    newbie = Member(guild, 1)
    bystander = Member(guild, 3)
    await cog.on_member_join(newbie)
    await cog.on_raw_reaction_add(reaction(guild, bystander, 555, 1, NAR, "Nar"))
    assert newbie.kicked is None
    harbormaster = Member(guild, 2, guild.harbor)
    await cog.on_raw_reaction_add(reaction(guild, harbormaster, 555, 1, OTHER, "heart"))
    assert newbie.kicked is None and guild.pending in newbie.roles
    veteran = Member(guild, 4)  # already aboard: a stray Nar on an old intro does nothing
    await cog.on_raw_reaction_add(reaction(guild, harbormaster, 556, 4, NAR, "Nar"))
    assert veteran.kicked is None
    other_channel = reaction(guild, harbormaster, 555, 1, NAR, "Nar")
    other_channel.channel_id = 99
    await cog.on_raw_reaction_add(other_channel)
    assert newbie.kicked is None


async def test_off_does_nothing(env):
    bot, cog, guild = env
    await bot.db.update_settings(5, gangplank_enabled=0)
    newbie = Member(guild, 1)
    await cog.on_member_join(newbie)
    assert guild.pending not in newbie.roles and not guild.intro.sent


async def test_silence_gets_a_reminder_then_the_door(env):
    bot, cog, guild = env
    newbie = Member(guild, 1, guild.pending)
    await bot.db.add_boarding(5, 1, iso(T0))
    assert await cog.tick(guild, await bot.db.get_settings(5), T0 + timedelta(days=1)) == 1
    assert not guild.intro.sent
    await cog.tick(guild, await bot.db.get_settings(5), T0 + timedelta(days=3, minutes=1))
    assert "<@1>" in guild.intro.sent[-1] and "<t:" in guild.intro.sent[-1]
    reminders = len(guild.intro.sent)
    await cog.tick(guild, await bot.db.get_settings(5), T0 + timedelta(days=4))
    assert len(guild.intro.sent) == reminders  # only once
    assert await cog.tick(guild, await bot.db.get_settings(5), T0 + timedelta(days=7, minutes=1)) == 0
    assert "no introduction" in newbie.kicked
    assert newbie.dms and await bot.db.get_boarding(5, 1) is None


async def test_introduced_members_are_never_auto_kicked(env):
    bot, cog, guild = env
    newbie = Member(guild, 1, guild.pending)
    await bot.db.add_boarding(5, 1, iso(T0), None, iso(T0))
    await cog.tick(guild, await bot.db.get_settings(5), T0 + timedelta(days=30))
    assert newbie.kicked is None and not guild.intro.sent


async def test_catch_up_on_existing_pending_members(env):
    bot, cog, guild = env
    talker = Member(guild, 1, guild.pending)
    lurker = Member(guild, 2, guild.pending)
    Member(guild, 3, guild.pending, bot=True)
    guild.intro._history = [SimpleNamespace(author=SimpleNamespace(id=1))]
    s = await bot.db.get_settings(5)
    assert await cog.catch_up(guild, s, T0) == 2
    assert (await bot.db.get_boarding(5, 1)).responded_at is not None
    assert (await bot.db.get_boarding(5, 2)).responded_at is None
    assert await bot.db.get_boarding(5, 3) is None
    assert await cog.catch_up(guild, s, T0) == 0  # already tracked
    await cog.tick(guild, s, T0 + timedelta(days=8))  # the clock started at catch-up, not their join
    assert lurker.kicked and talker.kicked is None


async def test_let_aboard_by_hand_or_left(env):
    bot, cog, guild = env
    newbie = Member(guild, 1, guild.pending)
    await bot.db.add_boarding(5, 1, iso(T0))
    await newbie.remove_roles(guild.pending)  # a Harbormaster took Pending off by hand
    await cog.tick(guild, await bot.db.get_settings(5), T0 + timedelta(days=8))
    assert newbie.kicked is None and await bot.db.get_boarding(5, 1) is None
    await bot.db.add_boarding(5, 7, iso(T0))
    await cog.on_member_remove(SimpleNamespace(id=7, guild=guild))
    assert await bot.db.get_boarding(5, 7) is None


async def test_welcome_aboard_offers_role_menus(env, monkeypatch):
    bot, cog, guild = env
    from plunderbot.cogs.colours import MenuButton

    class FakeColours:
        async def onboarding_items(self, g):
            return [MenuButton(3, "Choose Region Roles")]

    real = bot.get_cog
    monkeypatch.setattr(bot, "get_cog", lambda name: FakeColours() if name == "Colours" else real(name))
    sent = []

    async def send(text, **kw):
        sent.append((text, kw))
        return SimpleNamespace(id=1)

    guild.intro.send = send
    newbie = Member(guild, 1, guild.pending)
    harbormaster = Member(guild, 2, guild.harbor)
    await bot.db.add_boarding(5, 1, iso(T0))
    await cog.on_raw_reaction_add(reaction(guild, harbormaster, 555, 1, YAR, "Yar"))
    text, kw = sent[-1]
    assert "buttons below" in text and kw["view"].children[0].custom_id == "colours:open:3"
