"""Gangplank: the rules of the airlock, kept free of Discord so they're easy to test.

A newcomer joins wearing the Pending role and is asked to introduce themselves in #introductions.
A Harbormaster reacts to the introduction with Yar (let them aboard: Pending comes off) or Nar
(turned away: kicked). Anyone who never says a word is reminded after a few days and shown the
door after a week.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .crew_logic import parse

APPROVE_DEFAULT = "yar"
REJECT_DEFAULT = "nar"


def emoji_key(text: str) -> str | None:
    """How an emoji is stored: a custom emoji by its id, a standard emoji as itself.
    Accepts "<:Yar:123>", "<a:Yar:123>", "123", or a standard emoji like "✅"."""
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        return text
    if text.startswith("<") and text.endswith(">"):
        parts = text[1:-1].split(":")
        if len(parts) == 3 and parts[2].isdigit():
            return parts[2]
        return None
    if text.startswith(":") and text.endswith(":"):
        return None  # a :name: we can't resolve here; custom emoji must be picked or pasted
    return text


def emoji_matches(emoji_id: int | None, emoji_name: str | None, configured: str | None, default_name: str) -> bool:
    """Is a reaction the configured emoji? With nothing configured, a custom emoji named
    Yar/Nar (any capitalisation) counts."""
    if configured:
        if configured.isdigit():
            return emoji_id is not None and emoji_id == int(configured)
        return emoji_id is None and emoji_name == configured
    return emoji_id is not None and (emoji_name or "").lower() == default_name


def verdict(emoji_id: int | None, emoji_name: str | None, approve: str | None, reject: str | None) -> str | None:
    if emoji_matches(emoji_id, emoji_name, approve, APPROVE_DEFAULT):
        return "approve"
    if emoji_matches(emoji_id, emoji_name, reject, REJECT_DEFAULT):
        return "reject"
    return None


def due(joined_at: str, responded_at: str | None, reminded_at: str | None, now: datetime,
        remind_days: int, kick_days: int) -> str | None:
    """What the clock says to do for someone still on the gangplank: "kick", "remind" or None.
    Only newcomers who never introduced themselves are reminded or kicked; once they've spoken,
    it's up to the Harbormasters."""
    if responded_at is not None:
        return None
    joined = parse(joined_at)
    if now >= joined + timedelta(days=kick_days):
        return "kick"
    if reminded_at is None and now >= joined + timedelta(days=remind_days):
        return "remind"
    return None


def deadline(joined_at: str, days: int) -> datetime:
    return parse(joined_at) + timedelta(days=days)
