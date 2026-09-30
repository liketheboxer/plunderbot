"""The Ship's Log: a weekly look back at the Fortress, and ahead at the week to come.

Pure functions: the cog gathers the numbers, these decide when to post and how it reads.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime

import discord

from . import games

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
FIELD_MAX = 1024


def is_due(now_local: datetime, weekday: int, hour: int, last_posted: str | None) -> bool:
    """Post once on the chosen weekday, from the chosen hour (server time) onwards."""
    today = now_local.date().isoformat()
    return now_local.weekday() == weekday and now_local.hour >= hour and last_posted != today


@dataclass
class WeekStats:
    week_start: date
    crews: list = field(default_factory=list)            # Crew objects that set sail
    voyages_done: list = field(default_factory=list)     # Voyages that started in the week
    voyages_ahead: list = field(default_factory=list)    # scheduled in the next 7 days
    birthdays: list = field(default_factory=list)        # (user_id, date) in the next 7 days
    newcomers: list = field(default_factory=list)        # user ids who joined and are aboard
    threads: dict = field(default_factory=dict)          # thread id -> messages
    news: list = field(default_factory=list)             # (game_key, title, url)

    @property
    def quiet(self) -> bool:
        return not (self.crews or self.voyages_done or self.voyages_ahead or self.birthdays or self.newcomers
                    or self.threads or self.news)


def _fit(lines: list[str], limit: int = FIELD_MAX) -> str:
    out, used = [], 0
    for i, line in enumerate(lines):
        more = len(lines) - i
        if used + len(line) + 1 > limit - 20:
            out.append(f"…and {more} more")
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


def _game_name(key: str | None) -> str:
    g = games.get(key)
    return g.name if g else "a server event"


def crew_lines(crews: list) -> list[str]:
    if not crews:
        return []
    pirates = {m for c in crews for m in c.members}
    by_game = Counter(c.game_key for c in crews)
    top = ", ".join(f"{_game_name(k)} ({n})" for k, n in by_game.most_common(4))
    lines = [f"**{len(crews)}** crew{'s' if len(crews) != 1 else ''} set sail with **{len(pirates)}** "
             f"pirate{'s' if len(pirates) != 1 else ''} aboard.", f"Most sailed: {top}"]
    captains = Counter(c.captain_id for c in crews).most_common(1)
    if captains and captains[0][1] >= 2:
        lines.append(f"Busiest captain: <@{captains[0][0]}> with {captains[0][1]} crews")
    return lines


def voyage_line(v) -> str:
    stamp = int(datetime.fromisoformat(v.starts_at).timestamp())
    link = f"https://discord.com/channels/{v.guild_id}/{v.channel_id}/{v.message_id}" if v.message_id else None
    title = f"[{v.title}]({link})" if link else v.title
    return f"<t:{stamp}:f> · {title}"


def render(stats: WeekStats, intro: str, colour: int = 0x1F8B8B) -> discord.Embed:
    embed = discord.Embed(title=f"Ship's Log · week of {stats.week_start.strftime('%B')} {stats.week_start.day}",
                          description=intro, colour=discord.Colour(colour))
    lines = crew_lines(stats.crews)
    if lines:
        embed.add_field(name="⚓ On the water", value=_fit(lines), inline=False)
    if stats.voyages_done:
        embed.add_field(name="🗺️ Voyages sailed", value=_fit([voyage_line(v) for v in stats.voyages_done]),
                        inline=False)
    if stats.voyages_ahead:
        embed.add_field(name="🧭 Coming up this week", value=_fit([voyage_line(v) for v in stats.voyages_ahead]),
                        inline=False)
    if stats.birthdays:
        embed.add_field(name="🎂 Birthdays this week",
                        value=_fit([f"<@{uid}> · {d.strftime('%A')} {d.strftime('%B')} {d.day}"
                                    for uid, d in stats.birthdays]), inline=False)
    if stats.newcomers:
        embed.add_field(name="🏴‍☠️ New pirates aboard",
                        value=_fit([", ".join(f"<@{u}>" for u in stats.newcomers)]), inline=False)
    if stats.threads:
        top = sorted(stats.threads.items(), key=lambda kv: -kv[1])[:5]
        embed.add_field(name="💬 Liveliest game threads",
                        value=_fit([f"<#{tid}> · {n} message{'s' if n != 1 else ''}" for tid, n in top]),
                        inline=False)
    if stats.news:
        embed.add_field(name="🔭 From the Crow's Nest",
                        value=_fit([f"{_game_name(k)}: [{t}]({u})" if u else f"{_game_name(k)}: {t}"
                                    for k, t, u in stats.news[-8:]]), inline=False)
    return embed
