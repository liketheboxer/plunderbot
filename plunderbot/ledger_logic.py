"""The Ship's Ledger: pirates' ships, their Captain's Log hauls, and pirate profiles.

Pure rules, free of Discord's plumbing: reading a Captain's Log screenshot with Claude (the tool
it fills in and how that's tidied), the Edit form's text, and how ships, hauls and pirates read.
"""
from __future__ import annotations

import base64
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import discord

from . import games

KINDS = ("Sloop", "Brigantine", "Galleon")
KIND_EMOJI = {"Sloop": "⛵", "Brigantine": "🛶", "Galleon": "🚢"}
GOLD, DOUBLOONS = "🪙", "🔷"
COLOUR = discord.Colour.from_rgb(212, 160, 23)
PENDING_COLOUR = discord.Colour.from_rgb(120, 144, 156)

# A crew that sailed for less than this, or never got anyone into voice, isn't asked for its log.
MIN_VOYAGE = timedelta(minutes=15)
# An unconfirmed reading is dropped after this long.
PENDING_LIFETIME = timedelta(days=1)
# How far back "your last crew" reaches when /ship log is used without saying which crew.
RECENT_CREW = timedelta(hours=18)
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # Claude's per-image limit
MAX_IMAGE_EDGE = 1568              # Claude scales anything bigger down to about this anyway
MAX_ROWS = 12


def fmt(n: int) -> str:
    return f"{n:,}"


_NUM = re.compile(r"(-?\d[\d,.\s]*)\s*([km])?", re.I)


def parse_number(text: str | None) -> int | None:
    """'12,345' / '12 345' / '12.3k' / '1.2m' -> an int. None if there's no number."""
    if text is None:
        return None
    m = _NUM.search(str(text).replace(" ", " ").replace(" ", " "))
    if not m:
        return None
    digits, suffix = m.group(1).strip(), (m.group(2) or "").lower()
    if suffix:
        try:
            value = float(digits.replace(",", "").replace(" ", ""))
        except ValueError:
            return None
        return int(round(value * (1000 if suffix == "k" else 1_000_000)))
    cleaned = re.sub(r"[,.\s]", "", digits)  # thousands separators, whichever the game used
    return int(cleaned) if cleaned.lstrip("-").isdigit() else None


# ------------------------------------------------------------ reading a screenshot
READ_TOOL = {
    "name": "record_captains_log",
    "description": "Record what a Sea of Thieves Captain's Log screenshot shows for the voyage.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_captains_log": {"type": "boolean",
                                "description": "True only if the picture is a Sea of Thieves Captain's Log or "
                                               "voyage summary page."},
            "ship_name": {"type": "string", "description": "The ship's name if it's shown, else empty."},
            "gold": {"type": "integer", "description": "Gold earned on this voyage. 0 if not shown."},
            "doubloons": {"type": "integer", "description": "Doubloons earned on this voyage. 0 if not shown."},
            "emissary": {"type": "string",
                         "description": "Emissary company and grade or value if shown, e.g. 'Gold Hoarders, "
                                        "grade 5'. Empty if none."},
            "reputation": {"type": "array", "description": "Reputation gained per trading company or faction.",
                           "items": {"type": "object", "properties": {
                               "company": {"type": "string"}, "amount": {"type": "integer"}},
                               "required": ["company", "amount"]}},
            "stats": {"type": "array",
                      "description": "Every other voyage statistic shown (islands visited, chests or loot sold, "
                                     "ships sunk, skeletons defeated, distance sailed, time at sea and so on), "
                                     "with the label as it's written.",
                      "items": {"type": "object", "properties": {
                          "label": {"type": "string"}, "value": {"type": "string"}},
                          "required": ["label", "value"]}},
            "notes": {"type": "string", "description": "Anything you couldn't read clearly. Empty if all clear."},
        },
        "required": ["is_captains_log", "gold", "doubloons"],
    },
}

READ_SYSTEM = ("You read Sea of Thieves Captain's Log screenshots for a Discord bot's ledger. Report only what is "
               "visibly written on the page; never guess or invent a number. Numbers are whole: read '12,345' as "
               "12345. If a value isn't shown, use 0 or leave it out. Always answer by calling "
               "record_captains_log.")
READ_PROMPT = "Here's the Captain's Log from our voyage. Record what it shows."


@dataclass
class Haul:
    gold: int = 0
    doubloons: int = 0
    emissary: str | None = None
    reputation: list[tuple[str, int]] = field(default_factory=list)
    stats: list[tuple[str, str]] = field(default_factory=list)
    ship_name: str | None = None
    notes: str | None = None
    is_log: bool = True


def _text(value, limit: int) -> str | None:
    cleaned = " ".join(str(value or "").replace("`", "'").split())[:limit].strip()
    return cleaned or None


def _count(value) -> int:
    n = value if isinstance(value, int) and not isinstance(value, bool) else parse_number(value)
    return max(0, min(n or 0, 2_000_000_000))


def from_tool_input(data: dict) -> Haul:
    """Tidy what Claude reported: non-negative numbers, short labels, no more than a dozen rows."""
    rep = []
    for item in (data.get("reputation") or [])[:MAX_ROWS]:
        if isinstance(item, dict) and _text(item.get("company"), 40):
            rep.append((_text(item["company"], 40), _count(item.get("amount"))))
    stats = []
    for item in (data.get("stats") or [])[:MAX_ROWS]:
        if isinstance(item, dict) and _text(item.get("label"), 40) and _text(item.get("value"), 40):
            stats.append((_text(item["label"], 40), _text(item["value"], 40)))
    return Haul(gold=_count(data.get("gold")), doubloons=_count(data.get("doubloons")),
                emissary=_text(data.get("emissary"), 100), reputation=rep, stats=stats,
                ship_name=_text(data.get("ship_name"), 60), notes=_text(data.get("notes"), 200),
                is_log=bool(data.get("is_captains_log", True)))


def read_response(resp: dict) -> Haul | None:
    for block in resp.get("content") or []:
        if block.get("type") == "tool_use" and block.get("name") == READ_TOOL["name"]:
            return from_tool_input(block.get("input") or {})
    return None


def prepare_image(data: bytes) -> tuple[str, str]:
    """(media type, base64) small enough for Claude. Big screenshots are scaled down to a JPEG."""
    from .images import ImageError, sniff
    kind = sniff(data)
    if kind is None:
        raise ImageError("not a PNG, JPG, GIF or WEBP picture")
    try:
        from PIL import Image
    except ImportError:
        Image = None
    if Image is not None:
        try:
            with Image.open(io.BytesIO(data)) as img:
                if max(img.size) > MAX_IMAGE_EDGE or len(data) > MAX_IMAGE_BYTES:
                    img = img.convert("RGB")
                    img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
                    out = io.BytesIO()
                    img.save(out, "JPEG", quality=88)
                    data, kind = out.getvalue(), "image/jpeg"
        except (OSError, ValueError) as e:
            raise ImageError(f"couldn't open the picture ({e})") from e
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError("too big to read (the limit is 5 MB)")
    return kind, base64.b64encode(data).decode("ascii")


def read_messages(media_type: str, b64: str) -> list[dict]:
    return [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
        {"type": "text", "text": READ_PROMPT}]}]


# ------------------------------------------------------------ storing and editing
def dump_rows(rows) -> str:
    return json.dumps([list(r) for r in rows])


def load_rows(text: str | None) -> list[tuple]:
    try:
        return [tuple(r) for r in json.loads(text or "[]") if isinstance(r, list) and len(r) == 2]
    except (ValueError, TypeError):
        return []


def reputation_text(rows) -> str:
    return "\n".join(f"{c}: {fmt(a)}" for c, a in rows)


def stats_text(rows) -> str:
    return "\n".join(f"{label}: {value}" for label, value in rows)


def _pairs(text: str) -> list[tuple[str, str]]:
    out = []
    for line in (text or "").splitlines():
        if ":" in line:
            label, value = line.split(":", 1)
        elif "=" in line:
            label, value = line.split("=", 1)
        else:
            continue
        label, value = _text(label, 40), _text(value, 40)
        if label and value:
            out.append((label, value))
    return out[:MAX_ROWS]


def parse_reputation(text: str) -> list[tuple[str, int]]:
    return [(c, parse_number(v) or 0) for c, v in _pairs(text)]


def parse_stats(text: str) -> list[tuple[str, str]]:
    return _pairs(text)


# ------------------------------------------------------------ who's asked, and when
def ask_at_end(crew, now: datetime) -> bool:
    """A Sea of Thieves crew that really sailed is asked for its Captain's Log when it's over."""
    if crew.game_key != "sot" or crew.status != "closed" or not crew.sailed_at:
        return False
    if crew.voice_channel_id and not crew.voice_occupied:
        return False  # the voice channel never saw anyone: they didn't sail together
    return now - datetime.fromisoformat(crew.sailed_at) >= MIN_VOYAGE


def log_keeper(crew, ship) -> int:
    """Who's asked for the log: the ship's owner if they were aboard (it's their Captain's Log), else the captain."""
    if ship is not None and ship.owner_id in crew.members:
        return ship.owner_id
    return crew.captain_id


def can_change(user_id: int, entry, crew, ship, is_mod: bool) -> bool:
    """Who may replace or remove a logged haul."""
    if is_mod or user_id == entry.logged_by:
        return True
    return (crew is not None and user_id == crew.captain_id) or (ship is not None and user_id == ship.owner_id)


def pick_crew(crews: list, now: datetime):
    """The crew a /ship log most likely means: the newest SoT crew the member sailed in lately."""
    for crew in sorted(crews, key=lambda c: c.sailed_at or "", reverse=True):
        if crew.game_key == "sot" and crew.sailed_at and now - datetime.fromisoformat(crew.sailed_at) <= RECENT_CREW:
            return crew
    return None


# ------------------------------------------------------------ how it reads
def ship_label(ship) -> str:
    return f"{KIND_EMOJI.get(ship.kind, '⛵')} {ship.name}"


def haul_line(gold: int, doubloons: int) -> str:
    parts = [f"{GOLD} **{fmt(gold)}** gold"]
    if doubloons:
        parts.append(f"{DOUBLOONS} **{fmt(doubloons)}** doubloons")
    return " · ".join(parts)


def _fit(lines: list[str], limit: int = 1024) -> str:
    out, used = [], 0
    for line in lines:
        if used + len(line) + 1 > limit - 12:
            out.append("…")
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out) or "—"


def render_log(entry, *, ship=None, crew=None, pending: bool = False, notes: str | None = None) -> discord.Embed:
    title = "📜 Captain's Log" + (f": {ship.name}" if ship else "")
    embed = discord.Embed(title=title, description=haul_line(entry.gold, entry.doubloons),
                          colour=PENDING_COLOUR if pending else COLOUR)
    if entry.emissary:
        embed.add_field(name="Emissary", value=entry.emissary[:1024], inline=False)
    rep = load_rows(entry.reputation)
    if rep:
        embed.add_field(name="Reputation", value=_fit([f"{c}: +{fmt(a)}" for c, a in rep]), inline=True)
    stats = load_rows(entry.stats)
    if stats:
        embed.add_field(name="Voyage", value=_fit([f"{label}: {value}" for label, value in stats]), inline=True)
    if entry.pirates:
        embed.add_field(name="Aboard", value=_fit([" ".join(f"<@{u}>" for u in entry.pirates)]), inline=False)
    if pending:
        embed.set_footer(text=("Check it over: Confirm to write it in the ledger, Edit to fix anything. "
                               + (f"Unsure about: {notes}" if notes else ""))[:2048])
    else:
        embed.set_footer(text=f"Ledger entry #{entry.id}" + (f" · {crew.title}" if crew is not None and crew.title else ""))
    return embed


def render_ship(ship, *, totals, shipmates: list[tuple[int, int]], recent: list, owner_name: str) -> discord.Embed:
    embed = discord.Embed(title=ship_label(ship), description=f"*{ship.motto}*" if ship.motto else None, colour=COLOUR)
    embed.add_field(name="Captain", value=f"<@{ship.owner_id}>", inline=True)
    embed.add_field(name="Class", value=ship.kind, inline=True)
    since = datetime.fromisoformat(ship.created_at)
    embed.add_field(name="Registered", value=f"<t:{int(since.timestamp())}:D>", inline=True)
    if totals.logs:
        embed.add_field(name="Plunder", value=f"{haul_line(totals.gold, totals.doubloons)}\n"
                                              f"{totals.logs} voyage{'s' if totals.logs != 1 else ''} logged · "
                                              f"best haul {GOLD} {fmt(totals.best_gold)}", inline=False)
    else:
        embed.add_field(name="Plunder", value="No voyages logged yet. After a voyage: `/ship log` with a "
                                              "Captain's Log screenshot.", inline=False)
    if shipmates:
        embed.add_field(name="Trusted crew", value=_fit([f"<@{u}> · {n} voyage{'s' if n != 1 else ''}"
                                                          for u, n in shipmates]), inline=True)
    if recent:
        embed.add_field(name="Latest voyages", value=_fit([_recent_line(e) for e in recent]), inline=True)
    if ship.retired:
        embed.set_footer(text="Retired from the fleet")
    return embed


def _recent_line(entry) -> str:
    when = int(datetime.fromisoformat(entry.confirmed_at or entry.created_at).timestamp())
    return f"<t:{when}:d> · {GOLD} {fmt(entry.gold)}"


def render_pirate(*, user_id: int, name: str, avatar: str | None, gamertag: str | None, motto: str | None,
                  sailed: int, captained: int, per_game: dict[str, int], ships: list, totals,
                  recent: list) -> discord.Embed:
    embed = discord.Embed(title=f"🏴‍☠️ {name}", description=f"*{motto}*" if motto else None, colour=COLOUR)
    if avatar:
        embed.set_thumbnail(url=avatar)
    if gamertag:
        embed.add_field(name="Gamertag", value=gamertag, inline=True)
    embed.add_field(name="Crews sailed", value=f"{sailed}" + (f" ({captained} as captain)" if captained else ""),
                    inline=True)
    if per_game:
        top = sorted(per_game.items(), key=lambda kv: -kv[1])[:3]
        embed.add_field(name="Favourite waters",
                        value=", ".join(f"{(games.get(k).name if games.get(k) else k)} ({n})" for k, n in top),
                        inline=False)
    if ships:
        embed.add_field(name="Ships", value=_fit([f"{ship_label(s)} ({s.kind})" for s in ships]), inline=False)
    if totals.logs:
        embed.add_field(name="Sea of Thieves plunder",
                        value=f"{haul_line(totals.gold, totals.doubloons)}\n{totals.logs} voyage"
                              f"{'s' if totals.logs != 1 else ''} logged · best haul {GOLD} {fmt(totals.best_gold)}",
                        inline=False)
    if recent:
        embed.add_field(name="Latest voyages", value=_fit([_recent_line(e) for e in recent]), inline=False)
    return embed


def render_fleet(ships: list[tuple], pirates: list[tuple], ship_names: dict[int, str]) -> discord.Embed:
    embed = discord.Embed(title="⚓ The Fortress Fleet", colour=COLOUR,
                          description="Richest ships and pirates by logged plunder. Log a voyage with `/ship log`.")
    medals = ["🥇", "🥈", "🥉"]
    if ships:
        embed.add_field(name="Ships", value=_fit([
            f"{medals[i] if i < 3 else f'{i + 1}.'} {ship_names.get(sid, 'A lost ship')} · {GOLD} {fmt(g)}"
            f" · {n} voyage{'s' if n != 1 else ''}" for i, (sid, n, g, d) in enumerate(ships)]), inline=False)
    if pirates:
        embed.add_field(name="Pirates", value=_fit([
            f"{medals[i] if i < 3 else f'{i + 1}.'} <@{uid}> · {GOLD} {fmt(g)}" for i, (uid, n, g, d) in enumerate(pirates)]),
            inline=False)
    if not ships and not pirates:
        embed.add_field(name="Empty seas", value="No voyages logged yet.", inline=False)
    return embed


def week_lines(logs: list, ship_names: dict[int, str]) -> list[str]:
    """The Ship's Log roundup's plunder field."""
    if not logs:
        return []
    gold, doubloons = sum(e.gold for e in logs), sum(e.doubloons for e in logs)
    lines = [f"{len(logs)} voyage{'s' if len(logs) != 1 else ''} logged: {haul_line(gold, doubloons)}"]
    best = max(logs, key=lambda e: e.gold)
    if best.gold:
        who = ship_names.get(best.ship_id) or (" ".join(f"<@{u}>" for u in best.pirates[:4]) or "a crew")
        lines.append(f"Richest haul: {who} with {GOLD} {fmt(best.gold)}")
    return lines


def ledger_summary(ships: list[tuple], pirates: list[tuple], ship_names: dict[int, str], totals) -> str:
    """For Parley: the ledger in a few plain lines."""
    if not totals.logs:
        return "No Sea of Thieves voyages have been logged yet. Crews log them with /ship log."
    lines = [f"All time: {totals.logs} voyages logged, {fmt(totals.gold)} gold and {fmt(totals.doubloons)} doubloons."]
    if ships:
        lines.append("Richest ships: " + "; ".join(
            f"{ship_names.get(sid, 'unknown')} ({fmt(g)} gold, {n} voyages)" for sid, n, g, d in ships[:5]))
    if pirates:
        lines.append("Richest pirates: " + "; ".join(f"<@{uid}> ({fmt(g)} gold)" for uid, n, g, d in pirates[:5]))
    return "\n".join(lines)
