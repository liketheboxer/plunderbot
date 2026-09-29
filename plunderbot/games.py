"""Game profiles: the games Brimstone Hill plays, with each one's crew sizes and activity tags,
plus the open-ended 1 Player Hangout for parallel play.

Profiles live in code for now and ship with each release. Per-server choices (the LFG ping
role for a game) live in the database. Phase 8's admin screens will make these editable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CrewSize:
    label: str
    capacity: int


@dataclass(frozen=True)
class GameProfile:
    key: str
    name: str
    short: str  # used in voice channel names
    sizes: tuple[CrewSize, ...]
    tags: tuple[str, ...]
    open_ended: bool = False  # no crew size: a hangout anyone can join, with its voice channel up at once
    crew_call: bool = True    # offered in /crew start (False: only used by Voyages)

    @property
    def default_size(self) -> CrewSize:
        return self.sizes[-1]

    def size(self, label: str | None) -> CrewSize | None:
        if not label:
            return self.default_size
        for s in self.sizes:
            if s.label.lower() == label.lower():
                return s
        return None

    def matches_role_name(self, role_name: str) -> bool:
        """Whether a server role is this game's ping role, ignoring case, spaces and punctuation
        ("Plate Up!" matches PlateUp!, "Helldivers" matches Helldivers 2)."""
        wanted = {normalise(self.name), normalise(self.short), self.key}
        return normalise(role_name) in wanted

    def tag(self, value: str | None) -> str | None:
        """The canonical spelling of a tag, or None if it isn't one of this game's tags."""
        if not value:
            return None
        for t in self.tags:
            if t.lower() == value.lower():
                return t
        return None


# Seats for an open-ended hangout. Never reached in practice; there's no user limit on its voice channel.
OPEN_CAPACITY = 99


def _upto(n: int, low: int = 2) -> tuple[CrewSize, ...]:
    return tuple(CrewSize(f"{k} players", k) for k in range(low, n + 1))


GAMES: tuple[GameProfile, ...] = (
    GameProfile("sot", "Sea of Thieves", "Sea of Thieves",
                (CrewSize("Sloop", 2), CrewSize("Brigantine", 3), CrewSize("Galleon", 4)),
                ("Adventure", "Hourglass", "Tall Tales", "Fort", "World Events", "Safer Seas", "Just Sailing")),
    GameProfile("aletale", "Ale & Tale Tavern", "Ale & Tale", _upto(4),
                ("Run the tavern", "Adventuring", "Fishing and hunting", "Quests")),
    GameProfile("nms", "No Man's Sky", "No Man's Sky", _upto(4),
                ("Expedition", "Base building", "Exploring", "Missions")),
    GameProfile("fortnite", "Fortnite", "Fortnite",
                (CrewSize("Duo", 2), CrewSize("Trio", 3), CrewSize("Squad", 4)),
                ("Battle Royale", "Zero Build", "Reload", "Creative", "LEGO")),
    GameProfile("voidcrew", "Void Crew", "Void Crew", _upto(4), ("Campaign", "Endless", "Just flying")),
    GameProfile("borderlands", "Borderlands", "Borderlands", _upto(4), ("Story", "Farming", "Endgame")),
    GameProfile("jumpspace", "Jump Space", "Jump Space", _upto(4), ("Missions", "Just flying")),
    GameProfile("artemis", "Artemis Starship Bridge Simulator", "Artemis", _upto(6), ("Mission", "Skirmish")),
    GameProfile("drg", "Deep Rock Galactic", "Deep Rock", _upto(4), ("Missions", "Deep Dives", "Promotion grind")),
    GameProfile("plateup", "PlateUp!", "PlateUp!", _upto(4), ("New run", "Franchise", "Challenge")),
    GameProfile("anacrusis", "The Anacrusis", "Anacrusis", _upto(4), ("Campaign",)),
    GameProfile("helldivers", "Helldivers 2", "Helldivers", _upto(4),
                ("Major Order", "Bug front", "Bot front", "Squid front", "Farming")),
    GameProfile("rivals", "Marvel Rivals", "Rivals", (CrewSize("Team", 6),), ("Quick Match", "Competitive", "Arcade")),
    GameProfile("lol", "League of Legends", "League",
                (CrewSize("Duo", 2), CrewSize("Flex", 5)), ("Normals", "Ranked", "ARAM", "Arena")),
    GameProfile("lethal", "Lethal Company", "Lethal Company", _upto(4), ("Quota run",)),
    GameProfile("hangout", "1 Player Hangout", "Hangout", (CrewSize("Hangout", OPEN_CAPACITY),),
                ("Parallel play", "Just chatting", "Watch party"), open_ended=True),
    GameProfile("event", "Server event", "Event", (CrewSize("Event", OPEN_CAPACITY),),
                ("Movie night", "Game night", "Meeting", "Hangout"), open_ended=True, crew_call=False),
)

BY_KEY: dict[str, GameProfile] = {g.key: g for g in GAMES}


def normalise(text: str) -> str:
    """Lower case, "&" read as "and", everything but letters and digits dropped."""
    return re.sub(r"[^a-z0-9]", "", text.lower().replace("&", "and"))


def get(key: str | None) -> GameProfile | None:
    return BY_KEY.get(key or "")
