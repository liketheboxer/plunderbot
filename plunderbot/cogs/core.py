"""The basics: who PlunderBot is, and each member's time zone."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import available_timezones

import discord
from discord import app_commands
from discord.ext import commands

from .. import voice
from ..voyage_logic import ZONE_ALIASES, zone_from_name, zone_label

_ZONES = sorted(available_timezones())
_COMMON = ["America/Los_Angeles", "America/Denver", "America/Phoenix", "America/Chicago", "America/New_York",
           "America/Anchorage", "Pacific/Honolulu", "Europe/London", "Europe/Berlin", "Australia/Sydney", "UTC"]


class Core(commands.Cog):
    timezone = app_commands.Group(name="timezone", description="Your time zone, for reading the times you type")

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="plunderbot", description="Meet PlunderBot, the Fortress's robot butler")
    async def about(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(voice.say("about", version=self.bot.version), ephemeral=True)

    @timezone.command(name="set", description="Save your time zone so times you type are read correctly")
    @app_commands.describe(zone="e.g. Pacific, ET, America/Chicago or Europe/London")
    async def tz_set(self, interaction: discord.Interaction, zone: str) -> None:
        tz = zone_from_name(zone)
        if tz is None:
            await interaction.response.send_message(voice.say("tz_unknown", zone=zone), ephemeral=True)
            return
        await self.bot.db.set_member_timezone(interaction.user.id, tz.key)
        now = datetime.now(timezone.utc)
        await interaction.response.send_message(voice.say(
            "tz_saved", zone=zone_label(tz, now), local=now.astimezone(tz).strftime("%-I:%M %p")), ephemeral=True)

    @tz_set.autocomplete("zone")
    async def tz_ac(self, interaction: discord.Interaction, current: str):
        needle = current.strip().lower().replace(" ", "_")
        if not needle:
            names = _COMMON
        else:
            names = [z for z in _ZONES if needle in z.lower()]
            alias = ZONE_ALIASES.get(needle)
            if alias and alias not in names:
                names.insert(0, alias)
        return [app_commands.Choice(name=n, value=n) for n in names[:25]]

    @timezone.command(name="show", description="See the time zone PlunderBot uses for you")
    async def tz_show(self, interaction: discord.Interaction) -> None:
        saved = await self.bot.db.member_timezone_source(interaction.user.id)
        now = datetime.now(timezone.utc)
        if saved:
            tz = zone_from_name(saved[0])
            key = "tz_mine_region" if saved[1] == "region" else "tz_mine"
            text = voice.say(key, zone=zone_label(tz, now), local=now.astimezone(tz).strftime("%-I:%M %p"))
        else:
            settings = await self.bot.db.get_settings(interaction.guild_id) if interaction.guild_id else None
            server = zone_from_name((settings.timezone if settings else None) or self.bot.config.default_timezone)
            text = voice.say("tz_none", zone=zone_label(server, now))
        await interaction.response.send_message(text, ephemeral=True)

    @timezone.command(name="clear", description="Forget your time zone (times are read in the server's)")
    async def tz_clear(self, interaction: discord.Interaction) -> None:
        await self.bot.db.set_member_timezone(interaction.user.id, None)
        regions = self.bot.get_cog("Regions")
        if regions is not None and isinstance(interaction.user, discord.Member):
            await regions.apply(interaction.user)  # fall back to their region role, if any
        saved = await self.bot.db.member_timezone(interaction.user.id)
        if saved:
            now = datetime.now(timezone.utc)
            text = voice.say("tz_cleared_region", zone=zone_label(zone_from_name(saved), now))
        else:
            text = voice.say("tz_cleared")
        await interaction.response.send_message(text, ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(Core(bot))
