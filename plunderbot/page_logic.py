"""Notice Board pages: turning a page's sections into Discord messages.

Each section is one embed (a heading, a body, an optional colour and picture). Discord allows 10
embeds and 6,000 characters per message, so a long page spills over several messages, posted in
order and edited in place afterwards.
"""
from __future__ import annotations

import re

import discord

EMBEDS_PER_MESSAGE = 10
CHARS_PER_MESSAGE = 5800  # a little under Discord's 6,000
HEADING_MAX = 256
BODY_MAX = 4096
DEFAULT_COLOUR = 0x1F8B8B  # sea green


def parse_colour(text: str | None) -> int | None:
    """"#1f8b8b", "1f8b8b" or "0x1f8b8b" to a number; None if empty. Raises ValueError if it isn't one."""
    if not text or not text.strip():
        return None
    t = text.strip().lower().removeprefix("#").removeprefix("0x")
    if not re.fullmatch(r"[0-9a-f]{6}", t):
        raise ValueError("colour")
    return int(t, 16)


def colour_text(value: int | None) -> str:
    return f"#{value:06x}" if value is not None else ""


def section_size(heading: str | None, body: str | None) -> int:
    return len(heading or "") + len(body or "")


def group(sections: list) -> list[list]:
    """Split sections into messages: at most 10 embeds and ~5,800 characters each, order kept."""
    out: list[list] = [[]]
    size = 0
    for s in sections:
        n = section_size(s.heading, s.body)
        if out[-1] and (len(out[-1]) >= EMBEDS_PER_MESSAGE or size + n > CHARS_PER_MESSAGE):
            out.append([])
            size = 0
        out[-1].append(s)
        size += n
    return out if out[0] else []


def image_filename(section_id: int, stored: str) -> str:
    return f"s{section_id}.{stored.rsplit('.', 1)[-1]}"


def render_section(s, has_image: bool = False) -> discord.Embed:
    embed = discord.Embed(title=(s.heading or None) and s.heading[:HEADING_MAX],
                          description=(s.body or None) and s.body[:BODY_MAX],
                          colour=discord.Colour(s.colour if s.colour is not None else DEFAULT_COLOUR))
    if has_image and s.image:
        embed.set_image(url=f"attachment://{image_filename(s.id, s.image)}")
    return embed


def game_index_lines(entries: list[dict]) -> list[str]:
    """One line per game: emoji, name, its forum thread and its ping role, when it has them."""
    lines = []
    for e in entries:
        bits = [f"{e['emoji']} **{e['name']}**"]
        if e.get("thread_id"):
            bits.append(f"<#{e['thread_id']}>")
        if e.get("role_id"):
            bits.append(f"<@&{e['role_id']}>")
        lines.append(" · ".join(bits))
    return lines


def chunk_lines(lines: list[str], limit: int = 4000) -> list[str]:
    out, cur = [], ""
    for line in lines:
        if cur and len(cur) + 1 + len(line) > limit:
            out.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out
