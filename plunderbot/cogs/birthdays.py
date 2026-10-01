"""Birthdays: members save their own month and day; PlunderBot toasts them on the day.

No years are stored, so nobody's age is ever on file.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .. import voice
from ..birthday_logic import change_allowed, due_to_announce, is_birthday_on, upcoming, valid_date, zone

log = logging.getLogger("plunderbot.birthdays")

MONTH_CHOICES = [app_commands.Choice(name=name, value=i) for i, name in enumerate(voice.MONTH_NAMES, start=1)]


@app_commands.guild_only()
class Birthdays(commands.GroupCog, group_name="birthday", group_description="Your birthday in the ship's ledger"):
    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    async def cog_load(self) -> None:
        self.announcer.start()

    async def cog_unload(self) -> None:
        self.announcer.cancel()

    # ------------------------------------------------------------ member commands
    @app_commands.command(name="set", description="Save your birthday (month and day only, no year)")
    @app_commands.choices(month=MONTH_CHOICES)
    async def set_birthday(self, interaction: discord.Interaction, month: app_commands.Choice[int],
                           day: app_commands.Range[int, 1, 31]) -> None:
        await interaction.response.send_message(
            await self.set_as(interaction.guild_id, interaction.user.id, month.value, day), ephemeral=True)

    @app_commands.command(name="remove", description="Remove your birthday from the ledger")
    async def remove_birthday(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(await self.remove_as(interaction.guild_id, interaction.user.id),
                                                ephemeral=True)

    @app_commands.command(name="mine", description="See the birthday PlunderBot has for you")
    async def my_birthday(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(await self.mine_as(interaction.guild_id, interaction.user.id),
                                                ephemeral=True)

    # A member's own birthday, for the slash commands and Parley (1.6.0).
    async def set_as(self, gid: int, uid: int, m: int, day: int) -> str:
        if not 1 <= m <= 12 or not valid_date(m, day):
            return voice.say("birthday_invalid", month_name=voice.MONTH_NAMES[m - 1] if 1 <= m <= 12 else str(m),
                             day=day)
        had = await self.bot.db.get_birthday(gid, uid)
        if had == (m, day):
            return voice.say("birthday_mine", date=voice.format_date(m, day))
        now = datetime.now(timezone.utc)
        last = await self.bot.db.last_birthday_change(gid, uid)
        allowed, new_window, locked_until = change_allowed(datetime.fromisoformat(last) if last else None, now)
        if not allowed:
            return voice.say("birthday_too_soon", date=voice.format_date(locked_until.month, locked_until.day))
        await self.bot.db.set_birthday(gid, uid, m, day)
        if new_window:
            await self.bot.db.record_birthday_change(gid, uid, now.isoformat())
        key = "birthday_changed" if had and had != (m, day) else "birthday_set"
        return voice.say(key, date=voice.format_date(m, day))

    async def remove_as(self, gid: int, uid: int) -> str:
        removed = await self.bot.db.remove_birthday(gid, uid)
        return voice.say("birthday_removed" if removed else "birthday_not_found")

    async def mine_as(self, gid: int, uid: int) -> str:
        found = await self.bot.db.get_birthday(gid, uid)
        return voice.say("birthday_mine", date=voice.format_date(*found)) if found else voice.say("birthday_not_found")

    @app_commands.command(name="upcoming", description="The next birthdays on the ship's calendar")
    async def upcoming_birthdays(self, interaction: discord.Interaction) -> None:
        settings = await self.bot.db.get_settings(interaction.guild_id)
        today = datetime.now(zone(settings.timezone, self.bot.config.default_timezone)).date()
        entries = await self.bot.db.birthdays(interaction.guild_id)
        # Only list people still on the server.
        entries = [e for e in entries if interaction.guild.get_member(e[0]) is not None]
        if not entries:
            await interaction.response.send_message(voice.say("birthdays_none"), ephemeral=True)
            return
        lines = [voice.say("birthdays_upcoming_header")]
        for user_id, when in upcoming(entries, today, limit=10):
            label = "today!" if when == today else voice.format_date(when.month, when.day)
            lines.append(f"- {label}: <@{user_id}>")
        # Mentions render as names but ping nobody.
        await interaction.response.send_message("\n".join(lines), allowed_mentions=discord.AllowedMentions.none())

    # ------------------------------------------------------------ the daily toast
    @tasks.loop(minutes=5)
    async def announcer(self) -> None:
        try:
            self.bot.gauge("birthdays_on_file", await self.bot.db.count_birthdays())
            for settings in await self.bot.db.all_settings():
                guild = self.bot.get_guild(settings.guild_id)
                if guild is None:
                    continue
                try:
                    await self.run_for_guild(guild, settings)
                except Exception as e:  # one server's problem shouldn't stop the others
                    log.exception("Birthday run failed for guild %s", guild.id)
                    if self.bot.telemetry is not None:
                        self.bot.telemetry.error(e, command="birthday-announcer")
        except Exception as e:
            log.exception("Birthday announcer failed")
            if self.bot.telemetry is not None:
                self.bot.telemetry.error(e, command="birthday-announcer")

    @announcer.before_loop
    async def _wait_until_ready(self) -> None:
        await self.bot.wait_until_ready()

    async def run_for_guild(self, guild: discord.Guild, settings, now_utc: datetime | None = None) -> None:
        now_local = (now_utc or datetime.now(timezone.utc)).astimezone(
            zone(settings.timezone, self.bot.config.default_timezone))
        today = now_local.date()
        await self._retire_old_roles(guild, today.isoformat())
        if settings.birthday_channel_id is None:
            return
        if not due_to_announce(now_local, settings.birthday_hour, settings.birthday_last_announced):
            return
        channel = guild.get_channel(settings.birthday_channel_id)
        # Mark the day first, so a failed post can never turn into a toast every five minutes.
        await self.bot.db.update_settings(guild.id, birthday_last_announced=today.isoformat())
        members = []
        for user_id, month, day in await self.bot.db.birthdays(guild.id):
            if is_birthday_on(month, day, today):
                member = guild.get_member(user_id)
                if member is not None:
                    members.append(member)
        if not members:
            return
        members.sort(key=lambda m: m.display_name.lower())
        names = voice.join_names([m.mention for m in members])
        key = "birthday_toast_one" if len(members) == 1 else "birthday_toast_many"
        if channel is not None and hasattr(channel, "send"):
            await channel.send(voice.say(key, names=names),
                               allowed_mentions=discord.AllowedMentions(users=members, everyone=False, roles=False))
        else:
            log.warning("Birthday channel %s is missing in guild %s", settings.birthday_channel_id, guild.id)
        await self._grant_roles(guild, settings, members, today.isoformat())

    async def _grant_roles(self, guild: discord.Guild, settings, members, today: str) -> None:
        if not settings.birthday_role_id:
            return
        role = guild.get_role(settings.birthday_role_id)
        if role is None:
            log.warning("Birthday role %s no longer exists in guild %s", settings.birthday_role_id, guild.id)
            return
        for member in members:
            try:
                await member.add_roles(role, reason="Happy birthday from PlunderBot")
                await self.bot.db.record_role_grant(guild.id, member.id, role.id, today)
            except discord.HTTPException as e:
                log.warning("Couldn't give %s the birthday role: %s", member.id, e)

    async def _retire_old_roles(self, guild: discord.Guild, today: str) -> None:
        for user_id, role_id in await self.bot.db.stale_role_grants(guild.id, today):
            member = guild.get_member(user_id)
            role = guild.get_role(role_id)
            if member is not None and role is not None and role in member.roles:
                try:
                    await member.remove_roles(role, reason="Birthday's over; back to regular duties")
                except discord.HTTPException as e:
                    log.warning("Couldn't remove the birthday role from %s: %s", user_id, e)
                    continue
            await self.bot.db.clear_role_grant(guild.id, user_id)


async def setup(bot) -> None:
    await bot.add_cog(Birthdays(bot))
