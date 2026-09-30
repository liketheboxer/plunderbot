"""Daisho: PlunderBot's screens in The Magical Samurai.

PlunderBot stays the source of truth. This cog:

* sends Daisho a snapshot of its data (settings, the server's channels and roles, articles, Notice
  Board pages, voyages, crews and the Ship's Ledger): anything that changed, every five minutes, and
  everything every half hour;
* every 15 seconds, picks up changes made on the screens, applies them the same way the slash
  commands do (with the same checks), reports how each went, and re-sends what it touched.

It needs SAMURAI_URL and SAMURAI_MODULE_TOKEN (Exocomp sets both once the Captain has issued the module
token). Without them it does nothing, and if Daisho is down PlunderBot carries on as normal.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import aiohttp
import discord
from discord.ext import commands, tasks

from .. import games, images, links
from ..articles_logic import (ACTIONS, COOLDOWN_SCOPES, MATCHES, MAX_ACTIONS, MAX_REPLIES, SCHEDULE, TRIGGERS,
                              action_problem, clean_name, next_run, parse_schedule, server_emoji, split_keywords)
from ..birthday_logic import valid_timezone, zone
from ..crew_logic import clean_title, iso, now_utc, voice_channel_name
from ..discord_util import self_serve_problem
from ..ledger_logic import KINDS
from ..voyage_logic import ParseError, format_reminders, parse_reminders

log = logging.getLogger("plunderbot.daisho")

POLL_SECONDS = 15
PUSH_EVERY = 300        # send what changed
FORCE_EVERY = 1800      # send everything anyway, so Daisho knows we're alive
SECTIONS = ("guild", "settings", "articles", "pages", "voyages", "crews", "ledger")


class ApplyError(Exception):
    """A change that can't be applied; the message goes back to Daisho, so it's written for people."""


# ------------------------------------------------------------ talking to Daisho
class SamuraiClient:
    def __init__(self, base: str, token: str):
        self.base, self.token = base.rstrip("/") + "/api/m/plunderbot/v1", token
        self._session: aiohttp.ClientSession | None = None

    async def _s(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20),
                headers={"Authorization": f"Bearer {self.token}", "User-Agent": "PlunderBot"})
        return self._session

    async def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        s = await self._s()
        async with s.request(method, self.base + path, json=body) as resp:
            data = await resp.json(content_type=None)
            if resp.status != 200 or not isinstance(data, dict) or data.get("ok") is False:
                raise RuntimeError(f"{method} {path}: {resp.status} {str(data)[:200]}")
            return data

    async def snapshot(self, guild_id: int, sections: dict) -> dict:
        return await self._call("POST", "/snapshot", {"guild_id": str(guild_id), "sections": sections})

    async def changes(self) -> list[dict]:
        return (await self._call("GET", "/changes")).get("changes") or []

    async def result(self, change_id: int, status: str, message: str) -> None:
        await self._call("POST", f"/changes/{change_id}", {"status": status, "message": message[:1900]})

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()


def short_reminders(minutes: list[int]) -> str:
    """[1440, 60, 15] -> "1d, 1h, 15m": the way /voyage takes them, for the edit form."""
    if not minutes:
        return "none"
    return ", ".join(f"{n // 1440}d" if n % 1440 == 0 else f"{n // 60}h" if n % 60 == 0 else f"{n}m"
                     for n in minutes)


def digest(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def _channel_kind(c) -> str | None:
    t = getattr(c, "type", None)
    return {discord.ChannelType.text: "text", discord.ChannelType.news: "news", discord.ChannelType.voice: "voice",
            discord.ChannelType.stage_voice: "voice", discord.ChannelType.forum: "forum",
            discord.ChannelType.category: "category"}.get(t)


# ------------------------------------------------------------ what the Settings screen may change
# key: (kind, low, high). Kinds match the screen: text, category, forum, role, bool, int, zone.
SETTINGS = {
    "timezone": ("zone", 0, 0),
    "birthday_channel_id": ("text", 0, 0), "birthday_hour": ("int", 0, 23), "birthday_role_id": ("role", 0, 0),
    "crew_channel_id": ("text", 0, 0), "crew_category_id": ("category", 0, 0),
    "crew_cleanup_minutes": ("int", 1, 120), "crew_expire_minutes": ("int", 5, 1440),
    "voyage_channel_id": ("text", 0, 0),
    "gangplank_enabled": ("bool", 0, 1), "intro_channel_id": ("text", 0, 0), "pending_role_id": ("role", 0, 0),
    "harbormaster_role_id": ("role", 0, 0), "rules_channel_id": ("text", 0, 0),
    "orientation_channel_id": ("text", 0, 0), "gangplank_alert_channel_id": ("text", 0, 0),
    "gangplank_remind_days": ("int", 1, 30), "gangplank_kick_days": ("int", 1, 60),
    "forum_channel_id": ("forum", 0, 0), "crowsnest_enabled": ("bool", 0, 1),
    "shipslog_channel_id": ("text", 0, 0), "shipslog_weekday": ("int", 0, 6), "shipslog_hour": ("int", 0, 23),
    "parley_enabled": ("bool", 0, 1), "parley_budget_cents": ("int", 0, 1_000_000), "parley_daily": ("int", 0, 200),
    "ledger_reminders": ("bool", 0, 1),
}
LABELS = {"text": "text channel", "category": "category", "forum": "forum channel", "role": "role"}


class Daisho(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        cfg = bot.config
        self.connected = bool(cfg.samurai_url and cfg.module_token)
        self.client = SamuraiClient(cfg.samurai_url, cfg.module_token) if self.connected else None
        links.configure(cfg.samurai_public_url, cfg.unit, self.connected)
        self.sent: dict[str, str] = {}        # section → digest last accepted by Daisho
        self.dirty: set[str] = set(SECTIONS)  # send these on the next pass
        self.last_push = 0.0
        self.last_force = 0.0
        self.failing = False
        self.done: dict[int, tuple[str, str]] = {}   # change id → result, in case reporting it failed

    async def cog_load(self) -> None:
        if self.connected:
            self.loop.start()

    async def cog_unload(self) -> None:
        self.loop.cancel()
        if self.client is not None:
            await self.client.close()

    def guild(self) -> discord.Guild | None:
        guilds = [g for g in self.bot.guilds if not getattr(g, "unavailable", False)]
        if self.bot.config.dev_guild_id:
            dev = [g for g in guilds if g.id == self.bot.config.dev_guild_id]
            guilds = dev or guilds
        return max(guilds, key=lambda g: g.member_count or 0) if guilds else None

    def mark(self, *sections: str) -> None:
        self.dirty.update(sections)

    # ------------------------------------------------------------ the loop
    @tasks.loop(seconds=POLL_SECONDS)
    async def loop(self) -> None:
        guild = self.guild()
        if guild is None:
            return
        try:
            await self.run_once(guild)
            if self.failing:
                log.info("Daisho is reachable again")
            self.failing = False
        except Exception as e:  # Daisho down or unreachable: carry on, try again next pass
            if not self.failing:
                log.warning("Can't reach Daisho (%s); PlunderBot carries on and keeps trying", e)
            self.failing = True

    @loop.before_loop
    async def _wait_until_ready(self) -> None:
        await self.bot.wait_until_ready()

    async def run_once(self, guild: discord.Guild, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        for change in await self.client.changes():
            await self.handle(guild, change)
        force = now - self.last_force >= FORCE_EVERY
        check_all = force or now - self.last_push >= PUSH_EVERY
        if check_all or self.dirty:
            await self.push(guild, check_all=check_all, force=force)
            if check_all:
                self.last_push = now
            if force:
                self.last_force = now

    async def push(self, guild: discord.Guild, check_all: bool = False, force: bool = False) -> None:
        """Send the sections that changed: the marked ones, or every one when checking all. Forced, send
        everything whether or not it changed, so Daisho knows PlunderBot is alive."""
        wanted = set(SECTIONS) if (check_all or force) else set(self.dirty)
        out = {}
        for name in SECTIONS:
            if name not in wanted:
                continue
            data = await self.build(name, guild)
            d = digest(data)
            if force or self.sent.get(name) != d:
                out[name] = (data, d)
        if not out:
            self.dirty.clear()
            return
        await self.client.snapshot(guild.id, {k: v[0] for k, v in out.items()})
        for k, (_, d) in out.items():
            self.sent[k] = d
        self.dirty.clear()

    async def handle(self, guild: discord.Guild, change: dict) -> None:
        action, cid = change.get("action"), change.get("id")
        if cid in self.done:   # applied already, but Daisho never heard: just tell it again
            await self.client.result(cid, *self.done[cid])
            return
        handler = HANDLERS.get(action)
        try:
            if handler is None:
                raise ApplyError(f"This version of PlunderBot doesn't know how to {action}. Refit it.")
            message = await handler(self, guild, change.get("payload") or {})
            status = "applied"
        except ApplyError as e:
            message, status = str(e), "failed"
        except Exception as e:
            log.exception("Daisho change %s (%s) failed", cid, action)
            message, status = f"Something went wrong applying it ({type(e).__name__}).", "failed"
            if self.bot.telemetry is not None:
                self.bot.telemetry.error(e, command="daisho")
        self.done[cid] = (status, message or "Done.")
        if len(self.done) > 500:
            for old in sorted(self.done)[:250]:
                del self.done[old]
        section = change.get("section")
        if section in SECTIONS:
            self.mark(section)
        await self.client.result(cid, status, message or "Done.")
        log.info("Daisho change %s by %s: %s (%s)", cid, change.get("by"), action, status)

    # ------------------------------------------------------------ snapshots
    async def build(self, name: str, guild: discord.Guild):
        return await getattr(self, f"snap_{name}")(guild)

    def name_of(self, guild, user_id: int | None) -> str:
        if not user_id:
            return ""
        m = guild.get_member(user_id)
        return m.display_name if m else f"a former member ({user_id})"

    async def snap_guild(self, guild):
        s = await self.bot.db.get_settings(guild.id)
        chans = []
        for c in sorted(guild.channels, key=lambda c: (getattr(c, "position", 0), c.id)):
            kind = _channel_kind(c)
            if kind:
                cat = getattr(c, "category", None)
                chans.append({"id": c.id, "name": c.name, "type": kind, "category": cat.name if cat else None})
        me = guild.me
        roles = [{"id": r.id, "name": r.name, "assignable": me is not None and self_serve_problem(r, me) is None}
                 for r in sorted(guild.roles, key=lambda r: -r.position) if not r.is_default() and not r.managed]
        emojis = [{"id": e.id, "name": e.name, "animated": e.animated} for e in guild.emojis]
        return {"id": str(guild.id), "name": guild.name, "timezone": s.timezone or self.bot.config.default_timezone,
                "channels": chans, "roles": roles, "emojis": emojis,
                "games": [{"key": g.key, "name": g.name} for g in games.GAMES],
                "version": self.bot.version}

    async def snap_settings(self, guild):
        s = asdict(await self.bot.db.get_settings(guild.id))
        s.pop("guild_id", None)
        s["timezone"] = s.get("timezone") or self.bot.config.default_timezone
        parley = self.bot.get_cog("Parley")
        month = parley.today(await self.bot.db.get_settings(guild.id))[1] if parley else now_utc().strftime("%Y-%m")
        dollars, calls = await self.bot.db.parley_spend(guild.id, month)
        s["parley_spend"] = {"month": month, "dollars": round(dollars, 4), "calls": calls}
        s["has_anthropic"] = bool(self.bot.config.anthropic_api_key)
        s["can_read_messages"] = bool(getattr(self.bot, "can_read_messages", True))
        return s

    async def snap_articles(self, guild):
        out = []
        for a in await self.bot.db.articles(guild.id):
            d = asdict(a)
            d["actions"], d["channels"] = a.action_list, a.channel_ids
            d["counts"] = [[u, n] for u, n in await self.bot.db.article_counts(a.id, 5)]
            out.append(d)
        return out

    async def snap_pages(self, guild):
        out = []
        for p in await self.bot.db.pages(guild.id):
            out.append({"id": p.id, "key": p.key, "title": p.title, "kind": p.kind, "channel_id": p.channel_id,
                        "posted": bool(p.messages),
                        "sections": [{"id": s.id, "position": s.position, "heading": s.heading, "body": s.body,
                                      "colour": s.colour, "image": s.image, "image_style": s.image_style}
                                     for s in p.sections]})
        return out

    async def snap_voyages(self, guild):
        now = now_utc()
        vs = await self.bot.db.voyages_starting_between(guild.id, iso(now - timedelta(days=14)),
                                                        iso(now + timedelta(days=120)))
        out = []
        for v in vs:
            r = await self.bot.db.rsvps(v.id)
            g = games.get(v.game_key)
            out.append({"id": v.id, "title": v.title, "description": v.description, "game_key": v.game_key,
                        "game": g.name if g else None, "size_label": v.size_label, "capacity": v.capacity,
                        "starts_at": v.starts_at, "duration_min": v.duration_min,
                        "reminders": short_reminders(v.reminder_minutes),
                        "reminders_text": format_reminders(v.reminder_minutes),
                        "repeat": v.repeat, "status": v.status, "ping_role": v.ping_role,
                        "organizer_id": v.organizer_id, "organizer": self.name_of(guild, v.organizer_id),
                        "channel_id": v.channel_id, "message_id": v.message_id,
                        "aboard": [self.name_of(guild, u) for u in r.aboard],
                        "maybe": len(r.maybe), "waitlist": len(r.waitlist)})
        return out

    async def snap_crews(self, guild):
        now = now_utc()
        crews = {c.id: c for c in await self.bot.db.active_crews(guild.id)}
        for c in await self.bot.db.crews_sailed_between(guild.id, iso(now - timedelta(days=7)), iso(now)):
            crews.setdefault(c.id, c)
        ships = {s.id: s for s in await self.bot.db.ships(guild.id, include_retired=True)}
        out = []
        for c in sorted(crews.values(), key=lambda c: c.created_at, reverse=True)[:60]:
            g = games.get(c.game_key)
            entry = await self.bot.db.confirmed_log_for_crew(c.id)
            ship = ships.get(c.ship_id)
            out.append({"id": c.id, "game": g.name if g else c.game_key, "size_label": c.size_label,
                        "title": c.title, "status": c.status, "captain_id": c.captain_id,
                        "captain": self.name_of(guild, c.captain_id),
                        "members": [self.name_of(guild, u) for u in c.members], "capacity": c.capacity,
                        "ship": ship.name if ship else None, "created_at": c.created_at, "sailed_at": c.sailed_at,
                        "ended_at": c.ended_at, "channel_id": c.channel_id, "message_id": c.message_id,
                        "haul": {"gold": entry.gold, "doubloons": entry.doubloons} if entry else None})
        return out

    async def snap_ledger(self, guild):
        db = self.bot.db
        ships = []
        for s in await db.ships(guild.id, include_retired=True):
            t = await db.ledger_totals(guild.id, ship_id=s.id)
            ships.append({"id": s.id, "name": s.name, "kind": s.kind, "motto": s.motto, "owner_id": s.owner_id,
                          "owner": self.name_of(guild, s.owner_id), "retired": bool(s.retired),
                          "logs": t.logs, "gold": t.gold, "doubloons": t.doubloons})
        logs = []
        for e in await db.recent_logs(guild.id, limit=50):
            logs.append({"id": e.id, "ship_id": e.ship_id, "crew_id": e.crew_id, "gold": e.gold,
                         "doubloons": e.doubloons, "emissary": e.emissary, "confirmed_at": e.confirmed_at,
                         "logged_by": self.name_of(guild, e.logged_by),
                         "pirates": [self.name_of(guild, u) for u in e.pirates]})
        totals = await db.ledger_totals(guild.id)
        return {"ships": ships, "logs": logs, "totals": {"logs": totals.logs, "gold": totals.gold,
                                                         "doubloons": totals.doubloons}}

    # ------------------------------------------------------------ applying: settings
    def _check_value(self, guild, key: str, value):
        kind, lo, hi = SETTINGS[key]
        if kind == "zone":
            if not isinstance(value, str) or not valid_timezone(value):
                raise ApplyError(f"{value!r} isn't a time zone.")
            return value
        if kind in ("bool", "int"):
            if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
                raise ApplyError(f"{key.replace('_', ' ')} must be between {lo} and {hi}.")
            return value
        if value is None:
            return None
        if not isinstance(value, int):
            raise ApplyError(f"{key.replace('_', ' ')} must be a {LABELS[kind]}.")
        if kind == "role":
            role = guild.get_role(value)
            if role is None:
                raise ApplyError("That role no longer exists.")
            if key == "birthday_role_id":
                problem = self_serve_problem(role, guild.me)
                if problem:
                    raise ApplyError(problem)
            return value
        channel = guild.get_channel(value)
        if channel is None or (kind == "text" and not isinstance(channel, discord.TextChannel)) or \
                (kind == "category" and not isinstance(channel, discord.CategoryChannel)) or \
                (kind == "forum" and not isinstance(channel, discord.ForumChannel)):
            raise ApplyError(f"That {LABELS[kind]} no longer exists (or isn't a {LABELS[kind]}).")
        perms = channel.permissions_for(guild.me)
        if kind == "text" and not (perms.view_channel and perms.send_messages and perms.embed_links):
            raise ApplyError(f"PlunderBot can't post in #{channel.name}: it needs View Channel, Send Messages "
                             "and Embed Links there.")
        if kind == "category" and not perms.manage_channels:
            raise ApplyError(f"PlunderBot needs Manage Channels in {channel.name} to open voice channels there.")
        return value

    async def apply_settings(self, guild, payload: dict) -> str:
        fields = payload.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise ApplyError("Nothing to change.")
        unknown = [k for k in fields if k not in SETTINGS]
        if unknown:
            raise ApplyError(f"PlunderBot has no setting called {unknown[0]}.")
        values = {k: self._check_value(guild, k, v) for k, v in fields.items()}
        before = await self.bot.db.get_settings(guild.id)
        after = {**asdict(before), **values}
        notes = []
        if values.get("gangplank_enabled") and not before.gangplank_enabled:
            if not (after["intro_channel_id"] and after["pending_role_id"] and after["harbormaster_role_id"]):
                raise ApplyError("Gangplank needs the intro channel, the Pending role and the Harbormasters role first.")
        if values.get("crowsnest_enabled") and not before.crowsnest_enabled and not after["forum_channel_id"]:
            raise ApplyError("The Crow's Nest needs the game forum first.")
        if values.get("parley_enabled") and not self.bot.config.anthropic_api_key:
            raise ApplyError("Parley needs the ANTHROPIC_API_KEY secret on the unit first.")
        s = await self.bot.db.update_settings(guild.id, **values)
        if values.get("gangplank_enabled") and not before.gangplank_enabled:
            cog = self.bot.get_cog("Gangplank")
            found = await cog.catch_up(guild, s, discord.utils.utcnow()) if cog else 0
            notes.append(f"Gangplank is on; {found} member(s) wearing Pending are now tracked.")
        if values.get("crowsnest_enabled") and not before.crowsnest_enabled:
            cog = self.bot.get_cog("CrowsNest")
            if cog is not None:
                await cog.check(guild)
            notes.append("The Crow's Nest is on; what's already out was noted, not posted.")
        if "timezone" in values and values["timezone"] != before.timezone:
            await self._reschedule_articles(guild)
        self.mark("settings", "guild")
        return " ".join(["Saved."] + notes)

    async def _reschedule_articles(self, guild) -> None:
        tz = zone((await self.bot.db.get_settings(guild.id)).timezone, self.bot.config.default_timezone)
        for a in await self.bot.db.articles(guild.id, SCHEDULE):
            try:
                await self.bot.db.update_article(a.id, next_run=iso(next_run(parse_schedule(a.value or ""),
                                                                             now_utc(), tz)))
            except ParseError:
                pass
        self.mark("articles")

    # ------------------------------------------------------------ applying: articles
    def _article_value(self, guild, trigger: str, value) -> str | None:
        if trigger == "keyword":
            words = split_keywords(value if isinstance(value, str) else "")
            if not words:
                raise ApplyError("Give the words or phrases, separated by commas.")
            return ", ".join(words)
        if trigger == "reaction":
            emoji = server_emoji(str(value or "").strip(), guild.emojis)
            if not emoji:
                raise ApplyError("Give the emoji for the reaction.")
            return emoji
        if trigger in ("role_added", "role_removed"):
            if not str(value or "").isdigit() or guild.get_role(int(value)) is None:
                raise ApplyError("Pick the role.")
            return str(int(value))
        if trigger == "schedule":
            try:
                parse_schedule(str(value or ""))
            except ParseError as e:
                raise ApplyError(str(e))
            return " ".join(str(value).split())
        return None

    def _article_action(self, guild, trigger: str, a, old_images: set[str]) -> dict:
        if not isinstance(a, dict) or a.get("type") not in ACTIONS:
            raise ApplyError("An action has an unknown type.")
        kind = a["type"]
        out: dict = {"type": kind}
        if kind == "reply":
            texts = [str(t).strip()[:2000] for t in (a.get("texts") or []) if str(t).strip()][:MAX_REPLIES]
            if not texts:
                raise ApplyError("A reply needs at least one message to pick from.")
            out["texts"] = texts
            cid = a.get("channel_id")
            if cid:
                ch = guild.get_channel(int(cid))
                if not isinstance(ch, discord.TextChannel):
                    raise ApplyError("A reply's channel no longer exists.")
                out["channel_id"] = ch.id
            else:
                out["channel_id"] = None
            image = a.get("image")
            out["image"] = image if image in old_images and images.path_of(image, self.bot.config.data_dir) else None
        elif kind == "react":
            emoji = server_emoji(str(a.get("emoji") or "").strip(), guild.emojis)
            if not emoji:
                raise ApplyError("A reaction needs an emoji.")
            out["emoji"] = emoji
        elif kind == "role":
            role = guild.get_role(int(a.get("role_id") or 0))
            if role is None:
                raise ApplyError("A role action's role no longer exists.")
            problem = self_serve_problem(role, guild.me)
            if problem:
                raise ApplyError(problem)
            mins = a.get("minutes")
            if mins not in (None, "") and not (isinstance(mins, int) and 1 <= mins <= 43200):
                raise ApplyError("Minutes for a role must be between 1 and 43200.")
            out.update(role_id=role.id, mode="remove" if a.get("mode") == "remove" else "add",
                       minutes=mins or None)
        elif kind == "count":
            out["scope"] = "server" if a.get("scope") == "server" else "member"
        elif kind == "repost":
            ch = guild.get_channel(int(a.get("channel_id") or 0))
            if not isinstance(ch, discord.TextChannel):
                raise ApplyError("Repost needs a text channel.")
            out["channel_id"] = ch.id
        problem = action_problem(trigger, out)
        if problem:
            raise ApplyError(problem)
        return out

    async def apply_article_save(self, guild, p: dict) -> str:
        db = self.bot.db
        existing = await db.get_article(int(p["id"])) if p.get("id") else None
        if p.get("id") and (existing is None or existing.guild_id != guild.id):
            raise ApplyError("That article no longer exists.")
        name = clean_name(str(p.get("name") or ""))
        if not name:
            raise ApplyError("An article needs a name.")
        clash = await db.article_named(guild.id, name)
        if clash is not None and (existing is None or clash.id != existing.id):
            raise ApplyError(f"There's already an article called {name}.")
        trigger = existing.trigger if existing else p.get("trigger")
        if trigger not in TRIGGERS:
            raise ApplyError("Pick what sets the article off.")
        value = self._article_value(guild, trigger, p.get("value"))
        match = p.get("match") if p.get("match") in MATCHES else "word"
        scope = p.get("cooldown_scope") if p.get("cooldown_scope") in COOLDOWN_SCOPES else "channel"

        def num(key, lo, hi, default):
            v = p.get(key, default)
            if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
                raise ApplyError(f"{key.replace('_', ' ').title()} must be between {lo} and {hi}.")
            return v
        threshold, cooldown, chance = num("threshold", 1, 100, 1), num("cooldown", 0, 604800, 0), num("chance", 1, 100, 100)
        chans = []
        for cid in p.get("channels") or []:
            ch = guild.get_channel(int(cid))
            if ch is None:
                raise ApplyError("One of the article's channels no longer exists.")
            chans.append(ch.id)
        only = p.get("only_role_id")
        if only and guild.get_role(int(only)) is None:
            raise ApplyError("The article's required role no longer exists.")
        acts = p.get("actions") or []
        if not isinstance(acts, list) or len(acts) > MAX_ACTIONS:
            raise ApplyError(f"An article can do at most {MAX_ACTIONS} things.")
        old_images = {a.get("image") for a in (existing.action_list if existing else []) if a.get("image")}
        actions = [self._article_action(guild, trigger, a, old_images) for a in acts]
        if sum(a["type"] == "count" for a in actions) > 1:
            raise ApplyError("An article counts once at most.")
        tz = zone((await db.get_settings(guild.id)).timezone, self.bot.config.default_timezone)
        nxt = iso(next_run(parse_schedule(value), now_utc(), tz)) if trigger == SCHEDULE else None
        fields = dict(name=name, value=value, match=match, threshold=threshold, cooldown=cooldown,
                      cooldown_scope=scope, chance=chance, channels=json.dumps(chans),
                      only_role_id=int(only) if only else None, actions=json.dumps(actions),
                      enabled=1 if p.get("enabled", True) else 0)
        if existing is None:
            a = await db.create_article(guild_id=guild.id, name=name, trigger=trigger, value=value, match=match,
                                        threshold=threshold, created_by=0, created_at=iso(now_utc()), next_run=nxt)
            await db.update_article(a.id, **fields)
            return f"Article {name} created."
        if trigger == SCHEDULE and (value != existing.value or not existing.next_run):
            fields["next_run"] = nxt
        await db.update_article(existing.id, **fields)
        return f"Article {name} saved."

    async def apply_article_delete(self, guild, p: dict) -> str:
        a = await self.bot.db.get_article(int(p.get("id") or 0))
        if a is None or a.guild_id != guild.id:
            return "It was already gone."
        await self.bot.db.delete_article(a.id)
        return f"Article {a.name} deleted."

    # ------------------------------------------------------------ applying: Notice Board
    @staticmethod
    def _colour(v) -> int | None:
        if v in (None, ""):
            return None
        if isinstance(v, int):
            return v if 0 <= v <= 0xFFFFFF else None
        s = str(v).strip().lstrip("#")
        try:
            n = int(s, 16)
        except ValueError:
            raise ApplyError(f"{v} isn't a colour; use a hex colour like #D4A017.")
        if not 0 <= n <= 0xFFFFFF:
            raise ApplyError(f"{v} isn't a colour.")
        return n

    async def apply_page_save(self, guild, p: dict) -> str:
        db = self.bot.db
        page = await db.get_page(int(p.get("id") or 0))
        if page is None or page.guild_id != guild.id:
            raise ApplyError("That page no longer exists.")
        if page.kind != "custom":
            raise ApplyError("The Game Index builds itself; post it again to refresh it.")
        title = " ".join(str(p.get("title") or page.title).split())[:100]
        secs = p.get("sections")
        if not isinstance(secs, list) or len(secs) > 40:
            raise ApplyError("A page has between 0 and 40 sections.")
        have = {s.id: s for s in page.sections}
        keep_order = []
        for i, sec in enumerate(secs, start=1):
            heading = (str(sec.get("heading") or "").strip()[:256]) or None
            body = (str(sec.get("body") or "").strip()[:4000]) or None
            style = "banner" if sec.get("image_style") == "banner" else "inside"
            colour = self._colour(sec.get("colour"))
            sid = sec.get("id")
            if sid and int(sid) in have:
                old = have[int(sid)]
                if not (heading or body or old.image):
                    raise ApplyError(f"Section {i} is empty: give it a heading or some text.")
                await db.update_section(old.id, heading=heading, body=body, colour=colour, image_style=style)
                keep_order.append(old.id)
            else:
                if not (heading or body):
                    raise ApplyError(f"Section {i} is empty: give it a heading or some text.")
                new = await db.add_section(page.id, heading, body, colour, image_style=style)
                keep_order.append(new.id)
        for sid in set(have) - set(keep_order):
            await db.remove_section(page.id, sid)
        for pos, sid in enumerate(keep_order, start=1):
            await db.move_section(page.id, sid, pos)
        if title != page.title:
            await db.update_page(page.id, title=title)
        posted = " Post it to update it in Discord." if page.messages else ""
        return f"Page {title} saved.{posted}"

    async def apply_page_post(self, guild, p: dict) -> str:
        board = self.bot.get_cog("Noticeboard")
        page = await self.bot.db.get_page(int(p.get("id") or 0))
        if page is None or page.guild_id != guild.id or board is None:
            raise ApplyError("That page no longer exists.")
        cid = int(p.get("channel_id") or page.channel_id or 0)
        channel = guild.get_channel(cid)
        if not isinstance(channel, discord.TextChannel):
            raise ApplyError("Pick a channel to post it in.")
        perms = channel.permissions_for(guild.me)
        if not (perms.send_messages and perms.embed_links and perms.attach_files):
            raise ApplyError(f"PlunderBot needs Send Messages, Embed Links and Attach Files in #{channel.name}.")
        count, note = await board.publish(guild, page, channel)
        if not count:
            raise ApplyError(note or "The page has nothing to post.")
        return f"Posted in #{channel.name} ({count} message{'s' if count != 1 else ''}). {note}".strip()

    # ------------------------------------------------------------ applying: voyages and crews
    async def apply_voyage_update(self, guild, p: dict) -> str:
        cog = self.bot.get_cog("Voyages")
        v = await self.bot.db.get_voyage(int(p.get("id") or 0))
        if cog is None or v is None or v.guild_id != guild.id:
            raise ApplyError("That voyage no longer exists.")
        changes: dict = {}
        if "title" in p:
            title = " ".join(str(p["title"] or "").split())[:80]
            if not title:
                raise ApplyError("A voyage needs a title.")
            changes["title"] = title
        if "description" in p:
            changes["description"] = (str(p["description"] or "").strip()[:1000]) or None
        if "starts_at" in p:
            try:
                starts = datetime.fromisoformat(str(p["starts_at"]))
            except ValueError:
                raise ApplyError("That start time can't be read.")
            if starts.tzinfo is None:
                raise ApplyError("That start time has no time zone.")
            if starts <= now_utc() + timedelta(minutes=1):
                raise ApplyError("Pick a time in the future.")
            if iso(starts) != v.starts_at:
                changes.update(starts_at=iso(starts), reminders_sent="")
        if "duration_min" in p:
            d = p["duration_min"]
            if not isinstance(d, int) or not 15 <= d <= 720:
                raise ApplyError("A voyage lasts between 15 minutes and 12 hours.")
            changes["duration_min"] = d
        if "capacity" in p:
            c = p["capacity"]
            if c is not None and (not isinstance(c, int) or not 1 <= c <= 99):
                raise ApplyError("Seats must be between 1 and 99.")
            changes["capacity"] = c
        if "reminders" in p:
            try:   # the same wording as /voyage: "1d, 1h, 15m" or "none"
                mins = parse_reminders(str(p["reminders"] or "none"))
            except ParseError as e:
                raise ApplyError(str(e))
            if ",".join(map(str, mins)) != v.reminders:
                changes.update(reminders=",".join(map(str, mins)), reminders_sent="")
        if "ping_role" in p:
            if p["ping_role"] not in ("off", "posted", "reminders"):
                raise ApplyError("Pick when the game's role is tagged.")
            changes["ping_role"] = p["ping_role"]
        if not changes:
            return "Nothing changed."
        if await cog.apply_edit(guild, v.id, changes) is None:
            raise ApplyError("That voyage has already started or ended, so it can't be changed.")
        self.mark("voyages")
        return f"Voyage {changes.get('title', v.title)} updated."

    async def apply_voyage_cancel(self, guild, p: dict) -> str:
        cog = self.bot.get_cog("Voyages")
        v = await self.bot.db.get_voyage(int(p.get("id") or 0))
        if cog is None or v is None or v.guild_id != guild.id:
            raise ApplyError("That voyage no longer exists.")
        if not await cog.apply_cancel(guild, v.id, bool(p.get("whole_series"))):
            raise ApplyError("That voyage has already started or ended.")
        return f"Voyage {v.title} cancelled; everyone who'd signed up was told."

    async def apply_crew_close(self, guild, p: dict) -> str:
        cog = self.bot.get_cog("CrewCall")
        crew = await self.bot.db.get_crew(int(p.get("id") or 0))
        if cog is None or crew is None or crew.guild_id != guild.id:
            raise ApplyError("That crew no longer exists.")
        if not crew.active:
            return "That crew had already finished."
        await cog.end(guild, crew.id, "closed")
        return "Crew closed, and its voice channel removed."

    async def apply_crew_rename(self, guild, p: dict) -> str:
        cog = self.bot.get_cog("CrewCall")
        crew = await self.bot.db.get_crew(int(p.get("id") or 0))
        if cog is None or crew is None or crew.guild_id != guild.id:
            raise ApplyError("That crew no longer exists.")
        if not crew.active:
            raise ApplyError("That crew has finished.")
        crew = await self.bot.db.update_crew(crew.id, title=clean_title(p.get("title")))
        await cog.refresh_card(guild, crew)
        vc = guild.get_channel(crew.voice_channel_id) if crew.voice_channel_id else None
        if vc is not None:
            profile = games.get(crew.game_key)
            emoji, _ = await cog.emoji_for(guild.id, profile, crew.size_label)
            captain = guild.get_member(crew.captain_id)
            await cog._rename_channel(vc, voice_channel_name(profile, crew.size_label,
                                                             captain.display_name if captain else "Captain",
                                                             emoji, crew.title))
        return "Crew renamed."

    # ------------------------------------------------------------ applying: the Ship's Ledger
    async def apply_ship_update(self, guild, p: dict) -> str:
        db = self.bot.db
        ship = await db.get_ship(int(p.get("id") or 0))
        if ship is None or ship.guild_id != guild.id:
            raise ApplyError("That ship no longer exists.")
        changes = {}
        if "name" in p:
            name = " ".join(str(p["name"] or "").replace("`", "'").split())[:60]
            if not name:
                raise ApplyError("A ship needs a name.")
            changes["name"] = name
        if "kind" in p:
            if p["kind"] not in KINDS:
                raise ApplyError("A ship is a Sloop, Brigantine or Galleon.")
            changes["kind"] = p["kind"]
        if "motto" in p:
            changes["motto"] = (" ".join(str(p["motto"] or "").split())[:150]) or None
        if "retired" in p:
            changes["retired"] = 1 if p["retired"] else 0
        if not changes:
            return "Nothing changed."
        await db.update_ship(ship.id, **changes)
        self.mark("crews", "ledger")
        return f"Ship {changes.get('name', ship.name)} updated."

    async def apply_log_remove(self, guild, p: dict) -> str:
        ledger = self.bot.get_cog("ShipLedger")
        entry = await self.bot.db.get_log(int(p.get("id") or 0))
        if ledger is None or entry is None or entry.guild_id != guild.id:
            return "It was already gone."
        await ledger.remove(guild, entry)
        crew = await self.bot.db.get_crew(entry.crew_id) if entry.crew_id else None
        cog = self.bot.get_cog("CrewCall")
        if crew is not None and cog is not None:
            await cog.refresh_card(guild, crew)
        self.mark("crews", "ledger")
        return f"Ledger entry #{entry.id} ({entry.gold:,} gold) removed, and its post taken down."


HANDLERS = {
    "settings.update": Daisho.apply_settings,
    "article.save": Daisho.apply_article_save,
    "article.delete": Daisho.apply_article_delete,
    "page.save": Daisho.apply_page_save,
    "page.post": Daisho.apply_page_post,
    "voyage.update": Daisho.apply_voyage_update,
    "voyage.cancel": Daisho.apply_voyage_cancel,
    "crew.close": Daisho.apply_crew_close,
    "crew.rename": Daisho.apply_crew_rename,
    "ship.update": Daisho.apply_ship_update,
    "log.remove": Daisho.apply_log_remove,
}


async def setup(bot) -> None:
    await bot.add_cog(Daisho(bot))
