"""The Crow's Nest: official game news, read from Steam or from a game's own RSS/Atom feed.

Kept free of networking so parsing is easy to test; the cog fetches and posts.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# Steam app ids for the Fortress's games (checked against the Steam store). Games not on Steam
# (Fortnite, League of Legends) need a feed set with /admin crowsnest source.
STEAM_APPS: dict[str, int] = {
    "sot": 1172620,
    "aletale": 2683150,
    "nms": 275850,
    "voidcrew": 1063420,
    "borderlands": 1285190,  # Borderlands 4
    "jumpspace": 1757300,
    "artemis": 247350,
    "drg": 548430,
    "plateup": 1599600,
    "anacrusis": 1120480,
    "helldivers": 553850,
    "rivals": 2767030,
    "lethal": 1966720,
}

STEAM_NEWS_URL = ("https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
                  "?appid={appid}&count=8&maxlength=0&format=json&feeds=steam_community_announcements")
STEAM_CLAN_IMAGE = "https://clan.akamai.steamstatic.com/images"
SUMMARY_MAX = 350


@dataclass
class NewsItem:
    id: str
    title: str
    url: str
    published: datetime | None
    summary: str
    image: str | None = None


def default_source(game_key: str) -> tuple[str, str] | None:
    appid = STEAM_APPS.get(game_key)
    return ("steam", str(appid)) if appid else None


def source_for(game_key: str, overrides: dict[str, tuple[str, str | None]]) -> tuple[str, str] | None:
    """The source to read for a game: a Quartermaster's choice, else the built-in Steam app.
    ("none", _) turns a game's news off."""
    if game_key in overrides:
        kind, value = overrides[game_key]
        return None if kind == "none" or not value else (kind, value)
    return default_source(game_key)


def steam_url(appid: str | int) -> str:
    return STEAM_NEWS_URL.format(appid=appid)


_BB_IMG = re.compile(r"\[img(?:=[^\]]*)?\](.*?)\[/img\]|\[img\s+src=\"([^\"]+)\"[^\]]*\]", re.I | re.S)
_HTML_IMG = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)
_BB_TAG = re.compile(r"\[/?[a-z0-9*]+(?:[= ][^\]]*)?\]", re.I)
_HTML_TAG = re.compile(r"<[^>]+>")


def first_image(text: str) -> str | None:
    m = _BB_IMG.search(text or "") or _HTML_IMG.search(text or "")
    if not m:
        return None
    url = next(g for g in m.groups() if g).strip()
    url = url.replace("{STEAM_CLAN_IMAGE}", STEAM_CLAN_IMAGE)
    return url if url.startswith("http") else None


def clean(text: str, limit: int = SUMMARY_MAX) -> str:
    """Steam's BBCode or a feed's HTML down to a short plain summary."""
    t = _BB_IMG.sub(" ", text or "")
    t = re.sub(r"\[\*\]", "\n• ", t)
    t = re.sub(r"\[/?(p|h\d|list|olist|br)\]|<br\s*/?>|</p>|</h\d>|</li>", "\n", t, flags=re.I)
    t = _BB_TAG.sub(" ", t)
    t = _HTML_TAG.sub(" ", t)
    t = html.unescape(t)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[ \t ]+", " ", t)
    t = re.sub(r"\s*\n\s*", "\n", t).strip()
    t = re.sub(r"\n{2,}", "\n", t)
    if len(t) > limit:
        cut = t[:limit].rsplit(" ", 1)[0].rstrip(",.;:-–—")
        t = cut + "…"
    return t


def parse_steam(data: dict) -> list[NewsItem]:
    items = []
    for n in (data.get("appnews") or {}).get("newsitems") or []:
        if n.get("feedname") not in (None, "steam_community_announcements"):
            continue
        contents = n.get("contents") or ""
        items.append(NewsItem(
            id=str(n.get("gid")), title=(n.get("title") or "Untitled").strip(), url=n.get("url") or "",
            published=datetime.fromtimestamp(n["date"], timezone.utc) if n.get("date") else None,
            summary=clean(contents), image=first_image(contents)))
    return items


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el, *names):
    for c in el:
        if _local(c.tag) in names:
            return c
    return None


def _date(text: str | None) -> datetime | None:
    if not text:
        return None
    text = text.strip()
    try:
        d = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def parse_feed(xml_text: str) -> list[NewsItem]:
    """RSS 2.0 or Atom."""
    root = ET.fromstring(xml_text)
    entries = [e for e in root.iter() if _local(e.tag) in ("item", "entry")]
    out = []
    for e in entries:
        title_el = _child(e, "title")
        title = (title_el.text or "").strip() if title_el is not None else "Untitled"
        link = ""
        for c in e:
            if _local(c.tag) == "link":
                link = (c.get("href") or c.text or "").strip()
                if c.get("rel") in (None, "alternate"):
                    break
        ident_el = _child(e, "guid", "id")
        ident = (ident_el.text or "").strip() if ident_el is not None and ident_el.text else link or title
        date_el = _child(e, "pubDate", "published", "updated", "date")
        body_el = _child(e, "encoded", "content", "description", "summary")
        body = body_el.text or "" if body_el is not None else ""
        image = None
        for c in e.iter():
            if _local(c.tag) in ("enclosure", "content", "thumbnail") and (c.get("url") or "").startswith("http"):
                if _local(c.tag) != "enclosure" or (c.get("type") or "").startswith("image"):
                    image = c.get("url")
                    break
        out.append(NewsItem(id=ident, title=html.unescape(title) or "Untitled", url=link,
                            published=_date(date_el.text if date_el is not None else None),
                            summary=clean(body), image=image or first_image(body)))
    return out


def new_items(items: list[NewsItem], seen: set[str], limit: int = 3) -> list[NewsItem]:
    """Unseen items, oldest first, at most `limit` (the rest wait for the next check)."""
    fresh = [i for i in items if i.id not in seen]
    fresh.sort(key=lambda i: i.published or datetime.min.replace(tzinfo=timezone.utc))
    return fresh[:limit]
