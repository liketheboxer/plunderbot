"""The Crow's Nest: official news and patch notes for each game, posted in its forum thread.

Every 30 minutes PlunderBot reads each game's source (its Steam news, or an RSS/Atom feed set
with /admin crowsnest source) and posts anything new in that game's thread in #game-discussion.
The first look at a source only takes note of what's there, so turning it on doesn't flood the
threads with old posts. Off until /admin crowsnest on.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands, tasks

from .. import games, voice
from ..crew_logic import iso
from ..news_logic import NewsItem, new_items, parse_feed, parse_steam, source_for, steam_url

log = logging.getLogger("plunderbot.crowsnest")
USER_AGENT = "PlunderBot (Discord bot for Brimstone Hill Fortress)"


class CrowsNest(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session: aiohttp.ClientSession | None = None
        self.lock = asyncio.Lock()

    async def cog_load(self) -> None:
        self.watch.start()

    async def cog_unload(self) -> None:
        self.watch.cancel()
        if self.session is not None:
            await self.session.close()

    async def http(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),
                                                 headers={"User-Agent": USER_AGENT})
        return self.session

    async def fetch(self, source: tuple[str, str]) -> list[NewsItem]:
        kind, value = source
        session = await self.http()
        url = steam_url(value) if kind == "steam" else value
        async with session.get(url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"{url.split('?')[0]} answered {resp.status}")
            if kind == "steam":
                return parse_steam(await resp.json(content_type=None))
            return parse_feed(await resp.text())

    # ------------------------------------------------------------ the watch
    @tasks.loop(minutes=30)
    async def watch(self) -> None:
        for s in await self.bot.db.all_settings():
            if not s.crowsnest_enabled:
                continue
            guild = self.bot.get_guild(s.guild_id)
            if guild is None:
                continue
            try:
                await self.check(guild)
            except Exception:
                log.exception("Crow's Nest failed in %s", s.guild_id)

    @watch.before_loop
    async def _wait_until_ready(self) -> None:
        await self.bot.wait_until_ready()

    async def entries(self, guild: discord.Guild) -> list[dict]:
        board = self.bot.get_cog("Noticeboard")
        return await board.game_entries(guild) if board else []

    async def check(self, guild: discord.Guild) -> dict[str, str]:
        """Look for news for every game. Returns a note per game, for /admin crowsnest check."""
        notes: dict[str, str] = {}
        async with self.lock:
            overrides = await self.bot.db.news_sources(guild.id)
            for e in await self.entries(guild):
                source = source_for(e["key"], overrides)
                if source is None:
                    notes[e["key"]] = "no news source"
                    continue
                if e.get("thread") is None:
                    notes[e["key"]] = "no forum thread"
                    continue
                try:
                    items = await self.fetch(source)
                except Exception as err:
                    log.warning("Couldn't read news for %s: %s", e["key"], err)
                    notes[e["key"]] = f"couldn't read its news ({err})"
                    continue
                seen = await self.bot.db.news_seen_ids(guild.id, e["key"])
                now = iso(datetime.now(timezone.utc))
                if not seen:  # first look: note what's there without posting it
                    for item in items:
                        await self.bot.db.mark_news_seen(guild.id, e["key"], item.id, now, False, item.title, item.url)
                    notes[e["key"]] = f"watching ({len(items)} older post(s) skipped)"
                    continue
                posted = 0
                for item in new_items(items, seen):
                    try:
                        await self.post(e, item)
                        posted += 1
                        await self.bot.db.mark_news_seen(guild.id, e["key"], item.id, now, True, item.title, item.url)
                    except discord.HTTPException as err:
                        log.warning("Couldn't post news in thread %s: %s", e["thread"].id, err)
                        notes[e["key"]] = f"couldn't post in its thread ({err.status})"
                        break
                notes.setdefault(e["key"], f"{posted} new post(s)" if posted else "nothing new")
        return notes

    def embed(self, game_name: str, item: NewsItem) -> discord.Embed:
        e = discord.Embed(title=item.title[:256], url=item.url or None, description=item.summary or None,
                          colour=discord.Colour(0x1F8B8B), timestamp=item.published)
        if item.image:
            e.set_image(url=item.image)
        e.set_footer(text=f"{game_name} · official news")
        return e

    async def post(self, entry: dict, item: NewsItem) -> None:
        await entry["thread"].send(voice.say("crowsnest_post", game=entry["name"]),
                                   embed=self.embed(entry["name"], item),
                                   allowed_mentions=discord.AllowedMentions.none())

    async def latest(self, guild: discord.Guild, game_key: str) -> NewsItem | None:
        overrides = await self.bot.db.news_sources(guild.id)
        source = source_for(game_key, overrides)
        if source is None:
            return None
        items = await self.fetch(source)
        items.sort(key=lambda i: i.published or datetime.min.replace(tzinfo=timezone.utc))
        return items[-1] if items else None


async def setup(bot) -> None:
    await bot.add_cog(CrowsNest(bot))
