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

from .. import crew_emoji, games
from ..region_logic import guess_zone
from ..voyage_logic import zone_from_name
from ..crew_logic import voice_channel_name
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
    crew = app_commands.Group(name="crew", description="Crew Call settings")
    voyages = app_commands.Group(name="voyages", description="Voyage settings")
    regions = app_commands.Group(name="regions", description="Region roles that set members' time zones")

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
        category = f"<#{s.crew_category_id}>" if s.crew_category_id else "same category as the crew card"
        crew_cards = f"<#{s.crew_channel_id}>" if s.crew_channel_id else "wherever /crew start is used"
        pings = await self.bot.db.game_ping_roles(interaction.guild_id)
        ping_text = ", ".join(f"{games.get(k).name if games.get(k) else k} <@&{r}>" for k, r in sorted(pings.items()))
        text = (
            f"**PlunderBot {self.bot.version} settings**\n"
            f"Time zone: {tz}\n"
            f"Birthday channel: {channel}\n"
            f"Birthday announcement time: {_hour_label(s.birthday_hour)} {s.timezone or self.bot.config.default_timezone}\n"
            f"Birthday role: {role}\n"
            f"Birthdays on file: {count}\n"
            f"Crew cards: {crew_cards}\n"
            f"Crew voice channels: {category}\n"
            f"Empty crew voice channels removed after: {s.crew_cleanup_minutes} min\n"
            f"Unfilled crew calls expire after: {s.crew_expire_minutes} min\n"
            f"Crew ping roles: {ping_text or 'none'}\n"
            f"Voyage cards: {f'<#{s.voyage_channel_id}>' if s.voyage_channel_id else 'wherever /voyage create is used'}"
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
        s = await self.bot.db.get_settings(interaction.guild_id)
        await interaction.response.send_message(
            f"Birthday toasts will go out at {_hour_label(hour)} {s.timezone or self.bot.config.default_timezone} "
            "(the server's time zone, set with /admin timezone).",
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

    # ------------------------------------------------------------ crew call
    @crew.command(name="category", description="Category for crew voice channels (leave empty: next to the card)")
    async def crew_category(self, interaction: discord.Interaction,
                            category: discord.CategoryChannel | None = None) -> None:
        if category is not None and not category.permissions_for(interaction.guild.me).manage_channels:
            await interaction.response.send_message(
                f"I need Manage Channels in {category.name} to open voice channels there.", ephemeral=True)
            return
        await self.bot.db.update_settings(interaction.guild_id, crew_category_id=category.id if category else None)
        where = category.name if category else "the same category as each crew card"
        await interaction.response.send_message(f"Crew voice channels will open in {where}.", ephemeral=True)

    @crew.command(name="channel", description="Where every crew card goes, including voyages that set sail (empty: where it's started)")
    async def crew_channel_cmd(self, interaction: discord.Interaction,
                               channel: discord.TextChannel | None = None) -> None:
        if channel is not None:
            perms = channel.permissions_for(interaction.guild.me)
            if not (perms.view_channel and perms.send_messages and perms.embed_links):
                await interaction.response.send_message(
                    f"I can't post in {channel.mention}. Give PlunderBot View Channel, Send Messages and "
                    "Embed Links there first.", ephemeral=True)
                return
        await self.bot.db.update_settings(interaction.guild_id, crew_channel_id=channel.id if channel else None)
        where = channel.mention if channel else "whichever channel /crew start is used in (voyages: their own channel)"
        await interaction.response.send_message(f"Crew cards will be posted in {where}.", ephemeral=True)

    @crew.command(name="cleanup", description="Minutes an empty crew voice channel waits before it's removed")
    async def crew_cleanup(self, interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 120]) -> None:
        await self.bot.db.update_settings(interaction.guild_id, crew_cleanup_minutes=minutes)
        await interaction.response.send_message(
            f"Empty crew voice channels will be removed after {minutes} min "
            "(15 min minimum before anyone has joined).", ephemeral=True)

    @crew.command(name="expire", description="Minutes before an unfilled crew call closes itself")
    async def crew_expire(self, interaction: discord.Interaction, minutes: app_commands.Range[int, 10, 720]) -> None:
        await self.bot.db.update_settings(interaction.guild_id, crew_expire_minutes=minutes)
        await interaction.response.send_message(
            f"New crew calls will close after {minutes} min if they haven't sailed.", ephemeral=True)

    @crew.command(name="pingrole", description="Role pinged when a crew call opens for a game (empty: no ping)")
    @app_commands.choices(game=[app_commands.Choice(name=g.name, value=g.key) for g in games.GAMES])
    async def crew_pingrole(self, interaction: discord.Interaction, game: app_commands.Choice[str],
                            role: discord.Role | None = None) -> None:
        if role is None:
            await self.bot.db.set_game_ping_role(interaction.guild_id, game.value, None)
            await interaction.response.send_message(f"{game.name} crew calls won't ping anyone.", ephemeral=True)
            return
        if role.is_default() or role.managed or _elevated(role.permissions):
            await interaction.response.send_message(
                "Pick an opt-in game role with no special permissions.", ephemeral=True)
            return
        await self.bot.db.set_game_ping_role(interaction.guild_id, game.value, role.id)
        note = ""
        if not role.mentionable and not interaction.guild.me.guild_permissions.mention_everyone:
            note = (" Heads up: that role isn't mentionable, so the ping won't go through. Turn on "
                    "\"Allow anyone to @mention this role\" in its settings.")
        await interaction.response.send_message(f"{game.name} crew calls will ping {role.mention}.{note}",
                                                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @crew.command(name="autopings", description="Match each game to its ping role by name, and optionally create missing ones")
    @app_commands.describe(create_missing="Create a mentionable, permission-free role for games that have none")
    async def crew_autopings(self, interaction: discord.Interaction, create_missing: bool = False) -> None:
        guild, me = interaction.guild, interaction.guild.me
        await interaction.response.defer(ephemeral=True)
        current = await self.bot.db.game_ping_roles(guild.id)
        matched, kept, created, missing, unmentionable, failed = [], [], [], [], [], []
        for g in games.GAMES:
            if not g.crew_call:  # "Server event" has no ping role of its own
                continue
            role = guild.get_role(current[g.key]) if g.key in current else None
            if role is not None:
                kept.append((g, role))
            else:
                role = next((r for r in guild.roles if g.matches_role_name(r.name) and not r.managed
                             and not r.is_default() and not _elevated(r.permissions)), None)
                if role is None and create_missing:
                    try:
                        role = await guild.create_role(name=g.name, mentionable=True,
                                                       permissions=discord.Permissions.none(),
                                                       reason="PlunderBot crew ping role")
                        created.append((g, role))
                    except discord.HTTPException as e:
                        failed.append(f"{g.name} ({e.text or e.status})")
                        continue
                elif role is not None:
                    matched.append((g, role))
                if role is None:
                    missing.append(g.name)
                    continue
                await self.bot.db.set_game_ping_role(guild.id, g.key, role.id)
            if not role.mentionable and not me.guild_permissions.mention_everyone:
                unmentionable.append(role.mention)
        lines = ["**Crew ping roles**"]
        if matched:
            lines.append("Matched: " + ", ".join(f"{g.name} → {r.mention}" for g, r in matched))
        if created:
            lines.append("Created: " + ", ".join(r.mention for _, r in created))
        if kept:
            lines.append("Already set: " + ", ".join(f"{g.name} → {r.mention}" for g, r in kept))
        if missing:
            lines.append("No role yet: " + ", ".join(missing)
                         + ("" if create_missing else ". Run again with create_missing:True to make them."))
        if failed:
            lines.append("Couldn't create: " + ", ".join(failed) + ". PlunderBot needs Manage Roles.")
        if unmentionable:
            lines.append("Not mentionable, so pings won't go through until you turn on "
                         "\"Allow anyone to @mention this role\": " + ", ".join(unmentionable))
        text = "\n".join(lines)
        await interaction.followup.send(text[:1990], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @crew.command(name="emoji", description="Pick the emoji for a game's crew cards and voice channels")
    @app_commands.describe(game="Which game", size="One crew size, or leave empty for every size of the game",
                           emoji="A standard emoji or one of this server's emoji; type reset to go back to the default")
    @app_commands.choices(game=[app_commands.Choice(name=g.name, value=g.key) for g in games.GAMES])
    async def crew_emoji_cmd(self, interaction: discord.Interaction, game: app_commands.Choice[str],
                             emoji: str, size: str | None = None) -> None:
        profile = games.get(game.value)
        label = ""
        if size:
            chosen = profile.size(size)
            if chosen is None:
                await interaction.response.send_message(
                    f"{profile.name} sizes are: {', '.join(s.label for s in profile.sizes)}.", ephemeral=True)
                return
            label = chosen.label
        what = f"{profile.name} {label}".strip() if label else f"every {profile.name} crew"
        value = emoji.strip()
        if value.lower() == "reset":
            await self.bot.db.set_crew_emoji(interaction.guild_id, profile.key, label, standard=None, server=None)
            channel, card = crew_emoji.resolve(profile, label or profile.default_size.label,
                                               await self.bot.db.crew_emoji(interaction.guild_id))
            await interaction.response.send_message(f"Reset {what}: now {card}.", ephemeral=True)
            return
        if crew_emoji.is_custom(value):
            emoji_id = int(value.rsplit(":", 1)[1].rstrip(">"))
            if interaction.guild.get_emoji(emoji_id) is None:
                await interaction.response.send_message(
                    "That emoji isn't one of this server's, so I can't be sure I'll be able to show it. "
                    "Pick one from the list as you type.", ephemeral=True)
                return
            await self.bot.db.set_crew_emoji(interaction.guild_id, profile.key, label, server=value)
            channel, _ = crew_emoji.resolve(profile, label or profile.default_size.label,
                                            await self.bot.db.crew_emoji(interaction.guild_id))
            await interaction.response.send_message(
                f"Crew cards for {what} will show {value}. Discord doesn't allow server emoji in channel names, "
                f"so the voice channel keeps {channel}. Set a standard emoji too to change that.", ephemeral=True)
            return
        if not crew_emoji.is_standard(value):
            await interaction.response.send_message(
                "That doesn't look like an emoji. Paste a standard emoji, or pick a server emoji from the list.",
                ephemeral=True)
            return
        await self.bot.db.set_crew_emoji(interaction.guild_id, profile.key, label, standard=value)
        sample = profile.size(label) or profile.default_size
        preview = voice_channel_name(profile, sample.label, interaction.user.display_name, value)
        await interaction.response.send_message(
            f"Done: {what} will use {value}. A voice channel will look like **{preview}**.", ephemeral=True)

    @crew_emoji_cmd.autocomplete("size")
    async def crew_emoji_size_ac(self, interaction: discord.Interaction, current: str):
        profile = games.get(getattr(interaction.namespace, "game", None))
        sizes = profile.sizes if profile and not profile.open_ended else ()
        return [app_commands.Choice(name=s.label, value=s.label) for s in sizes
                if current.lower() in s.label.lower()][:25]

    @crew_emoji_cmd.autocomplete("emoji")
    async def crew_emoji_emoji_ac(self, interaction: discord.Interaction, current: str):
        needle = current.strip(":").lower()
        options = [app_commands.Choice(name="reset (back to the default)", value="reset")] if "reset".startswith(needle) else []
        for e in interaction.guild.emojis:
            if needle in e.name.lower():
                options.append(app_commands.Choice(name=f":{e.name}: (server emoji)", value=str(e)))
        if current and crew_emoji.is_standard(current):
            options.insert(0, app_commands.Choice(name=current, value=current))
        return options[:25]

    # ------------------------------------------------------------ voyages
    @voyages.command(name="channel", description="Where voyage cards are posted (leave empty: wherever it's created)")
    async def voyages_channel(self, interaction: discord.Interaction,
                              channel: discord.TextChannel | None = None) -> None:
        if channel is not None:
            perms = channel.permissions_for(interaction.guild.me)
            if not (perms.view_channel and perms.send_messages and perms.embed_links):
                await interaction.response.send_message(
                    f"I can't post in {channel.mention}. Give PlunderBot View Channel, Send Messages and "
                    "Embed Links there first.", ephemeral=True)
                return
        await self.bot.db.update_settings(interaction.guild_id, voyage_channel_id=channel.id if channel else None)
        where = channel.mention if channel else "whichever channel /voyage create is used in"
        await interaction.response.send_message(f"Voyage cards will be posted in {where}.", ephemeral=True)

    # ------------------------------------------------------------ regions
    async def _sync_regions(self, guild) -> str:
        cog = self.bot.get_cog("Regions")
        if cog is None:
            return ""
        r = await cog.sync_guild(guild)
        text = f"Updated members: {r.set} zone(s) set, {r.cleared} cleared."
        if r.kept_manual:
            text += f" {r.kept_manual} member(s) chose their own zone with /timezone set, so theirs stayed."
        return text

    async def _region_lines(self, guild) -> list[str]:
        mapping = await self.bot.db.region_zones(guild.id)
        lines = []
        for role_id, zone in mapping.items():
            role = guild.get_role(role_id)
            if role is not None:
                lines.append(f"{role.mention} → {zone} ({len(role.members)} member(s))")
        return lines

    @regions.command(name="auto", description="Match region roles to time zones by name")
    async def regions_auto(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        await interaction.response.defer(ephemeral=True)
        current = await self.bot.db.region_zones(guild.id)
        matched, kept, rough, broad = [], [], [], []
        for role in guild.roles:
            if role.is_default() or role.managed:
                continue
            guess = guess_zone(role.name)
            if guess is None:
                continue
            if role.id in current:
                kept.append(f"{role.mention} → {current[role.id]}")
            elif guess.zone is None:
                broad.append(f"{role.mention} ({guess.note})")
            else:
                await self.bot.db.set_region_zone(guild.id, role.id, guess.zone)
                matched.append(f"{role.mention} → {guess.zone}")
                if guess.note:
                    rough.append(f"{role.mention}: {guess.note}")
        lines = ["**Region roles → time zones**"]
        if matched:
            lines.append("Matched: " + ", ".join(matched))
        if kept:
            lines.append("Already set: " + ", ".join(kept))
        if rough:
            lines.append("Rough guesses (members can fine-tune with /timezone set): " + "; ".join(rough))
        if broad:
            lines.append("Too broad for one zone, so left alone (members set theirs with /timezone set, "
                         "or map it with /admin regions set): " + ", ".join(broad))
        if len(lines) == 1:
            lines.append("No region roles found by name. Map them with /admin regions set.")
        lines.append(await self._sync_regions(guild))
        await interaction.followup.send("\n".join(lines)[:1990], ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())

    @regions.command(name="set", description="Make a role stand for a time zone")
    @app_commands.describe(role="The region role", zone="e.g. America/Chicago, Europe/London, ET")
    async def regions_set(self, interaction: discord.Interaction, role: discord.Role, zone: str) -> None:
        tz = zone_from_name(zone)
        if tz is None:
            await interaction.response.send_message(
                f"I don't know the time zone \"{zone}\". Try one like America/Chicago.", ephemeral=True)
            return
        if role.is_default() or role.managed:
            await interaction.response.send_message("Pick a region role members choose for themselves.",
                                                    ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.bot.db.set_region_zone(interaction.guild_id, role.id, tz.key)
        text = f"{role.mention} now sets members' time zone to {tz.key}.\n" + await self._sync_regions(interaction.guild)
        await interaction.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @regions_set.autocomplete("zone")
    async def regions_zone_ac(self, interaction: discord.Interaction, current: str):
        needle = current.strip().lower().replace(" ", "_")
        return [app_commands.Choice(name=z, value=z) for z in _ZONES if needle in z.lower()][:25]

    @regions.command(name="clear", description="Stop a role from setting time zones")
    async def regions_clear(self, interaction: discord.Interaction, role: discord.Role) -> None:
        await interaction.response.defer(ephemeral=True)
        await self.bot.db.set_region_zone(interaction.guild_id, role.id, None)
        text = f"{role.mention} no longer sets time zones.\n" + await self._sync_regions(interaction.guild)
        await interaction.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @regions.command(name="list", description="Show which region roles set which time zones")
    async def regions_list(self, interaction: discord.Interaction) -> None:
        lines = await self._region_lines(interaction.guild)
        text = "\n".join(["**Region roles → time zones**", *lines]) if lines else \
            "No region roles are mapped yet. Try /admin regions auto."
        await interaction.response.send_message(text[:1990], ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())


async def setup(bot) -> None:
    await bot.add_cog(Admin(bot))
