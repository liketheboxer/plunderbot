"""Colours: role menus, kept free of Discord objects where possible so the rules are easy to test.

A menu is a titled list of roles members pick for themselves (regions, platforms, games...).
Its card in the channel has one button; pressing it opens a private picker already ticked with the
roles the member wears, so saving the picker sets exactly what they chose.
"""
from __future__ import annotations

import re

import discord

MAX_OPTIONS = 25  # Discord's limit for one dropdown
_CUSTOM = re.compile(r"<a?:\w{2,32}:\d{15,25}>")
_ROLE = re.compile(r"<@&(\d{15,25})>")


def slug(text: str) -> str:
    """A short key for a menu or page: "Region Roles!" -> "region-roles"."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "menu"


def _is_emoji_char(ch: str) -> bool:
    cp = ord(ch)
    return (cp >= 0x1F000 or 0x2190 <= cp <= 0x2BFF or 0x2300 <= cp <= 0x23FF or 0x2600 <= cp <= 0x27BF
            or 0x3000 <= cp <= 0x303F or cp in (0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139, 0x3297, 0x3299))


def first_emoji(text: str) -> str | None:
    """The first emoji in a bit of text: a server emoji (<:name:id>) or a standard one (with any
    joiners, variation selectors, skin tones or flag pairs that belong to it)."""
    custom = _CUSTOM.search(text)
    i, n = 0, len(text)
    while i < n:
        if custom and i == custom.start():
            return custom.group(0)
        ch = text[i]
        if _is_emoji_char(ch) or (ch.isdigit() or ch in "#*") and i + 1 < n and text[i + 1] in "️⃣":
            j = i + 1
            while j < n and (text[j] in "️‍⃣" or 0x1F3FB <= ord(text[j]) <= 0x1F3FF
                             or (text[j - 1] == "‍" and _is_emoji_char(text[j]))
                             or (0x1F1E6 <= ord(ch) <= 0x1F1FF and j == i + 1 and 0x1F1E6 <= ord(text[j]) <= 0x1F1FF)
                             or 0xE0020 <= ord(text[j]) <= 0xE007F):
                j += 1
            return text[i:j]
        i += 1
    return None


def parse_import(text: str) -> list[tuple[str | None, int]]:
    """Pull (emoji, role id) pairs out of a reaction-role message, one per line that mentions a role:
    "🇼 : @North America - West" becomes ("🇼", <that role's id>)."""
    found, seen = [], set()
    for line in (text or "").splitlines():
        m = _ROLE.search(line)
        if not m:
            continue
        role_id = int(m.group(1))
        if role_id in seen:
            continue
        seen.add(role_id)
        found.append((first_emoji(line[:m.start()]) or first_emoji(line), role_id))
    return found


def plan(current: set[int], menu_roles: list[int], chosen: list[int], mode: str) -> tuple[list[int], list[int]]:
    """Roles to add and remove so the member wears exactly `chosen` out of this menu's roles.
    Roles outside the menu are never touched. A single-choice menu keeps only the first pick."""
    allowed = [r for r in chosen if r in menu_roles]
    if mode == "single":
        allowed = allowed[:1]
    want = set(allowed)
    add = [r for r in menu_roles if r in want and r not in current]
    remove = [r for r in menu_roles if r in current and r not in want]
    return add, remove


def partial_emoji(text: str | None) -> discord.PartialEmoji | None:
    if not text:
        return None
    try:
        return discord.PartialEmoji.from_str(text)
    except (TypeError, ValueError):
        return None


def option_line(emoji: str | None, role_id: int, description: str | None) -> str:
    line = f"{emoji}  <@&{role_id}>" if emoji else f"<@&{role_id}>"
    return f"{line} · {description}" if description else line


def render_menu(menu, colour: discord.Colour | None = None) -> discord.Embed:
    """The menu's card: title, description and the roles on offer. Role mentions in an embed
    don't ping anyone."""
    embed = discord.Embed(title=menu.title, colour=colour or discord.Colour.teal())
    lines = [option_line(o.emoji, o.role_id, o.description) for o in menu.options]
    body = (menu.description or "").strip()
    listing = "\n".join(lines) if lines else "*No roles on this menu yet.*"
    text = f"{body}\n\n{listing}" if body else listing
    embed.description = text[:4096]
    hint = "Pick one" if menu.mode == "single" else "Pick as many as you like"
    embed.set_footer(text=f"{hint}. Press the button to choose; you can change your mind any time.")
    return embed
