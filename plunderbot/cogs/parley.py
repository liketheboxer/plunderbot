"""Parley: @mention PlunderBot (or reply to it) and it answers, in character.

Claude (Haiku) does the talking and decides which tools to use: server facts come from
PlunderBot's own database, current facts from a Kagi web search. Slash commands never use AI.
Limits: a monthly dollar budget, replies per member per day, and web searches per day.
Off until /admin parley on, and only in channels everyone can see (staff channels are left out).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands

from .. import games, voice
from ..ai import Claude, Kagi
from ..birthday_logic import upcoming, zone
from ..discord_util import addressed_to
from ..parley_logic import (COMMANDS_HELP, COOLDOWN_SECONDS, MAX_ROUNDS, TOOLS, build_messages, cost, refusal,
                            reply_text, safe, strip_bot_mention, system_prompt)
from ..parley_actions import ACTION_NAMES, ACTION_TOOLS, act
from ..voyage_logic import zone_from_name, zone_label

log = logging.getLogger("plunderbot.parley")


class Parley(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        cfg = bot.config
        self.claude = Claude(cfg.anthropic_api_key, cfg.parley_model) if cfg.anthropic_api_key else None
        self.kagi = Kagi(cfg.kagi_api_key) if cfg.kagi_api_key else None
        self.last_asked: dict[int, float] = {}
        self.lock = asyncio.Lock()  # one conversation at a time keeps spending predictable
        self._background: set = set()

    async def cog_unload(self) -> None:
        for client in (self.claude, self.kagi):
            if client is not None:
                await client.close()

    # ------------------------------------------------------------ when to answer
    def addressed(self, message: discord.Message) -> bool:
        me = self.bot.user
        return me is not None and addressed_to(me.id, message)

    @staticmethod
    def public_channel(guild, channel_id: int | None) -> bool:
        """Whether everyone in the server can see a channel (1.4.1): Parley only repeats what's posted
        where anyone could read it, so a staff-only card or an unposted page stays private."""
        channel = guild.get_channel(channel_id) if channel_id else None
        base = getattr(channel, "parent", None) or channel
        try:
            return base is not None and base.permissions_for(guild.default_role).view_channel
        except (AttributeError, TypeError):
            return False

    async def allowed_here(self, message: discord.Message) -> bool:
        channel = message.channel
        base = channel.parent if isinstance(channel, discord.Thread) and channel.parent else channel
        off = await self.bot.db.parley_off_channels(message.guild.id)
        if channel.id in off or base.id in off:
            return False
        try:  # "public" means @everyone can see it; staff channels are left out
            return base.permissions_for(message.guild.default_role).view_channel
        except (AttributeError, TypeError):
            return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or not self.addressed(message):
            return
        ledger = self.bot.get_cog("ShipLedger")
        if ledger is not None and ledger.wants(message):
            return  # a Captain's Log screenshot: the Ship's Ledger reads it
        s = await self.bot.db.get_settings(message.guild.id)
        if not s.parley_enabled or self.claude is None:
            return
        if s.pending_role_id and isinstance(message.author, discord.Member) and message.author.get_role(s.pending_role_id):
            return  # newcomers on the gangplank talk to Harbormasters, not the butler
        if not await self.allowed_here(message):
            return
        now = time.monotonic()
        if now - self.last_asked.get(message.author.id, 0) < COOLDOWN_SECONDS:
            return
        self.last_asked[message.author.id] = now
        try:
            await self.answer(message, s)
        except Exception:
            log.exception("Parley failed")
            try:
                await message.reply(voice.say("parley_error"), mention_author=False,
                                    allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

    # ------------------------------------------------------------ answering
    def today(self, s) -> tuple[str, str, datetime]:
        tz = zone(s.timezone, self.bot.config.default_timezone)
        local = datetime.now(timezone.utc).astimezone(tz)
        return local.date().isoformat(), local.strftime("%Y-%m"), local

    async def answer(self, message: discord.Message, s) -> None:
        guild, author = message.guild, message.author
        day, month, local = self.today(s)
        spent, _ = await self.bot.db.parley_spend(guild.id, month)
        replies = await self.bot.db.parley_replies(guild.id, author.id, day)
        no = refusal(spent, s.parley_budget_cents / 100, replies, s.parley_daily)
        if no:
            await message.reply(voice.say("parley_broke" if no == "broke" else "parley_tired",
                                          daily=s.parley_daily),
                                mention_author=False, allowed_mentions=discord.AllowedMentions.none())
            return
        question = strip_bot_mention(message.content, self.bot.user.id)
        if not question:
            await message.reply(voice.say("parley_hello"), mention_author=False,
                                allowed_mentions=discord.AllowedMentions.none())
            return
        # counted before Claude is asked (1.4.1): deleting the question before the reply lands used to skip
        # the count, so the daily limit could be dodged
        await self.bot.db.add_parley_reply(guild.id, author.id, day)
        history = await self.history(message)
        saved = await self.bot.db.member_timezone(author.id)
        asker_zone = zone_label(zone_from_name(saved), local) if saved else ""
        lookups_left = (max(0, s.parley_kagi_daily - await self.bot.db.parley_lookups(guild.id, day))
                        if self.kagi else None)
        system = system_prompt(server=guild.name, now_local=local, zone_label=local.strftime("%Z"),
                               asker=author.display_name, asker_zone=asker_zone, lookups_left=lookups_left,
                               cusses=voice.CUSSES)
        messages = build_messages(history, question, author.display_name)
        async with message.channel.typing():
            text = await self.converse(guild, s, system, messages, day, month, author, message.channel)
        try:
            await message.reply(safe(text) or voice.say("parley_error"), mention_author=False,
                                allowed_mentions=discord.AllowedMentions.none())
        except discord.NotFound:       # they deleted the question: answer in the channel, saying whom to
            await message.channel.send(f"<@{author.id}> " + (safe(text) or voice.say("parley_error")),
                                       allowed_mentions=discord.AllowedMentions.none())

    async def converse(self, guild, s, system: str, messages: list[dict], day: str, month: str,
                       author=None, channel=None) -> str:
        tools = (TOOLS if self.kagi else [t for t in TOOLS if t["name"] != "search_web"]) + ACTION_TOOLS
        for round_ in range(MAX_ROUNDS + 1):
            last = round_ == MAX_ROUNDS
            async with self.lock:
                resp = await self.claude.create(system=system, messages=messages, tools=tools, allow_tools=not last)
                usage = resp.get("usage") or {}
                await self.bot.db.add_parley_spend(guild.id, month, cost(usage), usage.get("input_tokens", 0),
                                                   usage.get("output_tokens", 0))
            content = resp.get("content") or []
            if resp.get("stop_reason") != "tool_use":
                return reply_text(content)
            messages.append({"role": "assistant", "content": content})
            results = []
            for block in content:
                if block.get("type") != "tool_use":
                    continue
                try:
                    out = await self.run_tool(guild, s, block.get("name"), block.get("input") or {}, day,
                                              author, channel)
                except Exception as e:
                    log.warning("Parley tool %s failed: %s", block.get("name"), e, exc_info=True)
                    out = "That didn't work because of a problem inside PlunderBot; say so and suggest the slash command."
                results.append({"type": "tool_result", "tool_use_id": block.get("id"), "content": out[:6000]})
            messages.append({"role": "user", "content": results})
        return reply_text(content)

    async def history(self, message: discord.Message) -> list[tuple[str, str]]:
        """The reply chain above this message, oldest first, as (role, text)."""
        chain: list[tuple[str, str]] = []
        ref = message.reference
        me = self.bot.user.id
        for _ in range(6):
            if ref is None or ref.message_id is None:
                break
            prev = ref.resolved if isinstance(getattr(ref, "resolved", None), discord.Message) else None
            if prev is None:
                try:
                    prev = await message.channel.fetch_message(ref.message_id)
                except discord.HTTPException:
                    break
            role = "assistant" if prev.author.id == me else "user"
            text = strip_bot_mention(prev.content, me)
            chain.append((role, text if role == "assistant" else f"{prev.author.display_name}: {text}"))
            ref = prev.reference
        return list(reversed(chain))

    # ------------------------------------------------------------ tools
    async def game_activity(self, guild, now) -> str:
        rows = await game_activity_lines(self.bot.db, guild, now)
        lines = [f"- {n}: {c} crew(s) set sail with {p} different pirate(s) in the last 30 days, {f} follower(s)"
                 + (f", {v} voyage(s) planned" if v else "") for n, c, p, f, v in rows]
        return "Busiest first:\n" + "\n".join(lines)

    async def run_tool(self, guild: discord.Guild, s, name: str, args: dict, day: str, author=None,
                       channel=None) -> str:
        db = self.bot.db
        if name in ACTION_NAMES:
            return await act(self.bot, guild, author, channel, name, args)
        if name in ("play_music", "music_queue"):
            music = self.bot.get_cog("Music")
            if music is None:
                return "Music isn't running."
            if name == "music_queue":
                return music.summary(guild.id)
            if author is None:
                return "You can only queue music for someone who asked."
            query = " ".join(str(args.get("query") or "").split())[:200]
            if not query:
                return "Say what to play."
            ok, text, start = await music.enqueue(guild, author, channel, query, bool(args.get("next")))
            if ok and start:   # start playing without holding up the reply
                task = asyncio.create_task(music.advance(guild, music.players[guild.id]))
                self._background.add(task)
                task.add_done_callback(self._background.discard)
            return ("Done: " if ok else "It didn't work: ") + text
        now = datetime.now(timezone.utc)
        if name == "upcoming_voyages":
            from ..crew_logic import iso
            vs = [v for v in await db.voyages_starting_between(guild.id, iso(now), iso(now + timedelta(days=14)))
                  if v.status == "scheduled" and self.public_channel(guild, v.channel_id)]
            if not vs:
                return "No voyages scheduled in the next 14 days. Anyone can plan one with /voyage create."
            lines = []
            for v in vs[:15]:
                r = await db.rsvps(v.id)
                seats = f"{len(r.aboard)}/{v.capacity} aboard" if v.capacity else f"{len(r.aboard)} aboard"
                game = games.get(v.game_key).name if games.get(v.game_key) else "server event"
                link = f"https://discord.com/channels/{v.guild_id}/{v.channel_id}/{v.message_id}" if v.message_id else ""
                stamp = int(datetime.fromisoformat(v.starts_at).timestamp())
                lines.append(f"- #{v.id} {v.title} ({game}) at <t:{stamp}:F>, organized by <@{v.organizer_id}>, {seats} {link}")
            return "\n".join(lines)
        if name == "open_crews":
            crews = [c for c in await db.active_crews(guild.id) if self.public_channel(guild, c.channel_id)]
            if not crews:
                return "No crews are mustering or sailing right now. Start one with /crew start."
            lines = []
            for c in crews[:15]:
                g = games.get(c.game_key)
                link = f"https://discord.com/channels/{c.guild_id}/{c.channel_id}/{c.message_id}" if c.message_id else ""
                lines.append(f"- #{c.id} {g.name if g else c.game_key} {c.size_label}, captain <@{c.captain_id}>, "
                             f"{len(c.members)}/{c.capacity} aboard, {c.status} {link}")
            return "\n".join(lines)
        if name == "upcoming_birthdays":
            tz = zone(s.timezone, self.bot.config.default_timezone)
            today = now.astimezone(tz).date()
            soon = [(u, d) for u, d in upcoming(await db.birthdays(guild.id), today, limit=30)
                    if (d - today).days <= 30 and guild.get_member(u)]
            if not soon:
                return "No birthdays in the next 30 days. Members add theirs with /birthday set."
            return "\n".join(f"- {guild.get_member(u).display_name}: {d.strftime('%B')} {d.day}" for u, d in soon)
        if name == "server_games":
            board = self.bot.get_cog("Noticeboard")
            entries = await board.game_entries(guild, with_threads=True) if board else []
            lines = [f"- {e['name']}" + (f", thread <#{e['thread_id']}>" if e.get("thread_id") else "")
                     + (" (has a ping role)" if e.get("role_id") else "") for e in entries]
            return "\n".join(lines) + "\nMembers follow games (ping role + thread) with /follow."
        if name == "server_pages":
            pages = [p for p in await db.pages(guild.id)
                     if p.kind == "custom" and p.message_ids and self.public_channel(guild, p.channel_id)]
            want = (args.get("page") or "").lower().strip()
            if not want:
                return "Pages: " + ", ".join(f"{p.title} (in <#{p.channel_id}>)" if p.channel_id else p.title
                                             for p in pages) if pages else "No pages yet."
            match = [p for p in pages if want in p.title.lower() or want in p.key]
            if not match:
                return "No page by that name. Pages: " + ", ".join(p.title for p in pages)
            out = []
            for p in match[:2]:
                out.append(f"# {p.title}")
                for sec in p.sections:
                    out.append("\n".join(x for x in (sec.heading and f"## {sec.heading}", sec.body) if x))
            return "\n\n".join(out)[:6000]
        if name == "game_activity":
            return await self.game_activity(guild, now)
        if name == "ship_ledger":
            ledger = self.bot.get_cog("ShipLedger")
            return await ledger.summary(guild.id) if ledger else "The Ship's Ledger isn't running."
        if name == "plunderbot_commands":
            return COMMANDS_HELP
        if name == "search_web":
            if self.kagi is None:
                return "Web search isn't set up."
            if await db.parley_lookups(guild.id, day) >= s.parley_kagi_daily:
                return "Today's web searches are used up. Answer from what you know and say so."
            await db.add_parley_lookup(guild.id, day)
            answer, refs = await self.kagi.fastgpt(str(args.get("query", ""))[:300])
            sources = "\n".join(f"- {r.get('title')}: {r.get('url')}" for r in refs[:3])
            return f"{answer}\n\nSources:\n{sources}" if sources else answer
        return f"Unknown tool {name}."


async def game_activity_lines(db, guild, now) -> list[tuple]:
    """(name, crews, pirates, followers, planned) per game, busiest first."""
    from collections import defaultdict
    from ..crew_logic import iso
    crews = await db.crews_sailed_between(guild.id, iso(now - timedelta(days=30)), iso(now))
    sailed, pirates = defaultdict(int), defaultdict(set)
    for c in crews:
        sailed[c.game_key] += 1
        pirates[c.game_key].update(c.members)
    planned = defaultdict(int)
    for v in await db.voyages_starting_between(guild.id, iso(now), iso(now + timedelta(days=14))):
        if v.status == "scheduled" and v.game_key:
            planned[v.game_key] += 1
    roles = await db.game_ping_roles(guild.id)
    rows = []
    for g in games.GAMES:
        if not g.crew_call:
            continue
        role = guild.get_role(roles[g.key]) if g.key in roles and hasattr(guild, "get_role") else None
        followers = len(role.members) if role is not None else 0
        rows.append((g.name, sailed[g.key], len(pirates[g.key]), followers, planned[g.key]))
    rows.sort(key=lambda r: (-r[1], -r[3], r[0]))
    return rows


async def setup(bot) -> None:
    await bot.add_cog(Parley(bot))
