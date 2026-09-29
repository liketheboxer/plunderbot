"""/admin: server settings for Quartermasters, until the Magical Samurai screens exist.

Discord shows these commands only to members with Manage Server. To hand them to the
Quartermaster role instead, use Server Settings > Integrations > PlunderBot.
Replies here are plain English on purpose: they're settings, not banter.
"""
from __future__ import annotations

from zoneinfo import available_timezones

import discord
from discord import app_commands
from discord.ext import commands

from ..birthday_logic import valid_timezone

_ZONES = sorted(available_timezones())


def _elevated(p: discord.Permissions) -> bool:
    """A role with any of these is too powerful to hand out automatically."""
    return any((p.administrator, p.manage_guild, p.manage_roles, p.manage_channels, p.manage_messages,
                p.manage_webhooks, p.manage_nicknames, p.manage_events, p.manage_expressions,
                p.kick_members, p.ban_members, p.moderate_members, p.mention_everyone,
                p.view_audit_log, p.move_members, p.mute_members, p.deafen_members))


def _hour_label(hour: int) -> str:
    suffix = "AM" if hour < 12 else "PM"
    h = hour % 12 or 12
    return f"{h}:00 {suffix}"


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
class Admin(commands.GroupCog, group_name="admin", group_description="PlunderBot settings for Quartermasters"):
    birthdays = app_commands.Group(name="birthdays", description="Birthday announcement settings")

    def __init__(self, bot):
        self.bot = bot
        super().__init__()

    # ------------------------------------------------------------ general
    @app_commands.command(name="settings", description="Show PlunderBot's settings for this server")
    async def show(self, interaction: discord.Interaction) -> None:
        s = await self.bot.db.get_settings(interaction.guild_id)
        tz = s.timezone or f"{self.bot.config.default_timezone} (default)"
        channel = f"<#{s.birthday_channel_id}>" if s.birthday_channel_id else "not set (announcements off)"
        role = f"<@&{s.birthday_role_id}>" if s.birthday_role_id else "none"
        count = len(await self.bot.db.birthdays(interaction.guild_id))
        text = (
            f"**PlunderBot {self.bot.version} settings**\n"
            f"Time zone: {tz}\n"
            f"Birthday channel: {channel}\n"
            f"Birthday announcement time: {_hour_label(s.birthday_hour)}\n"
            f"Birthday role: {role}\n"
            f"Birthdays on file: {count}"
        )
        await interaction.response.send_message(text, ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="timezone", description="Set the server's time zone (used for birthday timing)")
    @app_commands.describe(name="An IANA time zone, e.g. America/Los_Angeles")
    async def timezone(self, interaction: discord.Interaction, name: str) -> None:
        if not valid_timezone(name):
            await interaction.response.send_message(
                f"`{name}` isn't a time zone I recognise. Pick one from the list as you type.", ephemeral=True)
            return
        await self.bot.db.update_settings(interaction.guild_id, timezone=name)
        await interaction.response.send_message(f"Time zone set to {name}.", ephemeral=True)

    @timezone.autocomplete("name")
    async def timezone_autocomplete(self, interaction: discord.Interaction, current: str):
        needle = current.lower().replace(" ", "_")
        matches = [z for z in _ZONES if needle in z.lower()][:25]
        return [app_commands.Choice(name=z, value=z) for z in matches]

    # ------------------------------------------------------------ birthdays
    @birthdays.command(name="channel", description="Where birthday toasts are posted")
    async def birthday_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        perms = channel.permissions_for(interaction.guild.me)
        if not (perms.view_channel and perms.send_messages):
            await interaction.response.send_message(
                f"I can't post in {channel.mention}. Give PlunderBot View Channel and Send Messages there first.",
                ephemeral=True)
            return
        await self.bot.db.update_settings(interaction.guild_id, birthday_channel_id=channel.id)
        await interaction.response.send_message(f"Birthday toasts will go to {channel.mention}.", ephemeral=True)

    @birthdays.command(name="hour", description="What hour birthday toasts go out, in the server's time zone")
    @app_commands.describe(hour="0 to 23; 9 means 9:00 AM")
    async def birthday_hour(self, interaction: discord.Interaction,
                            hour: app_commands.Range[int, 0, 23]) -> None:
        await self.bot.db.update_settings(interaction.guild_id, birthday_hour=hour)
        await interaction.response.send_message(f"Birthday toasts will go out at {_hour_label(hour)}.",
                                                ephemeral=True)

    @birthdays.command(name="role", description="A role members wear on their birthday (leave empty to turn off)")
    async def birthday_role(self, interaction: discord.Interaction, role: discord.Role | None = None) -> None:
        if role is None:
            await self.bot.db.update_settings(interaction.guild_id, birthday_role_id=None)
            await interaction.response.send_message("Birthday role turned off.", ephemeral=True)
            return
        me, user = interaction.guild.me, interaction.user
        if role.managed or role.is_default():
            await interaction.response.send_message("That role can't be handed out by a bot.", ephemeral=True)
            return
        if _elevated(role.permissions):
            await interaction.response.send_message(
                f"{role.mention} carries moderator or admin permissions, so it can't be a birthday role. "
                "Use a cosmetic role with no special permissions.", ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none())
            return
        if user.id != interaction.guild.owner_id and not (
                user.guild_permissions.manage_roles and role < user.top_role):
            await interaction.response.send_message(
                "You need Manage Roles, and a role above that one, to make it the birthday role.", ephemeral=True)
            return
        if not me.guild_permissions.manage_roles or role >= me.top_role:
            await interaction.response.send_message(
                f"I can't hand out {role.mention}. PlunderBot needs Manage Roles, and its own role must sit "
                "above that role in Server Settings > Roles.", ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none())
            return
        await self.bot.db.update_settings(interaction.guild_id, birthday_role_id=role.id)
        await interaction.response.send_message(f"Members will wear {role.mention} on their birthday.",
                                                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @birthdays.command(name="off", description="Stop posting birthday toasts")
    async def birthday_off(self, interaction: discord.Interaction) -> None:
        await self.bot.db.update_settings(interaction.guild_id, birthday_channel_id=None)
        await interaction.response.send_message(
            "Birthday toasts are off. Members can still save their birthdays.", ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(Admin(bot))
