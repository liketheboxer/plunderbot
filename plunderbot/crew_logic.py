"""Crew Call rules and the crew card, kept apart from the Discord plumbing so they're easy to test."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import discord

from .db import Crew
from .crew_emoji import channel_subject, default_for
from .games import GameProfile

# A new voice channel gets this long for the crew to arrive before an empty channel counts.
FIRST_JOIN_GRACE = timedelta(minutes=15)
# A crew that sailed but got no voice channel (creation failed) closes after this long.
NO_VOICE_GRACE = timedelta(minutes=10)
# The same game's ping role is pinged at most this often.
PING_COOLDOWN = timedelta(minutes=15)

STATUS_LABEL = {
    "open": "Mustering",
    "sailing": "Under sail",
    "closed": "Back in port",
    "expired": "Never left port",
}
STATUS_COLOUR = {
    "open": discord.Colour.from_rgb(46, 204, 170),
    "sailing": discord.Colour.from_rgb(241, 196, 15),
    "closed": discord.Colour.dark_grey(),
    "expired": discord.Colour.dark_grey(),
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def expired(crew: Crew, now: datetime) -> bool:
    """An open crew that never sailed runs out at expires_at; a sailing crew that never got a voice
    channel closes a little after it sailed."""
    if crew.status == "open":
        return now >= parse(crew.expires_at)
    if crew.status == "sailing" and crew.voice_channel_id is None:
        return now >= (parse(crew.sailed_at) or parse(crew.expires_at)) + NO_VOICE_GRACE
    return False


def voice_cleanup_due(crew: Crew, members_in_voice: int, now: datetime, cleanup_minutes: int) -> bool:
    """Whether a sailing crew's voice channel has sat empty long enough to be removed."""
    if members_in_voice > 0:
        return False
    since = parse(crew.voice_empty_since) or now
    wait = timedelta(minutes=cleanup_minutes)
    if not crew.voice_occupied:
        wait = max(wait, FIRST_JOIN_GRACE)
    return now - since >= wait


def clean_title(text: str | None) -> str | None:
    """A captain's session name: single spaces, no line breaks or backticks, at most 60 characters."""
    if not text:
        return None
    cleaned = " ".join(text.replace("`", "'").split())[:60].strip()
    return cleaned or None


def voice_channel_name(profile: GameProfile, size_label: str, captain_name: str, emoji: str | None = None,
                       title: str | None = None) -> str:
    """In the server's style: "⛵ | Boxer's Sloop", "🪖 | Boxer's Helldivers", or "⛵ | Fort Night"
    when the captain named the session."""
    emoji = emoji or default_for(profile, size_label)
    if title:
        return f"{emoji} | {title}"[:100]
    return f"{emoji} | {captain_name}'s {channel_subject(profile, size_label)}"[:100]


def render_card(crew: Crew, profile: GameProfile, emoji: str | None = None) -> discord.Embed:
    emoji = emoji or default_for(profile, crew.size_label)
    if profile.open_ended:
        return _render_hangout(crew, profile, emoji)
    seats = []
    for i in range(crew.capacity):
        if i < len(crew.members):
            role = " (captain)" if crew.members[i] == crew.captain_id else ""
            seats.append(f"{i + 1}. <@{crew.members[i]}>{role}")
        else:
            seats.append(f"{i + 1}. *open seat*")
    title = f"{emoji} {crew.title}" if crew.title else f"{emoji} {profile.name}: {crew.size_label}"
    embed = discord.Embed(title=title, colour=STATUS_COLOUR.get(crew.status, discord.Colour.default()))
    if crew.title:
        embed.description = f"{profile.name}: {crew.size_label}"
    embed.add_field(name="Status", value=STATUS_LABEL.get(crew.status, crew.status), inline=True)
    embed.add_field(name="Crew", value=f"{len(crew.members)} / {crew.capacity}", inline=True)
    if crew.activity:
        embed.add_field(name="Activity", value=crew.activity, inline=True)
    embed.add_field(name="Seats", value="\n".join(seats), inline=False)
    if crew.note:
        embed.add_field(name="Captain's note", value=crew.note[:1024], inline=False)
    if crew.status == "sailing" and crew.voice_channel_id:
        embed.add_field(name="Voice", value=f"<#{crew.voice_channel_id}>", inline=False)
    if crew.status == "open":
        expires = int(parse(crew.expires_at).timestamp())
        embed.set_footer(text="Join below. The captain can set sail any time; a full crew sails itself.")
        embed.add_field(name="Leaves port by", value=f"<t:{expires}:t> (<t:{expires}:R>)", inline=False)
    elif crew.status in ("closed", "expired"):
        embed.set_footer(text="This crew call is over. Start a new one with /crew start.")
    return embed


def _render_hangout(crew: Crew, profile: GameProfile, emoji: str) -> discord.Embed:
    """A hangout has no seats: just who's aboard, however many that is."""
    embed = discord.Embed(title=f"{emoji} {crew.title or profile.name}", colour=STATUS_COLOUR.get(crew.status, discord.Colour.default()))
    embed.add_field(name="Status", value="Open" if crew.active else STATUS_LABEL.get(crew.status, crew.status),
                    inline=True)
    embed.add_field(name="Aboard", value=str(len(crew.members)), inline=True)
    if crew.activity:
        embed.add_field(name="Vibe", value=crew.activity, inline=True)
    names = [f"<@{m}>" + (" (host)" if m == crew.captain_id else "") for m in crew.members]
    listing = "\n".join(names)
    if len(listing) > 1000:
        listing = listing[:1000].rsplit("\n", 1)[0] + "\n…and more"
    embed.add_field(name="Who's here", value=listing or "Nobody yet", inline=False)
    if crew.note:
        embed.add_field(name="Host's note", value=crew.note[:1024], inline=False)
    if crew.active and crew.voice_channel_id:
        embed.add_field(name="Voice", value=f"<#{crew.voice_channel_id}>", inline=False)
        embed.set_footer(text="Everyone plays their own thing. Press Join and hop in!")
    elif not crew.active:
        embed.set_footer(text="This hangout is over. Start a new one with /crew start.")
    return embed
