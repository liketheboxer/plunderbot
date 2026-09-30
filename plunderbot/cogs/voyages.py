"""Voyages: scheduled sessions with RSVPs, reminders, repeats and a matching Discord Event.

When a voyage starts, its Aboard list becomes a Crew Call crew: the voice channel opens, the crew is
pinged, and latecomers can still join from the crew card. The same code runs any game, or none.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .. import crew_emoji, games, images, voice
from ..birthday_logic import zone
from ..crew_logic import iso, now_utc
from ..db import Voyage
from ..mentions import send_pinging
from ..voyage_logic import (REMINDER_PRESETS, REPEATS, ParseError, Rsvps, due_reminder, format_reminders,
                            is_weekday_name, next_occurrence, overdue_reminders, parse_date, parse_reminders,
                            parse_time, placement, render_voyage, split_zone, to_utc, zone_label)

log = logging.getLogger("plunderbot.voyages")

GAME_CHOICES = [app_commands.Choice(name=g.name, value=g.key) for g in games.GAMES]
REPEAT_CHOICES = [app_commands.Choice(name=label, value=key) for key, label in REPEATS.items()]
PINGS = {"posted": "Tag the game's role when it's posted",
         "reminders": "Tag the game's role when posted, at each reminder and when it sails",
         "off": "Don't tag the game's role"}
PING_CHOICES = [app_commands.Choice(name=label, value=key) for key, label in PINGS.items()]
BUTTONS = {
    "aboard": ("Aboard", discord.ButtonStyle.success),
    "maybe": ("Maybe", discord.ButtonStyle.secondary),
    "cant": ("Can't make it", discord.ButtonStyle.danger),
}
# If PlunderBot was offline right through a voyage, don't open a voice channel hours late.
LATE_START_LIMIT = timedelta(minutes=30)


class VoyageButton(discord.ui.DynamicItem[discord.ui.Button], template=r"voyage:(?P<action>aboard|maybe|cant):(?P<id>\d+)"):
    def __init__(self, action: str, voyage_id: int, disabled: bool = False):
        label, style = BUTTONS[action]
        super().__init__(discord.ui.Button(label=label, style=style, custom_id=f"voyage:{action}:{voyage_id}",
                                           disabled=disabled))
        self.action = action
        self.voyage_id = voyage_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
        return cls(match["action"], int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("Voyages")
        if cog is None:
            await interaction.response.send_message(voice.say("error"), ephemeral=True)
            return
        await cog.on_button(interaction, self.action, self.voyage_id)


def voyage_view(v: Voyage) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    closed = v.status != "scheduled"
    for action in BUTTONS:
        view.add_item(VoyageButton(action, v.id, disabled=closed))
    return view


def _can_manage(member, v: Voyage) -> bool:
    p = member.guild_permissions
    return member.id == v.organizer_id or p.manage_events or p.manage_guild or p.administrator


def _link(v: Voyage) -> str:
    return f"https://discord.com/channels/{v.guild_id}/{v.channel_id}/{v.message_id}" if v.message_id else ""


@app_commands.guild_only()
class Voyages(commands.GroupCog, group_name="voyage", group_description="Schedule a voyage (a planned session)"):
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()
        super().__init__()

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(VoyageButton)
        self.clock.start()

    async def cog_unload(self) -> None:
        self.clock.cancel()
        self.bot.remove_dynamic_items(VoyageButton)

    # ------------------------------------------------------------ helpers
    async def tz(self, guild_id: int):
        settings = await self.bot.db.get_settings(guild_id)
        return zone(settings.timezone, self.bot.config.default_timezone)

    async def reading_zone(self, user_id: int, guild_id: int):
        """The zone to read a member's typed times in: theirs if they've set one, else the server's.
        Returns (zone, whose) where whose is "yours" or "server"."""
        mine = await self.bot.db.member_timezone(user_id)
        if mine:
            tz = zone(mine, self.bot.config.default_timezone)
            return tz, "yours"
        return await self.tz(guild_id), "server"

    async def emoji(self, v: Voyage) -> str:
        profile = games.get(v.game_key)
        if profile is None:
            profile = games.get("event")
        size = v.size_label or profile.default_size.label
        return crew_emoji.resolve(profile, size, await self.bot.db.crew_emoji(v.guild_id))[1]

    def card_file(self, channel, image_name: str | None) -> dict:
        crew_cog = self.bot.get_cog("CrewCall")
        return crew_cog.card_file(channel, image_name) if crew_cog else {}

    async def game_role(self, guild: discord.Guild, v: Voyage):
        """The game's ping role, if the voyage has one and it still exists."""
        if not v.game_key:
            return None
        role_id = (await self.bot.db.game_ping_roles(guild.id)).get(v.game_key)
        return guild.get_role(role_id) if role_id else None

    async def refresh(self, guild: discord.Guild | None, v: Voyage, new_image: bool = False) -> None:
        if guild is None or not v.message_id:
            return
        channel = guild.get_channel(v.channel_id)
        if channel is None:
            return
        rsvps = await self.bot.db.rsvps(v.id)
        try:
            crew_link = None
            if v.crew_id:
                crew = await self.bot.db.get_crew(v.crew_id)
                if crew is not None and crew.message_id:
                    crew_link = f"https://discord.com/channels/{crew.guild_id}/{crew.channel_id}/{crew.message_id}"
            embed = images.show(render_voyage(v, rsvps, games.get(v.game_key), await self.emoji(v), crew_link),
                                v.image, self.bot.config.data_dir)
            extra = {}
            if new_image:  # swap (or drop) the picture attached to the card
                f = self.card_file(channel, v.image)
                extra["attachments"] = [f["file"]] if f else []
            await channel.get_partial_message(v.message_id).edit(embed=embed, view=voyage_view(v), **extra)
        except discord.NotFound:
            pass
        except discord.HTTPException as e:
            log.warning("Couldn't update the card for voyage %s: %s", v.id, e)

    async def post(self, guild: discord.Guild, v: Voyage, announce_role: bool = True) -> Voyage:
        """Post a voyage's card (and its Discord Event). Returns the voyage with its ids filled in."""
        channel = guild.get_channel(v.channel_id)
        if channel is None:
            raise LookupError(f"voyage channel {v.channel_id} is gone")
        profile = games.get(v.game_key)
        text = voice.say("voyage_posted", organizer=f"<@{v.organizer_id}>", title=v.title)
        mentions = discord.AllowedMentions.none()
        if announce_role and profile is not None and v.ping_role != "off":
            role = await self.game_role(guild, v)
            if role is not None:
                text += "\n" + voice.say("crew_ping", role=role.mention)
                mentions = discord.AllowedMentions(everyone=False, users=False, roles=[role])
        rsvps = await self.bot.db.rsvps(v.id)
        embed = images.show(render_voyage(v, rsvps, profile, await self.emoji(v)), v.image, self.bot.config.data_dir)
        message = await channel.send(text, embed=embed, view=voyage_view(v), allowed_mentions=mentions,
                                     **self.card_file(channel, v.image))
        v = await self.bot.db.update_voyage(v.id, message_id=message.id)
        event_id = await self.sync_event(guild, v)
        if event_id:
            v = await self.bot.db.update_voyage(v.id, event_id=event_id)
        return v

    async def sync_event(self, guild: discord.Guild, v: Voyage, action: str = "upsert") -> int | None:
        """Keep the matching Discord Event in step. Failures are logged, never fatal."""
        start = datetime.fromisoformat(v.starts_at)
        channel = guild.get_channel(v.channel_id)
        description = (v.description or "")[:800]
        if v.message_id:
            description = (description + f"\n\nRSVP here: {_link(v)}").strip()
        location = f"#{channel.name}" if channel is not None else "Brimstone Hill"
        try:
            event = None
            if v.event_id:
                event = guild.get_scheduled_event(v.event_id)
                if event is None:
                    try:
                        event = await guild.fetch_scheduled_event(v.event_id)
                    except discord.NotFound:
                        event = None
            if action == "cancel":
                if event is not None and event.status == discord.EventStatus.scheduled:
                    await event.cancel()
                return v.event_id
            if action == "start":
                if event is not None and event.status == discord.EventStatus.scheduled:
                    await event.start()
                return v.event_id
            if action == "end":
                if event is not None and event.status == discord.EventStatus.active:
                    await event.end()
                elif event is not None and event.status == discord.EventStatus.scheduled:
                    await event.cancel()  # it never got going
                return v.event_id
            fields = dict(name=v.title[:100], description=description[:1000], start_time=start,
                          end_time=start + timedelta(minutes=v.duration_min), location=location[:100])
            if event is not None:
                await event.edit(**fields)
                return event.id
            event = await guild.create_scheduled_event(entity_type=discord.EntityType.external,
                                                       privacy_level=discord.PrivacyLevel.guild_only, **fields)
            return event.id
        except discord.HTTPException as e:
            log.warning("Discord Event sync (%s) failed for voyage %s: %s", action, v.id, e)
            return v.event_id

    # ------------------------------------------------------------ commands
    @app_commands.command(name="create", description="Schedule a voyage: a planned session people can RSVP to")
    @app_commands.describe(
        title="What it's called, e.g. Friday Fort Night",
        date="friday, tomorrow, 10/3 or 2026-10-03",
        time="8pm, 8:30pm or 20:30, in your time zone (/timezone set), or add one: 8pm ET",
        game="The game, or leave empty for a general server event",
        size="Crew size (depends on the game); sets how many can be Aboard",
        seats="Override how many can be Aboard (leave empty for the crew size, or no limit)",
        description="Details for the crew",
        reminders="When to remind people before the start, e.g. 1d, 1h (default) or none",
        repeat="Repeat this voyage",
        duration="Expected length in minutes (for the Discord Event)",
        image="A picture for the voyage card (it goes on the crew card too when it sails)",
        notify="When to tag the game's ping role (default: when it's posted)")
    @app_commands.choices(game=GAME_CHOICES, repeat=REPEAT_CHOICES, notify=PING_CHOICES)
    async def create(self, interaction: discord.Interaction, title: app_commands.Range[str, 1, 80],
                     date: str, time: str, game: app_commands.Choice[str] | None = None,
                     size: str | None = None, seats: app_commands.Range[int, 1, 99] | None = None,
                     description: app_commands.Range[str, 1, 1000] | None = None,
                     reminders: str | None = None, repeat: app_commands.Choice[str] | None = None,
                     duration: app_commands.Range[int, 15, 720] = 120,
                     image: discord.Attachment | None = None,
                     notify: app_commands.Choice[str] | None = None) -> None:
        guild = interaction.guild
        tz, whose = await self.reading_zone(interaction.user.id, guild.id)
        profile = games.get(game.value) if game else None
        now = now_utc()
        try:
            time_text, typed_zone = split_zone(time)
            if typed_zone is not None:
                tz, whose = typed_zone, "typed"
            day = parse_date(date, datetime.now(tz).date())
            starts = to_utc(day, parse_time(time_text), tz)
            if starts <= now and is_weekday_name(date):  # "friday" on a Friday evening means next Friday
                starts = to_utc(day + timedelta(days=7), parse_time(time_text), tz)
            minutes = parse_reminders(reminders)
        except ParseError as e:
            await interaction.response.send_message(voice.say("voyage_bad_input", error=str(e)), ephemeral=True)
            return
        if starts <= now + timedelta(minutes=1) or starts > now + timedelta(days=366):
            await interaction.response.send_message(voice.say("voyage_bad_time"), ephemeral=True)
            return
        size_label, capacity = None, seats
        if profile is not None:
            chosen = profile.size(size)
            if chosen is None:
                await interaction.response.send_message(voice.say(
                    "crew_bad_size", game=profile.name, options=", ".join(s.label for s in profile.sizes)),
                    ephemeral=True)
                return
            size_label = chosen.label
            if capacity is None and not profile.open_ended:
                capacity = chosen.capacity
        settings = await self.bot.db.get_settings(guild.id)
        channel = guild.get_channel(settings.voyage_channel_id) if settings.voyage_channel_id else interaction.channel
        if channel is None or isinstance(channel, discord.Thread):
            await interaction.response.send_message(voice.say("crew_no_threads"), ephemeral=True)
            return
        perms = channel.permissions_for(guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            await interaction.response.send_message(voice.say("crew_cant_post"), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        image_name = None
        if image is not None:
            try:
                image_name = await images.save(image, self.bot.config.data_dir)
            except (images.ImageError, discord.HTTPException, OSError) as e:
                log.warning("Voyage picture refused: %r", e)
                await interaction.followup.send(voice.say("image_bad"), ephemeral=True)
                return
        v = await self.bot.db.create_voyage(
            guild_id=guild.id, channel_id=channel.id, organizer_id=interaction.user.id, title=title.strip(),
            description=description, game_key=profile.key if profile else None, size_label=size_label,
            capacity=capacity, starts_at=iso(starts), duration_min=duration,
            reminders=",".join(str(m) for m in minutes), repeat=repeat.value if repeat else "none",
            created_at=iso(now), image=image_name, ping_role=notify.value if notify else "posted")
        v = await self.bot.db.update_voyage(v.id, series_id=v.id)
        await self.bot.db.set_rsvp(v.id, interaction.user.id, "aboard", iso(now))
        try:
            v = await self.post(guild, v)
        except discord.HTTPException as e:
            log.warning("Couldn't post voyage %s: %s", v.id, e)
            await self.bot.db.update_voyage(v.id, status="cancelled")
            await interaction.followup.send(voice.say("crew_cant_post"), ephemeral=True)
            return
        await interaction.followup.send(
            voice.say("voyage_created", link=_link(v), reminders=format_reminders(minutes),
                      when=f"<t:{int(starts.timestamp())}:F>")
            + "\n" + self.zone_note(tz, whose, starts), ephemeral=True)

    @staticmethod
    def zone_note(tz, whose: str, starts: datetime) -> str:
        """Tell the organizer which time zone their typed time was read in, so a mix-up is obvious."""
        label = zone_label(tz, starts)
        if whose == "server":
            return (f"I read your time as {label}, the server's time zone. Everyone sees it in their own time. "
                    "If you're elsewhere, set yours once with `/timezone set`, or add a zone like `8pm ET`.")
        if whose == "typed":
            return f"I read your time as {label}. Everyone sees it in their own time."
        return f"I read your time as {label}, your saved time zone. Everyone sees it in their own time."

    @create.autocomplete("size")
    async def size_ac(self, interaction: discord.Interaction, current: str):
        profile = games.get(getattr(interaction.namespace, "game", None))
        sizes = profile.sizes if profile and not profile.open_ended else ()
        return [app_commands.Choice(name=f"{s.label} ({s.capacity})", value=s.label)
                for s in sizes if current.lower() in s.label.lower()][:25]

    @create.autocomplete("reminders")
    async def reminders_ac(self, interaction: discord.Interaction, current: str):
        options = [app_commands.Choice(name=label, value=value) for label, value in REMINDER_PRESETS
                   if current.lower() in label.lower() or current.lower() in value]
        if current and all(o.value != current for o in options):
            try:
                parsed = parse_reminders(current)
                options.insert(0, app_commands.Choice(name=f"Custom: {format_reminders(parsed)}", value=current))
            except ParseError:
                pass
        return options[:25]

    async def _manageable(self, interaction: discord.Interaction, current: str):
        # Autocomplete can't show Discord timestamps, so write the time in the member's own zone.
        tz, _ = await self.reading_zone(interaction.user.id, interaction.guild_id)
        out = []
        for v in await self.bot.db.voyages_with_status("scheduled", guild_id=interaction.guild_id):
            if not _can_manage(interaction.user, v) or current.lower() not in v.title.lower():
                continue
            when = datetime.fromisoformat(v.starts_at).astimezone(tz).strftime("%a %b %-d, %-I:%M %p %Z")
            out.append(app_commands.Choice(name=f"{v.title[:70]} ({when})", value=str(v.id)))
        return out[:25]

    async def _fetch_manageable(self, interaction: discord.Interaction, value: str) -> Voyage | None:
        v = await self.bot.db.get_voyage(int(value)) if value.isdigit() else None
        if v is None or v.guild_id != interaction.guild_id or v.status != "scheduled":
            await interaction.response.send_message(voice.say("voyage_none"), ephemeral=True)
            return None
        if not _can_manage(interaction.user, v):
            await interaction.response.send_message(voice.say("voyage_not_yours"), ephemeral=True)
            return None
        return v

    @app_commands.command(name="edit", description="Change a voyage you organized")
    @app_commands.describe(voyage="Which voyage", title="New title", date="New date", time="New time",
                           description="New details", reminders="New reminders, e.g. 1d, 1h or none",
                           seats="New number of seats Aboard", image="A new picture for the card",
                           remove_image="Take the picture off the card", notify="When to tag the game's ping role")
    @app_commands.choices(notify=PING_CHOICES)
    async def edit(self, interaction: discord.Interaction, voyage: str,
                   title: app_commands.Range[str, 1, 80] | None = None, date: str | None = None,
                   time: str | None = None, description: app_commands.Range[str, 1, 1000] | None = None,
                   reminders: str | None = None, seats: app_commands.Range[int, 1, 99] | None = None,
                   image: discord.Attachment | None = None, remove_image: bool = False,
                   notify: app_commands.Choice[str] | None = None) -> None:
        v = await self._fetch_manageable(interaction, voyage)
        if v is None:
            return
        tz, whose = await self.reading_zone(interaction.user.id, v.guild_id)
        changes: dict = {}
        starts = None
        try:
            if date or time:
                if time:
                    time_text, typed_zone = split_zone(time)
                    if typed_zone is not None:
                        tz, whose = typed_zone, "typed"
                local = datetime.fromisoformat(v.starts_at).astimezone(tz)
                day = parse_date(date, datetime.now(tz).date()) if date else local.date()
                at = parse_time(time_text) if time else local.time().replace(tzinfo=None)
                starts = to_utc(day, at, tz)
                if starts <= now_utc() + timedelta(minutes=1):
                    await interaction.response.send_message(voice.say("voyage_bad_time"), ephemeral=True)
                    return
                # Reminders count again from the new time, starting now.
                changes.update(starts_at=iso(starts), reminders_sent="")
            if reminders is not None:
                changes.update(reminders=",".join(str(m) for m in parse_reminders(reminders)), reminders_sent="")
        except ParseError as e:
            await interaction.response.send_message(voice.say("voyage_bad_input", error=str(e)), ephemeral=True)
            return
        if title:
            changes["title"] = title.strip()
        if description:
            changes["description"] = description
        if seats:
            changes["capacity"] = seats
        if notify:
            changes["ping_role"] = notify.value
        if remove_image and image is None:
            changes["image"] = None
        if not changes and image is None:
            await interaction.response.send_message(voice.say("voyage_nothing_changed"), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        if image is not None:
            try:
                changes["image"] = await images.save(image, self.bot.config.data_dir)
            except (images.ImageError, discord.HTTPException, OSError) as e:
                log.warning("Voyage picture refused: %r", e)
                await interaction.followup.send(voice.say("image_bad"), ephemeral=True)
                return
        async with self.lock:
            current = await self.bot.db.get_voyage(v.id)
            if current is None or current.status != "scheduled":  # it started meanwhile
                await interaction.followup.send(voice.say("voyage_over"), ephemeral=True)
                return
            if "starts_at" in changes or "reminders" in changes:
                await self._reset_reminder_baseline(v.id)
            v = await self.bot.db.update_voyage(v.id, **changes)
            promoted = await self._promote_waitlist(v)
        await self.refresh(interaction.guild, v, new_image="image" in changes)
        await self.sync_event(interaction.guild, v)
        await self._announce_promotions(interaction.guild, v, promoted)
        stamp = int(datetime.fromisoformat(v.starts_at).timestamp())
        text = voice.say("voyage_edited", link=_link(v), when=f"<t:{stamp}:F>")
        if starts is not None:
            text += "\n" + self.zone_note(tz, whose, starts)
        await interaction.followup.send(text, ephemeral=True)

    async def _reset_reminder_baseline(self, voyage_id: int) -> None:
        # created_at is the "don't fire reminders due before this" line; moving it to now stops an edit
        # from setting off a burst of reminders that were already past.
        await self.bot.db.conn.execute("UPDATE voyages SET created_at = ? WHERE id = ?", (iso(now_utc()), voyage_id))
        await self.bot.db.conn.commit()

    @app_commands.command(name="cancel", description="Cancel a voyage you organized")
    @app_commands.describe(voyage="Which voyage", whole_series="For a repeating voyage: stop all future ones too")
    async def cancel(self, interaction: discord.Interaction, voyage: str, whole_series: bool = False) -> None:
        v = await self._fetch_manageable(interaction, voyage)
        if v is None:
            return
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            current = await self.bot.db.get_voyage(v.id)
            if current is None or current.status != "scheduled":  # it started meanwhile
                await interaction.followup.send(voice.say("voyage_over"), ephemeral=True)
                return
            v = await self.bot.db.update_voyage(v.id, status="cancelled")
        await self.refresh(interaction.guild, v)
        await self.sync_event(interaction.guild, v, "cancel")
        rsvps = await self.bot.db.rsvps(v.id)
        people = rsvps.aboard + rsvps.maybe + rsvps.waitlist
        channel = interaction.guild.get_channel(v.channel_id)
        if channel is not None and people:
            line = voice.say("voyage_cancelled", title=v.title, names="{names}")
            try:
                await send_pinging(channel, lambda names: line.replace("{names}", names), people)
            except discord.HTTPException as e:
                log.warning("Couldn't announce the cancellation of voyage %s: %s", v.id, e)
        if v.repeat != "none" and not whole_series:
            await self.schedule_next(interaction.guild, v)
        await interaction.followup.send(voice.say("voyage_cancel_done"), ephemeral=True)

    edit.autocomplete("voyage")(_manageable)
    cancel.autocomplete("voyage")(_manageable)

    @app_commands.command(name="list", description="Upcoming voyages")
    async def list_voyages(self, interaction: discord.Interaction) -> None:
        upcoming = await self.bot.db.voyages_with_status("scheduled", "started", guild_id=interaction.guild_id)
        if not upcoming:
            await interaction.response.send_message(voice.say("voyage_none_upcoming"), ephemeral=True)
            return
        lines = [voice.say("voyage_list_header")]
        for v in upcoming[:15]:
            stamp = int(datetime.fromisoformat(v.starts_at).timestamp())
            rs = await self.bot.db.rsvps(v.id)
            seats = f"{len(rs.aboard)}/{v.capacity}" if v.capacity else str(len(rs.aboard))
            state = " (under way)" if v.status == "started" else ""
            lines.append(f"- <t:{stamp}:f> **{v.title}**{state}, {seats} aboard {_link(v)}")
        await interaction.response.send_message("\n".join(lines)[:1990], ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())

    # ------------------------------------------------------------ RSVP buttons
    async def on_button(self, interaction: discord.Interaction, action: str, voyage_id: int) -> None:
        user = interaction.user
        promoted: list[int] = []
        async with self.lock:
            v = await self.bot.db.get_voyage(voyage_id)
            if v is None or v.status != "scheduled":
                reply, v = voice.say("voyage_over"), None
            else:
                rsvps = await self.bot.db.rsvps(v.id)
                current = rsvps.of(user.id)
                if current == action or (action == "aboard" and current == "waitlist"):
                    await self.bot.db.set_rsvp(v.id, user.id, None, iso(now_utc()))  # pressing again clears it
                    reply = voice.say("voyage_removed")
                else:
                    landed = placement(action, rsvps, v.capacity)
                    await self.bot.db.set_rsvp(v.id, user.id, landed, iso(now_utc()))
                    reply = voice.say(f"voyage_{landed}", title=v.title)
                if current == "aboard":
                    promoted = await self._promote_waitlist(v)
        try:
            await interaction.response.send_message(reply, ephemeral=True)
        except discord.HTTPException as e:
            log.warning("Couldn't answer a voyage button press: %s", e)
        if v is not None:
            await self.refresh(interaction.guild, v)
            await self._announce_promotions(interaction.guild, v, promoted)

    async def _promote_waitlist(self, v: Voyage) -> list[int]:
        """Move people off the waitlist while there are free seats. Call with the lock held."""
        rsvps = await self.bot.db.rsvps(v.id)
        promoted = []
        while rsvps.waitlist and (v.capacity is None or len(rsvps.aboard) < v.capacity):
            uid = rsvps.waitlist.pop(0)
            await self.bot.db.set_rsvp(v.id, uid, "aboard", iso(now_utc()))
            rsvps.aboard.append(uid)
            promoted.append(uid)
        return promoted

    async def _announce_promotions(self, guild, v: Voyage, promoted: list[int]) -> None:
        if not promoted or guild is None:
            return
        channel = guild.get_channel(v.channel_id)
        if channel is None:
            return
        line = voice.say("voyage_promoted", names="{names}", title=v.title)
        try:
            await send_pinging(channel, lambda names: line.replace("{names}", names), promoted)
        except discord.HTTPException as e:
            log.warning("Couldn't announce waitlist promotions for voyage %s: %s", v.id, e)

    # ------------------------------------------------------------ the clock: reminders, starts and a sweep
    @tasks.loop(minutes=1)
    async def clock(self) -> None:
        try:
            scheduled = await self.bot.db.voyages_with_status("scheduled")
            self.bot.gauge("voyages_scheduled", len(scheduled))
            now = now_utc()
            for v in scheduled:
                guild = self.bot.get_guild(v.guild_id)
                if guild is None:
                    continue
                try:
                    await self.tick(guild, v.id, now)
                except Exception as e:
                    log.exception("Voyage clock failed for voyage %s", v.id)
                    if self.bot.telemetry is not None:
                        self.bot.telemetry.error(e, command="voyage-clock")
            for v in await self.bot.db.voyages_with_status("started"):
                guild = self.bot.get_guild(v.guild_id)
                if guild is None:
                    continue
                try:
                    await self.sweep(guild, v)
                except Exception as e:
                    log.exception("Voyage sweep failed for voyage %s", v.id)
                    if self.bot.telemetry is not None:
                        self.bot.telemetry.error(e, command="voyage-clock")
        except Exception as e:
            log.exception("Voyage clock failed")
            if self.bot.telemetry is not None:
                self.bot.telemetry.error(e, command="voyage-clock")

    @clock.before_loop
    async def _wait_until_ready(self) -> None:
        await self.bot.wait_until_ready()

    async def tick(self, guild: discord.Guild, voyage_id: int, now: datetime) -> None:
        """Send a due reminder, or start the voyage. Reads the voyage fresh under the lock, so an edit or
        cancel that just happened is always respected."""
        async with self.lock:
            v = await self.bot.db.get_voyage(voyage_id)
            if v is None or v.status != "scheduled":
                return
            starts = datetime.fromisoformat(v.starts_at)
            if now >= starts:
                starting = True
            else:
                starting = False
                created = datetime.fromisoformat(v.created_at)
                skipped = overdue_reminders(starts, created, v.reminder_minutes, v.sent_minutes, now)
                due = due_reminder(starts, created, v.reminder_minutes, v.sent_minutes, now)
                if due is None and not skipped:
                    return
                # A reminder due now makes any earlier (longer) ones that never went out pointless.
                sent = set(v.sent_minutes) | set(skipped)
                if due is not None:
                    sent |= {m for m in v.reminder_minutes if m >= due}
                v = await self.bot.db.update_voyage(v.id, reminders_sent=",".join(str(m) for m in sorted(sent)))
                if due is None:
                    return
                rsvps = await self.bot.db.rsvps(v.id)
        if starting:
            await self.start(guild, v, now, late=now - starts > LATE_START_LIMIT)
            return
        people = rsvps.aboard + rsvps.maybe
        channel = guild.get_channel(v.channel_id)
        role = await self.game_role(guild, v) if v.ping_role == "reminders" else None
        if channel is None or not (people or role):
            return
        line = voice.say("voyage_reminder", title=v.title, when=f"<t:{int(starts.timestamp())}:R>",
                         names="{names}", link=_link(v))
        await send_pinging(channel, lambda names: line.replace("{names}", names or "crew"), people, role=role)

    async def start(self, guild: discord.Guild, v: Voyage, now: datetime | None = None, late: bool = False) -> None:
        now = now or now_utc()
        async with self.lock:
            v = await self.bot.db.get_voyage(v.id)
            if v is None or v.status != "scheduled" or now < datetime.fromisoformat(v.starts_at):
                return
            v = await self.bot.db.update_voyage(v.id, status="ended" if late else "started")
        rsvps = await self.bot.db.rsvps(v.id)
        if v.repeat != "none":
            await self.schedule_next(guild, v)
        if late:  # PlunderBot was down through the start; don't open a voice channel hours late
            await self.refresh(guild, v)
            await self.sync_event(guild, v, "end")
            return
        await self.sync_event(guild, v, "start")
        channel = guild.get_channel(v.channel_id)
        crew_cog = self.bot.get_cog("CrewCall")
        settings = await self.bot.db.get_settings(guild.id)
        # The crew card (and the "voice channel's ready" ping) go to the crew channel, e.g. #looking-for-group.
        crew_channel = (crew_cog.crew_channel(guild, settings) if crew_cog else None) or channel
        profile = games.get(v.game_key) or games.get("event")
        size_label = v.size_label or profile.default_size.label
        crew = None
        if crew_channel is not None and crew_cog is not None:
            try:
                crew = await crew_cog.launch_for_voyage(
                    guild, crew_channel, captain_id=v.organizer_id, profile=profile, size_label=size_label,
                    capacity=v.capacity or games.OPEN_CAPACITY, members=[v.organizer_id] + rsvps.aboard,
                    title=v.title, note=v.description[:200] if v.description else None, image=v.image)
            except Exception:
                log.exception("Couldn't launch the crew for voyage %s", v.id)
        if crew is None:  # no crew means nothing will ever end it, so end it now
            v = await self.bot.db.update_voyage(v.id, status="ended")
            await self.refresh(guild, v)
            await self.sync_event(guild, v, "end")
            return
        v = await self.bot.db.update_voyage(v.id, crew_id=crew.id)
        await self.refresh(guild, v)
        role = await self.game_role(guild, v) if v.ping_role == "reminders" else None
        if role is not None and crew.voice_channel_id:
            try:
                await crew_channel.send(voice.say("voyage_sailing_role", role=role.mention, title=v.title,
                                                  channel=f"<#{crew.voice_channel_id}>"),
                                        allowed_mentions=discord.AllowedMentions(everyone=False, users=False,
                                                                                 roles=[role]))
            except discord.HTTPException as e:
                log.warning("Couldn't tag the game role for voyage %s: %s", v.id, e)
        maybes = [u for u in rsvps.maybe if u not in rsvps.aboard]
        if channel is not None and maybes and crew.voice_channel_id:
            line = voice.say("voyage_starting_maybe", names="{names}", title=v.title,
                             channel=f"<#{crew.voice_channel_id}>")
            try:
                await send_pinging(channel, lambda names: line.replace("{names}", names), maybes)
            except discord.HTTPException as e:
                log.warning("Couldn't ping the maybes for voyage %s: %s", v.id, e)

    async def sweep(self, guild: discord.Guild, v: Voyage) -> None:
        """Repair a started voyage whose follow-up was interrupted (a restart, a failure): end it if its
        crew is gone, and make sure a repeating series still has its next voyage."""
        crew = await self.bot.db.get_crew(v.crew_id) if v.crew_id else None
        if v.repeat != "none":
            await self.schedule_next(guild, v)  # no-op when the series already has one scheduled
        started = datetime.fromisoformat(v.starts_at)
        if crew is None and now_utc() - started < timedelta(minutes=5):
            return  # still launching
        if crew is None or not crew.active:
            async with self.lock:
                v = await self.bot.db.get_voyage(v.id)
                if v is None or v.status != "started":
                    return
                v = await self.bot.db.update_voyage(v.id, status="ended")
            await self.refresh(guild, v)
            await self.sync_event(guild, v, "end")

    async def schedule_next(self, guild: discord.Guild, v: Voyage) -> Voyage | None:
        """Post the next voyage in v's series, unless the series already has one waiting."""
        series = v.series_id or v.id
        async with self.lock:
            waiting = [x for x in await self.bot.db.voyages_with_status("scheduled", guild_id=guild.id)
                       if (x.series_id or x.id) == series]
            if waiting:
                return None
            tz = await self.tz(guild.id)
            first = await self.bot.db.get_voyage(series)
            anchor = datetime.fromisoformat(first.starts_at).astimezone(tz).day if first else None
            nxt = next_occurrence(datetime.fromisoformat(v.starts_at), v.repeat, tz, anchor)
            if nxt is None:
                return None
            while nxt <= now_utc():  # skip occurrences missed while offline
                nxt = next_occurrence(nxt, v.repeat, tz, anchor)
            new = await self.bot.db.create_voyage(
                guild_id=v.guild_id, channel_id=v.channel_id, organizer_id=v.organizer_id, title=v.title,
                description=v.description, game_key=v.game_key, size_label=v.size_label, capacity=v.capacity,
                starts_at=iso(nxt), duration_min=v.duration_min, reminders=v.reminders, repeat=v.repeat,
                series_id=series, created_at=iso(now_utc()), image=v.image, ping_role=v.ping_role)
            await self.bot.db.set_rsvp(new.id, v.organizer_id, "aboard", iso(now_utc()))
        try:
            return await self.post(guild, new, announce_role=False)
        except (discord.HTTPException, LookupError) as e:
            log.warning("Couldn't post the next voyage in series %s: %s", series, e)
            return new

    # ------------------------------------------------------------ when the crew's done, so is the voyage
    async def on_crew_ended(self, guild: discord.Guild | None, crew) -> None:
        v = await self.bot.db.voyage_by_crew(crew.id)
        if v is None or v.status != "started":
            return
        v = await self.bot.db.update_voyage(v.id, status="ended")
        if guild is not None:
            await self.refresh(guild, v)
            await self.sync_event(guild, v, "end")


async def setup(bot) -> None:
    await bot.add_cog(Voyages(bot))
