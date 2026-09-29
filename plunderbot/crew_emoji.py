"""Emoji for crew cards and crew voice channels, per game and per crew size.

Voice channels follow the server's style, "⛵ | Boxer's Sloop". Discord only allows standard
(Unicode) emoji in channel names, so a server emoji can decorate the crew card but the channel
name always uses a standard one.
"""
from __future__ import annotations

import re
import unicodedata

from .games import GameProfile

# (game key, size label or "") -> default emoji. "" is the game-wide default.
DEFAULTS: dict[tuple[str, str], str] = {
    ("sot", ""): "⛵", ("sot", "Sloop"): "⛵", ("sot", "Brigantine"): "🛥️", ("sot", "Galleon"): "🚢",
    ("aletale", ""): "🍺",
    ("nms", ""): "🪐",
    ("fortnite", ""): "🪂",
    ("voidcrew", ""): "🚀",
    ("borderlands", ""): "💥",
    ("jumpspace", ""): "🛸",
    ("artemis", ""): "🛰️",
    ("drg", ""): "⛏️",
    ("plateup", ""): "🍳",
    ("anacrusis", ""): "👾",
    ("helldivers", ""): "🪖",
    ("rivals", ""): "🦸",
    ("lol", ""): "⚔️",
    ("lethal", ""): "📦",
    ("hangout", ""): "🛋️",
    ("event", ""): "🗓️",
}
FALLBACK = "🎮"

CUSTOM_RE = re.compile(r"^<a?:[A-Za-z0-9_]{2,32}:\d{15,21}>$")


def is_custom(value: str) -> bool:
    """A server (custom) emoji, e.g. <:galleon:123456789012345678>."""
    return bool(CUSTOM_RE.match(value.strip()))


def is_standard(value: str) -> bool:
    """A standard emoji: short, and made only of emoji/symbol characters and joiners."""
    value = value.strip()
    if not value or len(value) > 12:
        return False
    for ch in value:
        if ch in "‍️︎⃣" or 0x1F3FB <= ord(ch) <= 0x1F3FF:  # joiners, variation, skin tones
            continue
        cat = unicodedata.category(ch)
        if cat not in ("So", "Sk", "Sm") and not 0x1F1E6 <= ord(ch) <= 0x1F1FF:  # symbols, flags
            return False
    return True


def default_for(profile: GameProfile, size_label: str) -> str:
    return DEFAULTS.get((profile.key, size_label)) or DEFAULTS.get((profile.key, "")) or FALLBACK


def resolve(profile: GameProfile, size_label: str, overrides: dict[tuple[str, str], tuple[str | None, str | None]]
            ) -> tuple[str, str]:
    """(channel emoji, card emoji) for a game and size, from the server's picks then the defaults.

    `overrides` maps (game, size or "") to (standard emoji or None, server emoji or None).
    A size-specific pick beats a game-wide one; a server emoji only ever reaches the card.
    """
    channel, card = None, None
    for key in ((profile.key, size_label), (profile.key, "")):
        std, custom = overrides.get(key, (None, None))
        channel = channel or std
        card = card or custom or std
    channel = channel or default_for(profile, size_label)
    return channel, card or channel


def channel_subject(profile: GameProfile, size_label: str) -> str:
    """What the crew is called in its channel name: "Sloop", "Fortnite Squad", "Helldivers"."""
    if profile.open_ended:
        return profile.name
    if profile.key == "sot":
        return size_label
    if size_label.endswith(" players") or len(profile.sizes) == 1:
        return profile.short
    return f"{profile.short} {size_label}"
