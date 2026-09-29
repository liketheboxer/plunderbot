"""Voyages: scheduled sessions. Parsing, reminders, repeats and the RSVP card, apart from Discord."""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import discord

from .games import GameProfile

def is_weekday_name(text: str) -> bool:
    t = text.strip().lower().rstrip(".")
    return any(t in (n, n[:3]) for n in WEEKDAYS)


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DEFAULT_REMINDERS = "1d, 1h"
REMINDER_PRESETS = [
    ("1 day and 1 hour before (default)", "1d, 1h"),
    ("1 hour before", "1h"),
    ("2 days, 1 day and 1 hour before", "2d, 1d, 1h"),
    ("30 minutes before", "30m"),
    ("No reminders before the start", "none"),
]
REPEATS = {"none": "Doesn't repeat", "weekly": "Every week", "biweekly": "Every 2 weeks", "monthly": "Every month"}
MAX_REMINDERS = 5


class ParseError(ValueError):
    """Something a member typed that we couldn't understand; the message is shown to them."""


# ------------------------------------------------------------ dates and times
def parse_date(text: str, today: date) -> date:
    t = text.strip().lower()
    if t in ("today", "tonight"):
        return today
    if t == "tomorrow":
        return today + timedelta(days=1)
    for i, name in enumerate(WEEKDAYS):
        if t in (name, name[:3], name[:3] + "."):
            ahead = (i - today.weekday()) % 7
            return today + timedelta(days=ahead)
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        return _make_date(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?", t)
    if m:
        month, day = int(m[1]), int(m[2])
        if m[3]:
            year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
            return _make_date(year, month, day)
        d = _make_date(today.year, month, day)
        return d if d >= today else _make_date(today.year + 1, month, day)
    raise ParseError(f"I couldn't read the date \"{text}\". Try friday, tomorrow, 10/3 or 2026-10-03.")


def _make_date(y: int, m: int, d: int) -> date:
    try:
        return date(y, m, d)
    except ValueError as e:
        raise ParseError(f"{y}-{m:02d}-{d:02d} isn't a real date.") from e


def parse_time(text: str) -> time:
    t = text.strip().lower().replace(" ", "").replace(".", "")
    if t == "noon":
        return time(12, 0)
    if t == "midnight":
        return time(0, 0)
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm|a|p)?", t)
    if not m:
        raise ParseError(f"I couldn't read the time \"{text}\". Try 8pm, 8:30pm or 20:30.")
    hour, minute, suffix = int(m[1]), int(m[2] or 0), m[3]
    if minute > 59:
        raise ParseError(f"\"{text}\" has too many minutes.")
    if suffix:
        if not 1 <= hour <= 12:
            raise ParseError(f"\"{text}\" isn't a 12-hour time.")
        hour = hour % 12 + (12 if suffix.startswith("p") else 0)
    elif hour > 23:
        raise ParseError(f"\"{text}\" isn't a time of day.")
    return time(hour, minute)


def to_utc(day: date, at: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, at, tzinfo=tz).astimezone(timezone.utc)


# ------------------------------------------------------------ reminders
def parse_reminders(text: str | None) -> list[int]:
    """Minutes before the start, largest first. "1d, 1h, 15m" -> [1440, 60, 15]; "none" -> []."""
    if text is None:
        text = DEFAULT_REMINDERS
    t = text.strip().lower()
    if t in ("", "none", "off", "no"):
        return []
    out: set[int] = set()
    for token in re.split(r"[,\s]+", t):
        if not token or token in ("start", "and"):
            continue  # the start ping always happens when the voice channel opens
        m = re.fullmatch(r"(\d+)(d|h|m)", token)
        if not m:
            raise ParseError(f"I couldn't read the reminder \"{token}\". Use things like 2d, 3h or 15m.")
        n = int(m[1]) * {"d": 1440, "h": 60, "m": 1}[m[2]]
        if not 5 <= n <= 14 * 1440:
            raise ParseError("Reminders can be from 5 minutes to 14 days before the start.")
        out.add(n)
    if len(out) > MAX_REMINDERS:
        raise ParseError(f"That's a lot of pinging! Up to {MAX_REMINDERS} reminders, please.")
    return sorted(out, reverse=True)


def format_reminders(minutes: list[int]) -> str:
    if not minutes:
        return "none before the start"
    parts = []
    for n in minutes:
        if n % 1440 == 0:
            parts.append(f"{n // 1440} day{'s' if n >= 2880 else ''}")
        elif n % 60 == 0:
            parts.append(f"{n // 60} hour{'s' if n >= 120 else ''}")
        else:
            parts.append(f"{n} min")
    return ", ".join(parts) + " before"


def due_reminder(starts_at: datetime, created_at: datetime, minutes: list[int], sent: list[int],
                 now: datetime) -> int | None:
    """The reminder to send now, if any. Reminders whose time had already passed when the voyage was
    created are skipped rather than fired late; if several are due, only the closest to the start goes."""
    due = [m for m in minutes if m not in sent and now >= starts_at - timedelta(minutes=m)
           and starts_at - timedelta(minutes=m) >= created_at and now < starts_at]
    return min(due) if due else None


def overdue_reminders(starts_at: datetime, created_at: datetime, minutes: list[int], sent: list[int],
                      now: datetime) -> list[int]:
    """Reminders that will never go out (passed before creation, or superseded); mark them sent."""
    return [m for m in minutes if m not in sent and starts_at - timedelta(minutes=m) < created_at]


# ------------------------------------------------------------ repeats
def next_occurrence(starts_at: datetime, repeat: str, tz: ZoneInfo, anchor_day: int | None = None) -> datetime | None:
    """The next start in a series, keeping the same local wall-clock time across daylight saving.
    Monthly repeats aim for anchor_day (the series' original day) so Jan 31 -> Feb 28 -> Mar 31."""
    if repeat not in ("weekly", "biweekly", "monthly"):
        return None
    local = starts_at.astimezone(tz)
    if repeat == "weekly":
        nxt = local.date() + timedelta(days=7)
    elif repeat == "biweekly":
        nxt = local.date() + timedelta(days=14)
    else:
        y, m = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
        nxt = date(y, m, min(anchor_day or local.day, calendar.monthrange(y, m)[1]))
    return to_utc(nxt, local.timetz().replace(tzinfo=None), tz)


# ------------------------------------------------------------ RSVPs
@dataclass
class Rsvps:
    aboard: list[int] = field(default_factory=list)   # in order of joining
    maybe: list[int] = field(default_factory=list)
    cant: list[int] = field(default_factory=list)
    waitlist: list[int] = field(default_factory=list)  # in order of joining

    def of(self, user_id: int) -> str | None:
        for status in ("aboard", "maybe", "cant", "waitlist"):
            if user_id in getattr(self, status):
                return status
        return None


def placement(wanted: str, rsvps: Rsvps, capacity: int | None) -> str:
    """Where a member lands when they press a button: a full voyage puts "aboard" on the waitlist."""
    if wanted != "aboard":
        return wanted
    if capacity is None or len(rsvps.aboard) < capacity:
        return "aboard"
    return "waitlist"


# ------------------------------------------------------------ the card
STATUS_TEXT = {"scheduled": "Scheduled", "started": "Under way", "ended": "Finished", "cancelled": "Cancelled"}
STATUS_COLOUR = {
    "scheduled": discord.Colour.from_rgb(52, 152, 219),
    "started": discord.Colour.from_rgb(241, 196, 15),
    "ended": discord.Colour.dark_grey(),
    "cancelled": discord.Colour.dark_grey(),
}


def _names(ids: list[int], limit: int = 900) -> str:
    shown: list[str] = []
    for i in ids:
        mention = f"<@{i}>"
        if len(", ".join(shown + [mention])) > limit:
            return ", ".join(shown) + f" and {len(ids) - len(shown)} more"
        shown.append(mention)
    return ", ".join(shown) or "Nobody yet"


def render_voyage(v, rsvps: Rsvps, profile: GameProfile | None, emoji: str,
                  crew_link: str | None = None) -> discord.Embed:
    stamp = int(datetime.fromisoformat(v.starts_at).timestamp())
    embed = discord.Embed(title=f"{emoji} {v.title}", colour=STATUS_COLOUR.get(v.status, discord.Colour.default()))
    if v.description:
        embed.description = v.description[:2000]
    when = f"<t:{stamp}:F> (<t:{stamp}:R>)"
    if v.repeat != "none":
        when += f"\n{REPEATS[v.repeat]}"
    embed.add_field(name="When", value=when, inline=False)
    if profile is not None:
        game = profile.name if profile.open_ended else f"{profile.name}: {v.size_label}"
        embed.add_field(name="Game", value=game, inline=True)
    embed.add_field(name="Organizer", value=f"<@{v.organizer_id}>", inline=True)
    embed.add_field(name="Status", value=STATUS_TEXT.get(v.status, v.status), inline=True)
    cap = f" ({len(rsvps.aboard)}/{v.capacity})" if v.capacity else f" ({len(rsvps.aboard)})"
    embed.add_field(name=f"Aboard{cap}", value=_names(rsvps.aboard), inline=False)
    if rsvps.waitlist:
        embed.add_field(name=f"Waitlist ({len(rsvps.waitlist)})", value=_names(rsvps.waitlist), inline=False)
    embed.add_field(name=f"Maybe ({len(rsvps.maybe)})", value=_names(rsvps.maybe), inline=False)
    if rsvps.cant:
        embed.add_field(name="Can't make it", value=str(len(rsvps.cant)), inline=True)
    if v.status == "started" and crew_link:
        embed.add_field(name="Crew", value=f"Under way! Join the crew here: {crew_link}", inline=False)
    if v.status == "scheduled":
        embed.set_footer(text=f"Reminders: {format_reminders(v.reminder_minutes)}. "
                              "A voice channel opens at the start.")
    return embed
