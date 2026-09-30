"""/admin: server settings for Quartermasters, until the Magical Samurai screens exist.

Discord shows these commands only to members with Manage Server. To hand them to the
Quartermaster role instead, use Server Settings > Integrations > PlunderBot.
Replies here are plain English on purpose: they're settings, not banter.
"""
from __future__ import annotations

import re
from zoneinfo import available_timezones

import discord
from discord import app_commands
from discord.ext import commands

from .. import crew_emoji, games
from ..gangplank_logic import emoji_key, APPROVE_DEFAULT, REJECT_DEFAULT, deadline
from ..region_logic import guess_zone
from ..shipslog_logic import WEEKDAYS
from ..voyage_logic import zone_from_name
from ..crew_logic import voice_channel_name
from ..birthday_logic import valid_timezone
from ..discord_util import elevated

_ZONES = sorted(available_timezones())


_elevated = elevated


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
    gangplank = app_commands.Group(name="gangplank", description="Gangplank: the airlock in #introductions")
    shipslog = app_commands.Group(name="shipslog", description="The Ship's Log weekly roundup")
    crowsnest = app_commands.Group(name="crowsnest", description="The Crow's Nest: game news in each game's thread")
    parley = app_commands.Group(name="parley", description="Parley: PlunderBot answering in chat")
    ledger = app_commands.Group(name="ledger", description="The Ship's Ledger: Sea of Thieves ships and plunder")

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
    @app_commands.describe(category="Pick a category from the list (empty: next to the crew card)")
    async def crew_category(self, interaction: discord.Interaction, category: str | None = None) -> None:
        # A plain text option with our own suggestions: Discord's channel picker often won't
        # select categories, especially ones with symbols in their names.
        found = None
        if category is not None:
            wanted = category.strip()
            for c in interaction.guild.categories:
                if str(c.id) == wanted or c.name.lower() == wanted.lower():
                    found = c
                    break
            if found is None:
                await interaction.response.send_message(
                    f"I can't find a category called \"{category}\". Pick one from the list.", ephemeral=True)
                return
            if not found.permissions_for(interaction.guild.me).manage_channels:
                await interaction.response.send_message(
                    f"I need Manage Channels in {found.name} to open voice channels there.", ephemeral=True)
                return
        await self.bot.db.update_settings(interaction.guild_id, crew_category_id=found.id if found else None)
        where = found.name if found else "the same category as each crew card"
        await interaction.response.send_message(f"Crew voice channels will open in {where}.", ephemeral=True)

    @crew_category.autocomplete("category")
    async def crew_category_ac(self, interaction: discord.Interaction, current: str):
        needle = current.strip().lower()
        return [app_commands.Choice(name=c.name[:100], value=str(c.id))
                for c in interaction.guild.categories if needle in c.name.lower()][:25]

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

    # ------------------------------------------------------------ gangplank
    @gangplank.command(name="setup", description="Channels and roles for the airlock (doesn't turn it on)")
    @app_commands.describe(intro_channel="Where newcomers introduce themselves (#introductions)",
                           pending_role="The airlock role newcomers wear (Pending)",
                           harbormaster_role="Who can let people aboard or turn them away (Harbormasters)",
                           rules_channel="Linked in the welcome (#welcome)",
                           orientation_channel="Linked once they're aboard (#new-pirate-orientation)",
                           alert_channel="Optional: where Harbormasters hear about new intros and kicks")
    async def gangplank_setup(self, interaction: discord.Interaction, intro_channel: discord.TextChannel,
                              pending_role: discord.Role, harbormaster_role: discord.Role,
                              rules_channel: discord.TextChannel, orientation_channel: discord.TextChannel,
                              alert_channel: discord.TextChannel | None = None) -> None:
        me = interaction.guild.me
        problems = []
        if pending_role.is_default() or pending_role.managed:
            problems.append("Pending must be an ordinary role.")
        if not me.guild_permissions.manage_roles or pending_role >= me.top_role:
            problems.append(f"PlunderBot needs Manage Roles and its role above {pending_role.mention}.")
        if not me.guild_permissions.kick_members:
            problems.append("PlunderBot needs Kick Members to turn people away.")
        perms = intro_channel.permissions_for(me)
        if not (perms.view_channel and perms.send_messages and perms.read_message_history):
            problems.append(f"PlunderBot needs View Channel, Send Messages and Read Message History in "
                            f"{intro_channel.mention}.")
        if alert_channel is not None and not alert_channel.permissions_for(me).send_messages:
            problems.append(f"PlunderBot can't post in {alert_channel.mention}.")
        if problems:
            await interaction.response.send_message("Not saved:\n- " + "\n- ".join(problems), ephemeral=True,
                                                    allowed_mentions=discord.AllowedMentions.none())
            return
        s = await self.bot.db.update_settings(
            interaction.guild_id, intro_channel_id=intro_channel.id, pending_role_id=pending_role.id,
            harbormaster_role_id=harbormaster_role.id, rules_channel_id=rules_channel.id,
            orientation_channel_id=orientation_channel.id,
            gangplank_alert_channel_id=alert_channel.id if alert_channel else None)
        state = "on" if s.gangplank_enabled else "off (turn it on with /admin gangplank on)"
        await interaction.response.send_message(
            f"Gangplank saved. Newcomers get {pending_role.mention} and introduce themselves in "
            f"{intro_channel.mention}; {harbormaster_role.mention} react Yar or Nar. Gangplank is {state}.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @gangplank.command(name="emoji", description="Which emoji approve and reject (default: server emoji named Yar and Nar)")
    @app_commands.describe(approve="Paste the emoji, or leave empty for the one named Yar",
                           reject="Paste the emoji, or leave empty for the one named Nar")
    async def gangplank_emoji(self, interaction: discord.Interaction, approve: str | None = None,
                              reject: str | None = None) -> None:
        values = {}
        for field, text in (("approve_emoji", approve), ("reject_emoji", reject)):
            if text is None:
                values[field] = None
                continue
            key = emoji_key(text)
            if key is None or (key.isdigit() and interaction.guild.get_emoji(int(key)) is None):
                await interaction.response.send_message(
                    f"I can't use \"{text}\". Paste the emoji itself (one from this server, or a standard one).",
                    ephemeral=True)
                return
            values[field] = key
        if values.get("approve_emoji") and values.get("approve_emoji") == values.get("reject_emoji"):
            await interaction.response.send_message("Approve and reject need different emoji.", ephemeral=True)
            return
        await self.bot.db.update_settings(interaction.guild_id, **values)
        await interaction.response.send_message(
            f"Approve: {self._emoji_label(interaction.guild, values['approve_emoji'], APPROVE_DEFAULT)}. "
            f"Reject: {self._emoji_label(interaction.guild, values['reject_emoji'], REJECT_DEFAULT)}.", ephemeral=True)

    @staticmethod
    def _emoji_label(guild, key: str | None, default_name: str) -> str:
        if key is None:
            found = next((e for e in guild.emojis if e.name.lower() == default_name), None)
            return f"{found} (the server emoji named {found.name})" if found else \
                f"a server emoji named {default_name.capitalize()} (none found yet!)"
        if key.isdigit():
            e = guild.get_emoji(int(key))
            return str(e) if e else f"a deleted emoji ({key})"
        return key

    @gangplank.command(name="timing", description="Days before newcomers who haven't introduced themselves are reminded, then kicked")
    async def gangplank_timing(self, interaction: discord.Interaction, remind_days: app_commands.Range[int, 1, 30],
                               kick_days: app_commands.Range[int, 2, 60]) -> None:
        if remind_days >= kick_days:
            await interaction.response.send_message("The reminder has to come before the kick.", ephemeral=True)
            return
        await self.bot.db.update_settings(interaction.guild_id, gangplank_remind_days=remind_days,
                                          gangplank_kick_days=kick_days)
        await interaction.response.send_message(
            f"Newcomers who haven't introduced themselves get a reminder after {remind_days} day(s) and are "
            f"kicked after {kick_days}.", ephemeral=True)

    @gangplank.command(name="on", description="Start greeting, reminding and letting newcomers aboard")
    async def gangplank_on(self, interaction: discord.Interaction) -> None:
        s = await self.bot.db.get_settings(interaction.guild_id)
        if not (s.intro_channel_id and s.pending_role_id and s.harbormaster_role_id):
            await interaction.response.send_message("Run /admin gangplank setup first.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        s = await self.bot.db.update_settings(interaction.guild_id, gangplank_enabled=1)
        cog = self.bot.get_cog("Gangplank")
        found = await cog.catch_up(interaction.guild, s, discord.utils.utcnow()) if cog else 0
        await interaction.followup.send(
            f"Gangplank is on. {found} member(s) already wearing Pending are now tracked; their "
            f"{s.gangplank_remind_days}-day reminder and {s.gangplank_kick_days}-day kick clocks start now, "
            "and anyone who has already posted in the intro channel won't be kicked.\n"
            "Turn off MEE6's welcome message and its Pending automation so newcomers aren't greeted twice.",
            ephemeral=True)

    @gangplank.command(name="off", description="Stop greeting, reminding and kicking newcomers")
    async def gangplank_off(self, interaction: discord.Interaction) -> None:
        await self.bot.db.update_settings(interaction.guild_id, gangplank_enabled=0)
        await interaction.response.send_message("Gangplank is off. Nobody will be greeted, reminded or kicked.",
                                                ephemeral=True)

    @gangplank.command(name="status", description="Who's waiting on the gangplank")
    async def gangplank_status(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        s = await self.bot.db.get_settings(guild.id)
        lines = [f"**Gangplank is {'on' if s.gangplank_enabled else 'off'}**",
                 f"Intro channel: {f'<#{s.intro_channel_id}>' if s.intro_channel_id else 'not set'} · "
                 f"Pending: {f'<@&{s.pending_role_id}>' if s.pending_role_id else 'not set'} · "
                 f"Harbormasters: {f'<@&{s.harbormaster_role_id}>' if s.harbormaster_role_id else 'not set'}",
                 f"Approve: {self._emoji_label(guild, s.approve_emoji, APPROVE_DEFAULT)} · "
                 f"Reject: {self._emoji_label(guild, s.reject_emoji, REJECT_DEFAULT)}",
                 f"Reminder after {s.gangplank_remind_days} day(s), kick after {s.gangplank_kick_days} "
                 "for anyone who hasn't introduced themselves"]
        rows = await self.bot.db.boardings(guild.id)
        if rows:
            lines.append("")
            for b in rows:
                if b.responded_at:
                    state = "introduced, waiting for a Harbormaster"
                else:
                    kick = deadline(b.joined_at, s.gangplank_kick_days)
                    state = f"hasn't introduced themselves; kicked <t:{int(kick.timestamp())}:R>"
                joined = deadline(b.joined_at, 0)
                lines.append(f"<@{b.user_id}>: since <t:{int(joined.timestamp())}:R>, {state}")
        else:
            lines.append("Nobody is waiting.")
        await interaction.response.send_message("\n".join(lines)[:1990], ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())

    # ------------------------------------------------------------ Ship's Log
    @shipslog.command(name="channel", description="Where the weekly roundup posts (leave empty to turn it off)")
    async def shipslog_channel(self, interaction: discord.Interaction,
                               channel: discord.TextChannel | None = None) -> None:
        if channel is not None:
            perms = channel.permissions_for(interaction.guild.me)
            if not (perms.view_channel and perms.send_messages and perms.embed_links):
                await interaction.response.send_message(
                    f"I need View Channel, Send Messages and Embed Links in {channel.mention}.", ephemeral=True)
                return
        s = await self.bot.db.update_settings(interaction.guild_id,
                                              shipslog_channel_id=channel.id if channel else None)
        if channel is None:
            await interaction.response.send_message("The Ship's Log is off.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"The Ship's Log will post in {channel.mention} every {WEEKDAYS[s.shipslog_weekday]} at "
            f"{_hour_label(s.shipslog_hour)} {s.timezone or self.bot.config.default_timezone}. "
            "Change that with /admin shipslog when; see it now with /admin shipslog preview.", ephemeral=True)

    @shipslog.command(name="when", description="Which day and hour the roundup posts (server time)")
    @app_commands.describe(hour="0 to 23; 18 means 6:00 PM")
    @app_commands.choices(day=[app_commands.Choice(name=d, value=i) for i, d in enumerate(WEEKDAYS)])
    async def shipslog_when(self, interaction: discord.Interaction, day: app_commands.Choice[int],
                            hour: app_commands.Range[int, 0, 23]) -> None:
        s = await self.bot.db.update_settings(interaction.guild_id, shipslog_weekday=day.value, shipslog_hour=hour)
        await interaction.response.send_message(
            f"The Ship's Log will post every {day.name} at {_hour_label(hour)} "
            f"{s.timezone or self.bot.config.default_timezone}.", ephemeral=True)

    @shipslog.command(name="preview", description="See this week's roundup privately")
    async def shipslog_preview(self, interaction: discord.Interaction) -> None:
        cog = self.bot.get_cog("ShipsLog")
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(embed=await cog.build(interaction.guild), ephemeral=True)

    @shipslog.command(name="post", description="Post this week's roundup now")
    async def shipslog_post(self, interaction: discord.Interaction) -> None:
        s = await self.bot.db.get_settings(interaction.guild_id)
        if not s.shipslog_channel_id:
            await interaction.response.send_message("Set a channel first with /admin shipslog channel.",
                                                    ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        msg = await self.bot.get_cog("ShipsLog").post(interaction.guild)
        await interaction.followup.send(f"Posted: {msg.jump_url}" if msg else "Its channel is gone.",
                                        ephemeral=True)

    # ------------------------------------------------------------ Crow's Nest
    @crowsnest.command(name="on", description="Start posting game news in each game's forum thread")
    async def crowsnest_on(self, interaction: discord.Interaction) -> None:
        s = await self.bot.db.get_settings(interaction.guild_id)
        if not s.forum_channel_id:
            await interaction.response.send_message(
                "Tell me the game forum first: /noticeboard gameindex forum:#game-discussion.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.bot.db.update_settings(interaction.guild_id, crowsnest_enabled=1)
        notes = await self.bot.get_cog("CrowsNest").check(interaction.guild)
        await interaction.followup.send(
            "The Crow's Nest is on. I check for news every 30 minutes; what's already out was noted, not "
            "posted.\n" + self._news_notes(notes), ephemeral=True)

    @crowsnest.command(name="off", description="Stop posting game news")
    async def crowsnest_off(self, interaction: discord.Interaction) -> None:
        await self.bot.db.update_settings(interaction.guild_id, crowsnest_enabled=0)
        await interaction.response.send_message("The Crow's Nest is off.", ephemeral=True)

    @crowsnest.command(name="check", description="Look for game news now, and show each game's status")
    async def crowsnest_check(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        notes = await self.bot.get_cog("CrowsNest").check(interaction.guild)
        await interaction.followup.send(self._news_notes(notes), ephemeral=True)

    @staticmethod
    def _news_notes(notes: dict[str, str]) -> str:
        lines = [f"**{games.get(k).name if games.get(k) else k}**: {v}" for k, v in notes.items()]
        return ("\n".join(lines) or "No games to watch.")[:1990]

    @crowsnest.command(name="source", description="Where a game's news comes from")
    @app_commands.describe(game="Which game", kind="Steam app, RSS/Atom feed, or no news",
                           value="The Steam app id (the number in its store link), or the feed's web address")
    @app_commands.choices(game=[app_commands.Choice(name=g.name, value=g.key) for g in games.GAMES if g.crew_call],
                          kind=[app_commands.Choice(name="Steam app", value="steam"),
                                app_commands.Choice(name="RSS or Atom feed", value="feed"),
                                app_commands.Choice(name="No news for this game", value="none"),
                                app_commands.Choice(name="Back to the default", value="default")])
    async def crowsnest_source(self, interaction: discord.Interaction, game: app_commands.Choice[str],
                               kind: app_commands.Choice[str], value: str | None = None) -> None:
        if kind.value == "steam":
            m = re.search(r"(\d{3,10})", value or "")
            if not m:
                await interaction.response.send_message(
                    "Give the Steam app id, e.g. 1172620, or paste the store link.", ephemeral=True)
                return
            value = m.group(1)
        elif kind.value == "feed":
            if not (value or "").startswith(("http://", "https://")):
                await interaction.response.send_message("Give the feed's full web address.", ephemeral=True)
                return
        await self.bot.db.set_news_source(interaction.guild_id, game.value,
                                          None if kind.value == "default" else kind.value,
                                          value if kind.value in ("steam", "feed") else None)
        text = {"steam": f"{game.name} news will come from Steam app {value}.",
                "feed": f"{game.name} news will come from {value}.",
                "none": f"No news will be posted for {game.name}.",
                "default": f"{game.name} is back to its built-in news source."}[kind.value]
        await interaction.response.send_message(text + " Try /admin crowsnest preview to see its latest post.",
                                                ephemeral=True)

    @crowsnest.command(name="preview", description="See a game's latest news post privately")
    @app_commands.choices(game=[app_commands.Choice(name=g.name, value=g.key) for g in games.GAMES if g.crew_call])
    async def crowsnest_preview(self, interaction: discord.Interaction, game: app_commands.Choice[str]) -> None:
        await interaction.response.defer(ephemeral=True)
        cog = self.bot.get_cog("CrowsNest")
        try:
            item = await cog.latest(interaction.guild, game.value)
        except Exception as e:
            await interaction.followup.send(f"I couldn't read {game.name}'s news: {e}", ephemeral=True)
            return
        if item is None:
            await interaction.followup.send(f"{game.name} has no news source, or nothing posted yet.",
                                            ephemeral=True)
            return
        await interaction.followup.send(embed=cog.embed(game.name, item), ephemeral=True)

    # ------------------------------------------------------------ Parley
    @parley.command(name="on", description="Let members chat with PlunderBot by @mentioning or replying to it")
    async def parley_on(self, interaction: discord.Interaction) -> None:
        if not self.bot.config.anthropic_api_key:
            await interaction.response.send_message(
                "Add the ANTHROPIC_API_KEY secret to PlunderBot in Exocomp and refit first.", ephemeral=True)
            return
        s = await self.bot.db.update_settings(interaction.guild_id, parley_enabled=1)
        web = "with Kagi web search" if self.bot.config.kagi_api_key else "answering from what it knows (no web search)"
        await interaction.response.send_message(
            f"Parley is on, {web}. Members @mention PlunderBot or reply to it, in any channel everyone can see. "
            f"Limits: ${s.parley_budget_cents / 100:.2f} a month, {s.parley_daily} replies per member a day"
            + (f", {s.parley_kagi_daily} web searches a day" if self.bot.config.kagi_api_key else "")
            + ". See /admin parley status.", ephemeral=True)

    @parley.command(name="off", description="Stop PlunderBot answering in chat")
    async def parley_off(self, interaction: discord.Interaction) -> None:
        await self.bot.db.update_settings(interaction.guild_id, parley_enabled=0)
        await interaction.response.send_message("Parley is off. Slash commands carry on as normal.", ephemeral=True)

    @parley.command(name="status", description="This month's spending and today's usage")
    async def parley_status(self, interaction: discord.Interaction) -> None:
        cog = self.bot.get_cog("Parley")
        s = await self.bot.db.get_settings(interaction.guild_id)
        day, month, _ = cog.today(s)
        spent, calls = await self.bot.db.parley_spend(interaction.guild_id, month)
        lookups = await self.bot.db.parley_lookups(interaction.guild_id, day)
        off = await self.bot.db.parley_off_channels(interaction.guild_id)
        cfg = self.bot.config
        lines = [f"**Parley is {'on' if s.parley_enabled else 'off'}** (model {cfg.parley_model})",
                 f"Claude key: {'set' if cfg.anthropic_api_key else 'missing'} · Web search: "
                 f"{'on (Kagi)' if cfg.kagi_api_key else 'off (no Kagi key)'}",
                 f"This month: ${spent:.2f} of ${s.parley_budget_cents / 100:.2f} ({calls} Claude calls)",
                 f"Web searches today: {lookups} of {s.parley_kagi_daily} (about ${lookups * 0.015:.2f})",
                 f"Replies per member per day: {s.parley_daily}"]
        if off:
            lines.append("Switched off in: " + ", ".join(f"<#{c}>" for c in off))
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @parley.command(name="channel", description="Switch Parley off (or back on) in one channel")
    async def parley_channel(self, interaction: discord.Interaction, channel: discord.abc.GuildChannel,
                             on: bool) -> None:
        await self.bot.db.set_parley_channel(interaction.guild_id, channel.id, on)
        await interaction.response.send_message(
            f"Parley is {'back on' if on else 'off'} in {channel.mention}.", ephemeral=True)

    @parley.command(name="limits", description="Monthly budget, replies per member per day, web searches per day")
    @app_commands.describe(budget="Dollars a month for Claude", daily="Replies per member per day",
                           searches="Kagi web searches per day (about 1.5 cents each)")
    async def parley_limits(self, interaction: discord.Interaction,
                            budget: app_commands.Range[float, 0, 100] | None = None,
                            daily: app_commands.Range[int, 0, 200] | None = None,
                            searches: app_commands.Range[int, 0, 500] | None = None) -> None:
        changes = {}
        if budget is not None:
            changes["parley_budget_cents"] = int(round(budget * 100))
        if daily is not None:
            changes["parley_daily"] = daily
        if searches is not None:
            changes["parley_kagi_daily"] = searches
        s = await self.bot.db.update_settings(interaction.guild_id, **changes)
        await interaction.response.send_message(
            f"Limits: ${s.parley_budget_cents / 100:.2f} a month, {s.parley_daily} replies per member a day, "
            f"{s.parley_kagi_daily} web searches a day.", ephemeral=True)


    # ------------------------------------------------------------ the Ship's Ledger
    @ledger.command(name="reminders", description="Remind Sea of Thieves crews to screenshot and log their Captain's Log")
    @app_commands.describe(on="On: a nudge when a crew sets sail and when it's back in port")
    async def ledger_reminders(self, interaction: discord.Interaction, on: bool) -> None:
        await self.bot.db.update_settings(interaction.guild_id, ledger_reminders=int(on))
        await interaction.response.send_message(
            "Captain's Log reminders are on: Sea of Thieves crews get a nudge when they set sail and when they're "
            "back in port." if on else "Captain's Log reminders are off. `/ship log` still works.", ephemeral=True)

    @ledger.command(name="remove", description="Take a haul out of the ledger (the number is in its footer)")
    @app_commands.describe(entry="The ledger entry number, e.g. 12 from 'Ledger entry #12'")
    async def ledger_remove(self, interaction: discord.Interaction, entry: int) -> None:
        found = await self.bot.db.get_log(entry)
        if found is None or found.guild_id != interaction.guild_id:
            await interaction.response.send_message(f"There's no ledger entry #{entry}.", ephemeral=True)
            return
        await self.bot.get_cog("ShipLedger").remove(interaction.guild, found)
        crew = await self.bot.db.get_crew(found.crew_id) if found.crew_id else None
        crew_cog = self.bot.get_cog("CrewCall")
        if crew is not None and crew_cog is not None:
            await crew_cog.refresh_card(interaction.guild, crew)
        await interaction.response.send_message(
            f"Ledger entry #{entry} ({found.gold:,} gold) is gone, and its post with it.", ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(Admin(bot))
