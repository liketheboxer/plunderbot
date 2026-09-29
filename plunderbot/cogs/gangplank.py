"""Gangplank: the airlock in #introductions.

New members get the Pending role and a welcome asking them to introduce themselves. A Harbormaster
reacts to the introduction with Yar (Pending comes off, welcome aboard) or Nar (kicked). Newcomers
who never say anything are reminded, then kicked, on the schedule in /admin gangplank timing.
Off until a Quartermaster runs /admin gangplank on.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import discord
from discord.ext import commands, tasks

from .. import voice
from ..crew_logic import iso, now_utc
from ..db import Boarding, GuildSettings
from ..gangplank_logic import deadline, due, verdict

log = logging.getLogger("plunderbot.gangplank")
HISTORY_SCAN = 1000  # messages of #introductions checked when catching up on existing Pending members


def _channel_ref(channel_id: int | None, fallback: str) -> str:
    return f"<#{channel_id}>" if channel_id else fallback


def _ts(dt: datetime, style: str = "R") -> str:
    return f"<t:{int(dt.timestamp())}:{style}>"


class Gangplank(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()

    async def cog_load(self) -> None:
        self.upkeep.start()

    async def cog_unload(self) -> None:
        self.upkeep.cancel()

    # ------------------------------------------------------------ helpers
    async def settings_for(self, guild_id: int) -> GuildSettings | None:
        s = await self.bot.db.get_settings(guild_id)
        return s if s.gangplank_enabled else None

    async def alert(self, guild: discord.Guild, s: GuildSettings, text: str) -> None:
        """A plain-English note for the Harbormasters, if an alert channel is set."""
        channel = guild.get_channel(s.gangplank_alert_channel_id) if s.gangplank_alert_channel_id else None
        if channel is None:
            return
        try:
            await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as e:
            log.warning("Couldn't post a gangplank alert in %s: %s", channel.id, e)

    @staticmethod
    def is_pending(member: discord.Member, s: GuildSettings) -> bool:
        return s.pending_role_id is not None and member.get_role(s.pending_role_id) is not None

    @staticmethod
    def is_harbormaster(member: discord.Member | None, s: GuildSettings) -> bool:
        return (member is not None and not member.bot and s.harbormaster_role_id is not None
                and member.get_role(s.harbormaster_role_id) is not None)

    # ------------------------------------------------------------ arrivals and departures
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        s = await self.settings_for(member.guild.id)
        if s is None:
            return
        await self.welcome(member, s)

    async def welcome(self, member: discord.Member, s: GuildSettings) -> None:
        guild = member.guild
        role = guild.get_role(s.pending_role_id) if s.pending_role_id else None
        if role is not None and role not in member.roles:
            try:
                await member.add_roles(role, reason="Gangplank: waiting to be let aboard")
            except discord.HTTPException as e:
                log.warning("Couldn't give %s the Pending role: %s", member.id, e)
                await self.alert(guild, s, f"I couldn't give {member.mention} the Pending role ({e.status}). "
                                           "Check that PlunderBot's role sits above it and has Manage Roles.")
        prompt_id = None
        channel = guild.get_channel(s.intro_channel_id) if s.intro_channel_id else None
        if channel is not None:
            text = voice.say("gangplank_welcome", server=guild.name, member=member.mention,
                             rules=_channel_ref(s.rules_channel_id, "the rules channel"))
            try:
                msg = await channel.send(text, allowed_mentions=discord.AllowedMentions(users=[member]))
                prompt_id = msg.id
            except discord.HTTPException as e:
                log.warning("Couldn't post the welcome for %s: %s", member.id, e)
        async with self.lock:
            await self.bot.db.add_boarding(guild.id, member.id, iso(now_utc()), prompt_id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        async with self.lock:
            await self.bot.db.remove_boarding(member.guild.id, member.id)

    # ------------------------------------------------------------ introductions
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or not isinstance(message.author, discord.Member):
            return
        s = await self.settings_for(message.guild.id)
        if s is None or message.channel.id != s.intro_channel_id or not self.is_pending(message.author, s):
            return
        async with self.lock:
            row = await self.bot.db.get_boarding(message.guild.id, message.author.id)
            if row is not None and row.responded_at is not None:
                return
            now = iso(now_utc())
            if row is None:
                await self.bot.db.add_boarding(message.guild.id, message.author.id, now, None, now)
            else:
                await self.bot.db.update_boarding(message.guild.id, message.author.id, responded_at=now)
        await self.alert(message.guild, s, f"{message.author.mention} introduced themselves: {message.jump_url} "
                                           "Harbormasters, react Yar to let them aboard or Nar to turn them away.")

    # ------------------------------------------------------------ Yar and Nar
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None:
            return
        s = await self.settings_for(payload.guild_id)
        if s is None or payload.channel_id != s.intro_channel_id:
            return
        if not self.is_harbormaster(payload.member, s):
            return
        decision = verdict(payload.emoji.id, payload.emoji.name, s.approve_emoji, s.reject_emoji)
        if decision is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        target_id = None
        row = await self.bot.db.boarding_by_prompt(guild.id, payload.message_id)
        if row is not None:
            target_id = row.user_id
        elif payload.message_author_id is not None:
            target_id = payload.message_author_id
        if target_id is None or target_id == payload.user_id:
            return
        await self.decide(guild, s, target_id, decision, payload.member)

    async def decide(self, guild: discord.Guild, s: GuildSettings, user_id: int, decision: str,
                     by: discord.Member) -> str:
        """Let someone aboard or turn them away. Returns what happened, for logs and tests."""
        async with self.lock:
            member = guild.get_member(user_id)
            row = await self.bot.db.get_boarding(guild.id, user_id)
            if member is None:
                if row is not None:
                    await self.bot.db.remove_boarding(guild.id, user_id)
                return "gone"
            if not self.is_pending(member, s):
                if row is not None:
                    await self.bot.db.remove_boarding(guild.id, user_id)
                return "not_pending"  # already aboard; a Yar on an old intro changes nothing
            if decision == "approve":
                try:
                    await member.remove_roles(guild.get_role(s.pending_role_id),
                                              reason=f"Gangplank: let aboard by {by}")
                except discord.HTTPException as e:
                    await self.alert(guild, s, f"I couldn't take Pending off {member.mention} ({e.status}). "
                                               "Check PlunderBot's role position and Manage Roles.")
                    return "failed"
                await self.bot.db.remove_boarding(guild.id, user_id)
            else:
                try:
                    await member.kick(reason=f"Gangplank: turned away by {by}")
                except discord.HTTPException as e:
                    await self.alert(guild, s, f"I couldn't kick {member.mention} ({e.status}). "
                                               "PlunderBot needs Kick Members and a role above theirs.")
                    return "failed"
                await self.bot.db.remove_boarding(guild.id, user_id)
        if decision == "approve":
            channel = guild.get_channel(s.intro_channel_id)
            if channel is not None:
                items = await self.onboarding_items(guild)
                text = voice.say("gangplank_approved_buttons" if items else "gangplank_approved",
                                 member=member.mention,
                                 orientation=_channel_ref(s.orientation_channel_id, "the orientation channel"))
                extra = {}
                if items:
                    view = discord.ui.View(timeout=None)
                    for item in items[:25]:
                        view.add_item(item)
                    extra["view"] = view
                try:
                    await channel.send(text, allowed_mentions=discord.AllowedMentions(users=[member]), **extra)
                except discord.HTTPException as e:
                    log.warning("Couldn't post the welcome-aboard for %s: %s", member.id, e)
            await self.alert(guild, s, f"{member.mention} was let aboard by {by.mention}.")
            return "approved"
        await self.alert(guild, s, f"{member} ({member.id}) was turned away by {by.mention}.")
        return "rejected"

    async def onboarding_items(self, guild: discord.Guild) -> list:
        """Role-menu and follow-a-game buttons for the welcome-aboard message."""
        items = []
        for name in ("Colours", "Noticeboard"):
            cog = self.bot.get_cog(name)
            if cog is not None:
                try:
                    items.extend(await cog.onboarding_items(guild))
                except Exception:
                    log.exception("Couldn't gather onboarding buttons from %s", name)
        return items

    # ------------------------------------------------------------ the clock
    @tasks.loop(minutes=5)
    async def upkeep(self) -> None:
        waiting = 0
        for s in await self.bot.db.all_settings():
            if not s.gangplank_enabled:
                continue
            guild = self.bot.get_guild(s.guild_id)
            if guild is None:
                continue
            try:
                waiting += await self.tick(guild, s, now_utc())
            except Exception:
                log.exception("Gangplank upkeep failed in %s", s.guild_id)
        self.bot.gauge("gangplank_waiting", waiting)

    @upkeep.before_loop
    async def _wait_until_ready(self) -> None:
        await self.bot.wait_until_ready()

    async def catch_up(self, guild: discord.Guild, s: GuildSettings, now: datetime) -> int:
        """Start the clock for anyone wearing Pending who isn't being tracked yet (e.g. they joined
        before Gangplank was on). Their clock starts now; anyone who has already posted in
        #introductions counts as having introduced themselves."""
        role = guild.get_role(s.pending_role_id) if s.pending_role_id else None
        if role is None:
            return 0
        tracked = {b.user_id for b in await self.bot.db.boardings(guild.id)}
        untracked = [m for m in role.members if not m.bot and m.id not in tracked]
        if not untracked:
            return 0
        spoke: set[int] = set()
        channel = guild.get_channel(s.intro_channel_id) if s.intro_channel_id else None
        if channel is not None:
            try:
                async for msg in channel.history(limit=HISTORY_SCAN):
                    spoke.add(msg.author.id)
            except discord.HTTPException as e:
                log.warning("Couldn't read #introductions history: %s", e)
                spoke = {m.id for m in untracked}  # unsure, so don't start anyone's kick clock
        async with self.lock:
            for m in untracked:
                await self.bot.db.add_boarding(guild.id, m.id, iso(now), None,
                                               iso(now) if m.id in spoke else None)
        return len(untracked)

    async def tick(self, guild: discord.Guild, s: GuildSettings, now: datetime) -> int:
        """Remind, kick and tidy up. Returns how many are still waiting."""
        await self.catch_up(guild, s, now)
        waiting = 0
        for row in await self.bot.db.boardings(guild.id):
            member = guild.get_member(row.user_id)
            if member is None or not self.is_pending(member, s):
                async with self.lock:
                    await self.bot.db.remove_boarding(guild.id, row.user_id)  # left, or let aboard by hand
                continue
            action = due(row.joined_at, row.responded_at, row.reminded_at, now,
                         s.gangplank_remind_days, s.gangplank_kick_days)
            if action == "remind":
                await self.remind(guild, s, member, row)
            elif action == "kick":
                if await self.kick_silent(guild, s, member):
                    continue
            waiting += 1
        return waiting

    async def remind(self, guild: discord.Guild, s: GuildSettings, member: discord.Member, row: Boarding) -> None:
        channel = guild.get_channel(s.intro_channel_id) if s.intro_channel_id else None
        if channel is not None:
            text = voice.say("gangplank_reminder", member=member.mention,
                             deadline=_ts(deadline(row.joined_at, s.gangplank_kick_days)))
            try:
                await channel.send(text, allowed_mentions=discord.AllowedMentions(users=[member]))
            except discord.HTTPException as e:
                log.warning("Couldn't remind %s: %s", member.id, e)
        async with self.lock:
            await self.bot.db.update_boarding(guild.id, member.id, reminded_at=iso(now_utc()))

    async def kick_silent(self, guild: discord.Guild, s: GuildSettings, member: discord.Member) -> bool:
        """Kick someone who never introduced themselves. Returns True if they're gone."""
        try:
            await member.send(voice.say("gangplank_kick_dm", server=guild.name, days=s.gangplank_kick_days))
        except discord.HTTPException:
            pass  # DMs closed; the kick goes ahead
        try:
            await member.kick(reason=f"Gangplank: no introduction within {s.gangplank_kick_days} days")
        except discord.HTTPException as e:
            log.warning("Couldn't kick %s: %s", member.id, e)
            await self.alert(guild, s, f"I couldn't kick {member.mention} after {s.gangplank_kick_days} days "
                                       f"without an introduction ({e.status}).")
            return False
        async with self.lock:
            await self.bot.db.remove_boarding(guild.id, member.id)
        await self.alert(guild, s, f"{member} ({member.id}) never introduced themselves, so I raised the "
                                   f"gangplank after {s.gangplank_kick_days} days.")
        return True


async def setup(bot) -> None:
    await bot.add_cog(Gangplank(bot))
