"""The Ship's Log: every week (Sunday evening by default) PlunderBot posts a roundup in
#announcements: crews that sailed, voyages sailed and coming up, birthdays, new pirates, the
liveliest game threads and the week's game news. Settings live under /admin shipslog.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks

from .. import voice
from ..birthday_logic import upcoming, zone
from ..crew_logic import iso
from ..shipslog_logic import WeekStats, is_due, render

log = logging.getLogger("plunderbot.shipslog")
KEEP_ACTIVITY_DAYS = 60


class ShipsLog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._forum_ids: dict[int, int | None] = {}

    async def cog_load(self) -> None:
        self.clock.start()

    async def cog_unload(self) -> None:
        self.clock.cancel()

    # ------------------------------------------------------------ counting game-thread chatter
    async def forum_id(self, guild_id: int) -> int | None:
        if guild_id not in self._forum_ids:
            self._forum_ids[guild_id] = (await self.bot.db.get_settings(guild_id)).forum_channel_id
        return self._forum_ids[guild_id]

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or not isinstance(message.channel, discord.Thread):
            return
        forum = await self.forum_id(message.guild.id)
        if forum is None or message.channel.parent_id != forum:
            return
        day = message.created_at.astimezone(timezone.utc).date().isoformat()
        await self.bot.db.count_thread_message(message.guild.id, day, message.channel.id)

    # ------------------------------------------------------------ the weekly post
    @tasks.loop(minutes=5)
    async def clock(self) -> None:
        self._forum_ids.clear()  # pick up forum changes
        now = datetime.now(timezone.utc)
        for s in await self.bot.db.all_settings():
            if not s.shipslog_channel_id:
                continue
            guild = self.bot.get_guild(s.guild_id)
            if guild is None:
                continue
            local = now.astimezone(zone(s.timezone, self.bot.config.default_timezone))
            if not is_due(local, s.shipslog_weekday, s.shipslog_hour, s.shipslog_last):
                continue
            await self.bot.db.update_settings(guild.id, shipslog_last=local.date().isoformat())
            try:
                await self.post(guild, now)
            except Exception:
                log.exception("Ship's Log failed in %s", guild.id)
        try:
            cutoff = (now - timedelta(days=KEEP_ACTIVITY_DAYS)).date().isoformat()
            await self.bot.db.prune_thread_activity(cutoff)
        except Exception:
            log.exception("Couldn't tidy old thread counts")

    @clock.before_loop
    async def _wait_until_ready(self) -> None:
        await self.bot.wait_until_ready()

    async def gather(self, guild: discord.Guild, now: datetime) -> WeekStats:
        s = await self.bot.db.get_settings(guild.id)
        tz = zone(s.timezone, self.bot.config.default_timezone)
        start, ahead = now - timedelta(days=7), now + timedelta(days=7)
        stats = WeekStats(week_start=start.astimezone(tz).date())
        stats.crews = await self.bot.db.crews_sailed_between(guild.id, iso(start), iso(now))
        stats.voyages_done = [v for v in await self.bot.db.voyages_starting_between(guild.id, iso(start), iso(now))
                              if v.status in ("started", "ended")]
        stats.voyages_ahead = [v for v in await self.bot.db.voyages_starting_between(guild.id, iso(now), iso(ahead))
                               if v.status == "scheduled"]
        today = now.astimezone(tz).date()
        stats.birthdays = [(uid, d) for uid, d in upcoming(await self.bot.db.birthdays(guild.id), today, limit=50)
                           if (d - today).days < 7 and guild.get_member(uid) is not None]
        pending = s.pending_role_id
        stats.newcomers = [m.id for m in guild.members
                           if not m.bot and m.joined_at and m.joined_at >= start
                           and not (pending and m.get_role(pending))]
        stats.threads = {tid: n for tid, n in (await self.bot.db.thread_activity(
            guild.id, start.date().isoformat(), now.date().isoformat())).items()
            if guild.get_channel_or_thread(tid) is not None}
        stats.news = await self.bot.db.news_posted_between(guild.id, iso(start), iso(now))
        return stats

    async def build(self, guild: discord.Guild, now: datetime | None = None) -> discord.Embed:
        stats = await self.gather(guild, now or datetime.now(timezone.utc))
        intro = voice.say("shipslog_quiet") if stats.quiet else voice.say("shipslog_intro")
        return render(stats, intro)

    async def post(self, guild: discord.Guild, now: datetime | None = None) -> discord.Message | None:
        s = await self.bot.db.get_settings(guild.id)
        channel = guild.get_channel(s.shipslog_channel_id) if s.shipslog_channel_id else None
        if channel is None:
            log.warning("Ship's Log channel is gone in %s", guild.id)
            return None
        embed = await self.build(guild, now)
        return await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot) -> None:
    await bot.add_cog(ShipsLog(bot))
