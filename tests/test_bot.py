"""Wiring tests: the bot builds its command tree, and the birthday run behaves, without Discord."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from discord import app_commands

from plunderbot.bot import COGS, PlunderBot
from plunderbot.config import Config


def make_config(tmp_path: Path) -> Config:
    return Config(discord_token="x", data_dir=tmp_path, dev_guild_id=None,
                  default_timezone="America/Los_Angeles", ready_file=tmp_path / "ready", log_level="INFO")


@pytest.fixture
async def bot(tmp_path):
    b = PlunderBot(make_config(tmp_path))
    await b.db.connect()
    for cog in COGS:
        await b.load_extension(cog)
    b.get_cog("Birthdays").announcer.cancel()  # the real loops need a live Discord connection
    b.get_cog("CrewCall").upkeep.cancel()
    b.get_cog("Voyages").clock.cancel()
    b.get_cog("Gangplank").upkeep.cancel()
    b.get_cog("ShipsLog").clock.cancel()
    b.get_cog("CrowsNest").watch.cancel()
    b.get_cog("Articles").clock.cancel()
    yield b
    await b.db.close()


async def test_command_tree(bot):
    top = {c.name: c for c in bot.tree.get_commands()}
    assert set(top) == {"plunderbot", "admin", "birthday", "crew", "voyage", "timezone", "colours", "noticeboard", "follow", "ship", "pirate", "articles", "play", "music"}
    arts = top["articles"]
    assert arts.guild_only and arts.default_permissions.manage_guild
    assert {c.name for c in arts.commands} == {"new", "edit", "reply", "react", "role", "count", "repost", "pin", "remove", "limits", "where", "on", "off", "delete", "list", "show"}
    assert {c.name for c in top["ship"].commands} == {"register", "edit", "retire", "show", "fleet", "log"}
    assert {c.name for c in top["pirate"].commands} == {"profile", "set"}
    assert top["ship"].guild_only and top["pirate"].guild_only
    assert {c.name for c in top["voyage"].commands} == {"create", "edit", "cancel", "list"}
    admin = top["admin"]
    assert isinstance(admin, app_commands.Group)
    assert admin.guild_only and admin.default_permissions.manage_guild
    assert {c.name for c in admin.commands} == {"settings", "timezone", "birthdays", "crew", "voyages", "regions", "gangplank", "shipslog", "crowsnest", "parley", "ledger", "music"}
    assert {c.name for c in admin.get_command("crew").commands} == {"channel", "category", "cleanup", "expire", "pingrole", "autopings", "emoji"}
    assert {c.name for c in top["crew"].commands} == {"start", "close", "list", "rename"}
    assert {c.name for c in top["music"].commands} == {"queue", "nowplaying", "skip", "pause", "resume", "stop", "clear",
                                                     "remove", "move", "shuffle", "repeat", "seek", "volume", "lyrics",
                                                     "leave"}
    assert top["music"].guild_only and top["play"].guild_only
    bday_admin = admin.get_command("birthdays")
    assert {c.name for c in bday_admin.commands} == {"channel", "hour", "role", "off"}
    birthday = top["birthday"]
    assert birthday.guild_only
    assert {c.name for c in birthday.commands} == {"set", "remove", "mine", "upcoming"}
    # Every command and option has a description Discord will accept.
    for cmd in bot.tree.walk_commands():
        assert 1 <= len(cmd.description) <= 100, cmd.qualified_name


# ------------------------------------------------------------ the daily toast, with fakes
class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, content, **kwargs):
        self.sent.append(content)


class FakeMember:
    def __init__(self, uid, name):
        self.id, self.display_name, self.mention, self.roles = uid, name, f"<@{uid}>", []

    async def add_roles(self, role, reason=None):
        self.roles.append(role)

    async def remove_roles(self, role, reason=None):
        self.roles.remove(role)


class FakeGuild:
    def __init__(self, gid, channel, members, role):
        self.id, self._channel, self._members, self._role = gid, channel, {m.id: m for m in members}, role

    def get_channel(self, cid):
        return self._channel if cid == 500 else None

    def get_member(self, uid):
        return self._members.get(uid)

    def get_role(self, rid):
        return self._role if rid == self._role.id else None


async def test_toast_once_per_day_with_role(bot):
    cog = bot.get_cog("Birthdays")
    channel, role = FakeChannel(), SimpleNamespace(id=777)
    ann, bo = FakeMember(1, "Ann"), FakeMember(2, "Bo")
    guild = FakeGuild(42, channel, [ann, bo], role)
    await bot.db.set_birthday(42, 1, 9, 29)
    await bot.db.set_birthday(42, 2, 3, 3)
    await bot.db.set_birthday(42, 3, 9, 29)  # left the server: no toast
    settings = await bot.db.update_settings(42, birthday_channel_id=500, birthday_hour=9, birthday_role_id=777,
                                            timezone="America/Los_Angeles")

    early = datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc)  # 8:00 AM Pacific
    await cog.run_for_guild(guild, settings, now_utc=early)
    assert channel.sent == []

    on_time = datetime(2026, 9, 29, 16, 5, tzinfo=timezone.utc)  # 9:05 AM Pacific
    await cog.run_for_guild(guild, settings, now_utc=on_time)
    assert len(channel.sent) == 1 and "<@1>" in channel.sent[0] and "<@2>" not in channel.sent[0]
    assert role in ann.roles

    settings = await bot.db.get_settings(42)
    await cog.run_for_guild(guild, settings, now_utc=on_time)  # five minutes later: no repeat
    assert len(channel.sent) == 1

    next_day = datetime(2026, 9, 30, 16, 5, tzinfo=timezone.utc)
    await cog.run_for_guild(guild, await bot.db.get_settings(42), now_utc=next_day)
    assert role not in ann.roles  # birthday role retired
    assert len(channel.sent) == 1  # nobody's birthday on the 30th


async def test_no_channel_means_no_toast(bot):
    cog = bot.get_cog("Birthdays")
    channel = FakeChannel()
    guild = FakeGuild(43, channel, [FakeMember(1, "Ann")], SimpleNamespace(id=1))
    await bot.db.set_birthday(43, 1, 9, 29)
    settings = await bot.db.update_settings(43, birthday_hour=0)
    await cog.run_for_guild(guild, settings, now_utc=datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc))
    assert channel.sent == []
