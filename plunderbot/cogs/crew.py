"""Crew Call: on-the-spot LFG cards with join buttons and temporary voice channels."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .. import crew_emoji, games, voice
from ..crew_logic import (PING_COOLDOWN, clean_title, expired, iso, now_utc, render_card, voice_channel_name,
                          voice_cleanup_due)
from ..db import Crew

log = logging.getLogger("plunderbot.crew")

GAME_CHOICES = [app_commands.Choice(name=g.name, value=g.key) for g in games.GAMES]
BUTTONS = {
    "join": ("Join", discord.ButtonStyle.success),
    "leave": ("Leave", discord.ButtonStyle.secondary),
    "sail": ("Set Sail", discord.ButtonStyle.primary),
    "close": ("Close", discord.ButtonStyle.danger),
}


class CrewButton(discord.ui.DynamicItem[discord.ui.Button], template=r"crew:(?P<action>join|leave|sail|close):(?P<id>\d+)"):
    """A crew card button. Its custom id carries the crew, so it keeps working after a restart."""

    def __init__(self, action: str, crew_id: int, disabled: bool = False):
        label, style = BUTTONS[action]
        super().__init__(discord.ui.Button(label=label, style=style, custom_id=f"crew:{action}:{crew_id}",
                                           disabled=disabled))
        self.action = action
        self.crew_id = crew_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
        return cls(match["action"], int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("CrewCall")
        if cog is None:
            await interaction.response.send_message(voice.say("error"), ephemeral=True)
            return
        await cog.on_button(interaction, self.action, self.crew_id)


def card_view(crew: Crew) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    over = not crew.active
    view.add_item(CrewButton("join", crew.id, disabled=over or crew.full))
    view.add_item(CrewButton("leave", crew.id, disabled=over))
    profile = games.get(crew.game_key)
    if not (profile and profile.open_ended):  # a hangout is already in voice; no Set Sail
        view.add_item(CrewButton("sail", crew.id, disabled=over or crew.status == "sailing"))
    view.add_item(CrewButton("close", crew.id, disabled=over))
    return view


def _is_mod(member: discord.Member) -> bool:
    p = member.guild_permissions
    return p.manage_channels or p.manage_guild or p.administrator


@app_commands.guild_only()
class CrewCall(commands.GroupCog, group_name="crew", group_description="Muster a crew for a game"):
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()  # serialises every crew change
        self.last_ping: dict[tuple[int, str], object] = {}
        self._background: set[asyncio.Task] = set()  # (guild, game) -> when its role was last pinged
        super().__init__()

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(CrewButton)
        self.upkeep.start()

    async def cog_unload(self) -> None:
        self.upkeep.cancel()
        self.bot.remove_dynamic_items(CrewButton)

    # ------------------------------------------------------------ commands
    @app_commands.command(name="start", description="Post a crew call for a game")
    @app_commands.describe(game="Which game", size="Crew size (depends on the game)",
                           activity="What you're planning (depends on the game)", note="Anything else crewmates should know",
                           name="Name the session (also names the voice channel)")
    @app_commands.choices(game=GAME_CHOICES)
    async def start(self, interaction: discord.Interaction, game: app_commands.Choice[str],
                    size: str | None = None, activity: str | None = None,
                    note: app_commands.Range[str, 1, 200] | None = None,
                    name: app_commands.Range[str, 1, 60] | None = None) -> None:
        profile = games.get(game.value)
        crew_size = profile.size(size)
        if crew_size is None:
            await interaction.response.send_message(voice.say(
                "crew_bad_size", game=profile.name, options=", ".join(s.label for s in profile.sizes)), ephemeral=True)
            return
        tag = profile.tag(activity)
        if activity and tag is None:
            await interaction.response.send_message(voice.say(
                "crew_bad_activity", game=profile.name, options=", ".join(profile.tags)), ephemeral=True)
            return
        channel = interaction.channel
        if isinstance(channel, discord.Thread):
            await interaction.response.send_message(voice.say("crew_no_threads"), ephemeral=True)
            return
        perms = channel.permissions_for(interaction.guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            await interaction.response.send_message(voice.say("crew_cant_post"), ephemeral=True)
            return

        async with self.lock:
            if await self.bot.db.active_crew_led_by(interaction.guild_id, interaction.user.id):
                await interaction.response.send_message(voice.say("crew_one_at_a_time"), ephemeral=True)
                return
            settings = await self.bot.db.get_settings(interaction.guild_id)
            now = now_utc()
            crew = await self.bot.db.create_crew(
                guild_id=interaction.guild_id, channel_id=channel.id, captain_id=interaction.user.id,
                game_key=profile.key, size_label=crew_size.label, capacity=crew_size.capacity,
                activity=tag, note=note, created_at=iso(now), title=clean_title(name),
                expires_at=iso(now + timedelta(minutes=settings.crew_expire_minutes)))
        await interaction.response.send_message(
            voice.say("hangout_started" if profile.open_ended else "crew_started"), ephemeral=True)

        key = "hangout_call" if profile.open_ended else "crew_call"
        text = voice.say(key, captain=interaction.user.mention, game=profile.name, size=crew_size.label)
        mentions = discord.AllowedMentions.none()
        role_id = (await self.bot.db.game_ping_roles(interaction.guild_id)).get(profile.key)
        role = interaction.guild.get_role(role_id) if role_id else None
        last = self.last_ping.get((interaction.guild_id, profile.key))
        if role is not None and (last is None or now - last >= PING_COOLDOWN):
            self.last_ping[(interaction.guild_id, profile.key)] = now
            text += "\n" + voice.say("crew_ping", role=role.mention)
            mentions = discord.AllowedMentions(everyone=False, users=False, roles=[role])
        try:
            _, card_emoji = await self.emoji_for(interaction.guild_id, profile, crew.size_label)
            message = await channel.send(text, embed=render_card(crew, profile, card_emoji), view=card_view(crew),
                                         allowed_mentions=mentions)
        except discord.HTTPException as e:
            log.warning("Couldn't post the card for crew %s: %s", crew.id, e)
            await self.bot.db.update_crew(crew.id, status="closed", ended_at=iso(now_utc()))
            await interaction.followup.send(voice.say("crew_cant_post"), ephemeral=True)
            return
        await self.bot.db.update_crew(crew.id, message_id=message.id)
        if profile.open_ended or crew.full:  # a hangout opens its voice channel straight away
            await self.sail(interaction.guild, crew.id)

    @start.autocomplete("size")
    async def size_autocomplete(self, interaction: discord.Interaction, current: str):
        profile = games.get(getattr(interaction.namespace, "game", None))
        options = [s for s in (profile.sizes if profile else ()) if current.lower() in s.label.lower()]
        return [app_commands.Choice(name=f"{s.label} ({s.capacity})", value=s.label) for s in options][:25]

    @start.autocomplete("activity")
    async def activity_autocomplete(self, interaction: discord.Interaction, current: str):
        profile = games.get(getattr(interaction.namespace, "game", None))
        options = [t for t in (profile.tags if profile else ()) if current.lower() in t.lower()]
        return [app_commands.Choice(name=t, value=t) for t in options][:25]

    @app_commands.command(name="close", description="Close the crew call you're captaining")
    async def close_mine(self, interaction: discord.Interaction) -> None:
        crew = await self.bot.db.active_crew_led_by(interaction.guild_id, interaction.user.id)
        if crew is None:
            await interaction.response.send_message(voice.say("crew_none"), ephemeral=True)
            return
        await interaction.response.send_message(voice.say("crew_closed"), ephemeral=True)
        await self.end(interaction.guild, crew.id, "closed")

    @app_commands.command(name="rename", description="Rename the session you're captaining (and its voice channel)")
    @app_commands.describe(name="The new name; leave empty to go back to the default")
    async def rename(self, interaction: discord.Interaction,
                     name: app_commands.Range[str, 1, 60] | None = None) -> None:
        crew = await self.bot.db.active_crew_led_by(interaction.guild_id, interaction.user.id)
        if crew is None:
            await interaction.response.send_message(voice.say("crew_none"), ephemeral=True)
            return
        crew = await self.bot.db.update_crew(crew.id, title=clean_title(name))
        await interaction.response.send_message(voice.say("crew_renamed"), ephemeral=True)
        await self.refresh_card(interaction.guild, crew)
        vc = interaction.guild.get_channel(crew.voice_channel_id) if crew.voice_channel_id else None
        if vc is not None:
            profile = games.get(crew.game_key)
            channel_emoji, _ = await self.emoji_for(interaction.guild_id, profile, crew.size_label)
            new_name = voice_channel_name(profile, crew.size_label, interaction.user.display_name,
                                          channel_emoji, crew.title)
            # Discord allows two channel renames per ten minutes, so don't hold anything up waiting.
            task = asyncio.create_task(self._rename_channel(vc, new_name))
            self._background.add(task)
            task.add_done_callback(self._background.discard)

    async def _rename_channel(self, vc, new_name: str) -> None:
        try:
            await vc.edit(name=new_name, reason="Crew Call renamed by its captain")
        except discord.HTTPException as e:
            log.warning("Couldn't rename voice channel %s: %s", vc.id, e)

    @app_commands.command(name="list", description="Crews mustering or sailing right now")
    async def list_crews(self, interaction: discord.Interaction) -> None:
        crews = await self.bot.db.active_crews(interaction.guild_id)
        if not crews:
            await interaction.response.send_message(voice.say("crew_none"), ephemeral=True)
            return
        lines = [voice.say("crew_list_header")]
        for c in crews:
            profile = games.get(c.game_key)
            name = profile.name if profile else c.game_key
            where = f"https://discord.com/channels/{c.guild_id}/{c.channel_id}/{c.message_id}" if c.message_id else ""
            lines.append(f"- {name}, {c.size_label}: {len(c.members)}/{c.capacity}, captain <@{c.captain_id}> {where}")
        text = "\n".join(lines)
        if len(text) > 1900:
            text = text[:1900].rsplit("\n", 1)[0] + "\n…and more."
        await interaction.response.send_message(text, ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())

    # ------------------------------------------------------------ buttons
    async def on_button(self, interaction: discord.Interaction, action: str, crew_id: int) -> None:
        user = interaction.user
        reply: str | None = None  # an ephemeral answer, or None to acknowledge silently
        follow_up = None          # "sail", "close" or "refresh", run after the lock is released
        async with self.lock:
            crew = await self.bot.db.get_crew(crew_id)
            if crew is None or not crew.active:
                reply = voice.say("crew_over")
            elif action == "join":
                if user.id in crew.members:
                    reply = voice.say("crew_already_aboard")
                elif not await self.bot.db.add_crew_member(crew.id, user.id, iso(now_utc())):
                    reply = voice.say("crew_full")
                else:
                    crew = await self.bot.db.get_crew(crew.id)
                    if crew.status == "sailing" and crew.voice_channel_id:
                        reply = voice.say("crew_joined_sailing", channel=f"<#{crew.voice_channel_id}>")
                    else:
                        reply = voice.say("crew_joined")
                    follow_up = "sail" if crew.full and crew.status == "open" else "refresh"
            elif action == "leave":
                if user.id == crew.captain_id:
                    reply = voice.say("crew_captain_leave")
                elif not await self.bot.db.remove_crew_member(crew.id, user.id):
                    reply = voice.say("crew_not_aboard")
                else:
                    crew = await self.bot.db.get_crew(crew.id)
                    reply, follow_up = voice.say("crew_left"), "refresh"
            elif action == "sail":
                if user.id != crew.captain_id:
                    reply = voice.say("crew_captain_only")
                else:
                    follow_up = "sail"
            elif action == "close":
                if user.id != crew.captain_id and not _is_mod(user):
                    reply = voice.say("crew_captain_only")
                else:
                    follow_up = "close"

        # The decision is already saved; a failed reply must not stop the card update or the sailing.
        try:
            if reply is not None:
                await interaction.response.send_message(reply, ephemeral=True)
            else:
                await interaction.response.defer()
        except discord.HTTPException as e:
            log.warning("Couldn't answer a crew button press: %s", e)

        if follow_up == "sail":
            await self.sail(interaction.guild, crew.id)
        elif follow_up == "close":
            await self.end(interaction.guild, crew.id, "closed")
        elif follow_up == "refresh":
            await self.refresh_card(interaction.guild, crew)

    async def emoji_for(self, guild_id: int, profile, size_label: str) -> tuple[str, str]:
        """(channel emoji, card emoji) for this game and size on this server."""
        return crew_emoji.resolve(profile, size_label, await self.bot.db.crew_emoji(guild_id))

    # ------------------------------------------------------------ state changes
    async def sail(self, guild: discord.Guild, crew_id: int) -> None:
        async with self.lock:
            crew = await self.bot.db.get_crew(crew_id)
            if crew is None or crew.status != "open":
                return
            crew = await self.bot.db.update_crew(crew.id, status="sailing", sailed_at=iso(now_utc()))
        profile = games.get(crew.game_key)
        settings = await self.bot.db.get_settings(guild.id)
        card_channel = guild.get_channel(crew.channel_id)
        category = guild.get_channel(settings.crew_category_id) if settings.crew_category_id else None
        if not isinstance(category, discord.CategoryChannel):
            category = getattr(card_channel, "category", None)
        captain = guild.get_member(crew.captain_id)
        channel_emoji, _ = await self.emoji_for(guild.id, profile, crew.size_label)
        name = voice_channel_name(profile, crew.size_label, captain.display_name if captain else "Captain",
                                  channel_emoji, crew.title)
        vc = None
        try:
            # No user limit: other members often drop in to hang out and watch the stream.
            vc = await guild.create_voice_channel(name, category=category, reason=f"Crew Call #{crew.id}")
        except discord.HTTPException as e:
            log.warning("Couldn't create a voice channel for crew %s: %s", crew.id, e)
            if self.bot.telemetry is not None:
                self.bot.telemetry.error(e, command="crew-voice")
        if vc is not None:
            async with self.lock:
                current = await self.bot.db.get_crew(crew.id)
                still_sailing = current is not None and current.status == "sailing"
                if still_sailing:
                    crew = await self.bot.db.update_crew(crew.id, voice_channel_id=vc.id,
                                                         voice_empty_since=iso(now_utc()))
            if not still_sailing:  # closed while the channel was being made: don't leave it behind
                try:
                    await vc.delete(reason=f"Crew Call #{crew.id} closed before it sailed")
                except discord.HTTPException as e:
                    log.warning("Couldn't delete voice channel %s: %s", vc.id, e)
                return
        await self.refresh_card(guild, crew)
        if card_channel is not None:
            names = voice.join_names([f"<@{m}>" for m in crew.members])
            key = "crew_sailing" if vc else "crew_sailing_no_voice"
            try:
                await card_channel.send(voice.say(key, names=names, channel=vc.mention if vc else ""),
                                        allowed_mentions=discord.AllowedMentions(
                                            users=[discord.Object(m) for m in crew.members]))
            except discord.HTTPException as e:
                log.warning("Couldn't announce sailing for crew %s: %s", crew.id, e)

    async def end(self, guild: discord.Guild, crew_id: int, status: str) -> None:
        async with self.lock:
            crew = await self.bot.db.get_crew(crew_id)
            if crew is None or not crew.active:
                return
            crew = await self.bot.db.update_crew(crew.id, status=status, ended_at=iso(now_utc()))
        if crew.voice_channel_id and guild is not None:
            vc = guild.get_channel(crew.voice_channel_id)
            if vc is None:
                try:
                    vc = await guild.fetch_channel(crew.voice_channel_id)
                except (discord.NotFound, AttributeError):
                    vc = None
                except discord.HTTPException as e:
                    log.warning("Couldn't look up voice channel %s: %s", crew.voice_channel_id, e)
                    vc = None
            if vc is not None:
                try:
                    await vc.delete(reason=f"Crew Call #{crew.id} is over")
                except discord.HTTPException as e:
                    log.warning("Couldn't delete voice channel %s: %s", vc.id, e)
        await self.refresh_card(guild, crew)

    async def refresh_card(self, guild: discord.Guild | None, crew: Crew) -> None:
        if guild is None or not crew.message_id:
            return
        channel = guild.get_channel(crew.channel_id)
        profile = games.get(crew.game_key)
        if channel is None or profile is None:
            return
        try:
            _, card_emoji = await self.emoji_for(guild.id, profile, crew.size_label)
            await channel.get_partial_message(crew.message_id).edit(embed=render_card(crew, profile, card_emoji),
                                                                    view=card_view(crew))
        except discord.NotFound:
            pass  # someone deleted the card; the crew still runs its course
        except discord.HTTPException as e:
            log.warning("Couldn't update the card for crew %s: %s", crew.id, e)

    # ------------------------------------------------------------ upkeep: expiry and voice cleanup
    @tasks.loop(minutes=1)
    async def upkeep(self) -> None:
        try:
            crews = await self.bot.db.active_crews()
            self.bot.gauge("crews_mustering", sum(c.status == "open" for c in crews))
            self.bot.gauge("crews_sailing", sum(c.status == "sailing" for c in crews))
            now = now_utc()
            for crew in crews:
                guild = self.bot.get_guild(crew.guild_id)
                if guild is None:
                    continue
                try:
                    await self._upkeep_one(guild, crew, now)
                except Exception as e:
                    log.exception("Crew upkeep failed for crew %s", crew.id)
                    if self.bot.telemetry is not None:
                        self.bot.telemetry.error(e, command="crew-upkeep")
        except Exception as e:
            log.exception("Crew upkeep failed")
            if self.bot.telemetry is not None:
                self.bot.telemetry.error(e, command="crew-upkeep")

    @upkeep.before_loop
    async def _wait_until_ready(self) -> None:
        await self.bot.wait_until_ready()

    async def _upkeep_one(self, guild: discord.Guild, crew: Crew, now) -> None:
        if expired(crew, now):
            await self.end(guild, crew.id, "expired" if crew.status == "open" else "closed")
            return
        if crew.status != "sailing" or not crew.voice_channel_id:
            return
        vc = guild.get_channel(crew.voice_channel_id)
        if vc is None:  # deleted by hand
            await self.end(guild, crew.id, "closed")
            return
        in_voice = len(getattr(vc, "members", []))
        if in_voice:
            if crew.voice_empty_since or not crew.voice_occupied:
                await self.bot.db.update_crew(crew.id, voice_empty_since=None, voice_occupied=1)
            return
        if crew.voice_empty_since is None:
            await self.bot.db.update_crew(crew.id, voice_empty_since=iso(now))
            return
        settings = await self.bot.db.get_settings(guild.id)
        if voice_cleanup_due(crew, 0, now, settings.crew_cleanup_minutes):
            await self.end(guild, crew.id, "closed")


async def setup(bot) -> None:
    await bot.add_cog(CrewCall(bot))
