"""The SQLite database in /data, and its migrations.

Every schema change is a new entry at the end of MIGRATIONS. Never edit one that has
shipped: existing databases have already run it. Migrations run in order at startup and
each is recorded in schema_version, so a refit upgrades the data in place.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import aiosqlite

log = logging.getLogger("plunderbot.db")

MIGRATIONS: list[str] = [
    # 1: per-server settings and birthdays
    """
    CREATE TABLE guild_settings (
        guild_id                INTEGER PRIMARY KEY,
        timezone                TEXT,
        birthday_channel_id     INTEGER,
        birthday_hour           INTEGER NOT NULL DEFAULT 9,
        birthday_role_id        INTEGER,
        birthday_last_announced TEXT
    );
    CREATE TABLE birthdays (
        guild_id INTEGER NOT NULL,
        user_id  INTEGER NOT NULL,
        month    INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
        day      INTEGER NOT NULL CHECK (day BETWEEN 1 AND 31),
        set_at   TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (guild_id, user_id)
    );
    CREATE INDEX birthdays_by_date ON birthdays (guild_id, month, day);
    CREATE TABLE birthday_role_grants (
        guild_id   INTEGER NOT NULL,
        user_id    INTEGER NOT NULL,
        role_id    INTEGER NOT NULL,
        granted_on TEXT NOT NULL,
        PRIMARY KEY (guild_id, user_id)
    );
    """,
    # 2: when each member last changed their birthday (kept after removal, so remove-and-re-add
    # can't dodge the change limit)
    """
    CREATE TABLE birthday_changes (
        guild_id   INTEGER NOT NULL,
        user_id    INTEGER NOT NULL,
        changed_at TEXT NOT NULL,
        PRIMARY KEY (guild_id, user_id)
    );
    """,
    # 3: Crew Call
    """
    ALTER TABLE guild_settings ADD COLUMN crew_category_id INTEGER;
    ALTER TABLE guild_settings ADD COLUMN crew_cleanup_minutes INTEGER NOT NULL DEFAULT 5;
    ALTER TABLE guild_settings ADD COLUMN crew_expire_minutes INTEGER NOT NULL DEFAULT 60;
    CREATE TABLE game_settings (
        guild_id     INTEGER NOT NULL,
        game_key     TEXT NOT NULL,
        ping_role_id INTEGER,
        PRIMARY KEY (guild_id, game_key)
    );
    CREATE TABLE crews (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id          INTEGER NOT NULL,
        channel_id        INTEGER NOT NULL,
        message_id        INTEGER,
        captain_id        INTEGER NOT NULL,
        game_key          TEXT NOT NULL,
        size_label        TEXT NOT NULL,
        capacity          INTEGER NOT NULL,
        activity          TEXT,
        note              TEXT,
        status            TEXT NOT NULL DEFAULT 'open',  -- open, sailing, closed, expired
        voice_channel_id  INTEGER,
        voice_empty_since TEXT,
        voice_occupied    INTEGER NOT NULL DEFAULT 0,
        created_at        TEXT NOT NULL,
        expires_at        TEXT NOT NULL,
        sailed_at         TEXT,
        ended_at          TEXT
    );
    CREATE INDEX crews_active ON crews (status);
    CREATE TABLE crew_members (
        crew_id   INTEGER NOT NULL REFERENCES crews (id) ON DELETE CASCADE,
        user_id   INTEGER NOT NULL,
        joined_at TEXT NOT NULL,
        PRIMARY KEY (crew_id, user_id)
    );
    """,
    # 4: per-game (and per-size) emoji for crew cards and voice channels
    """
    CREATE TABLE crew_emoji (
        guild_id       INTEGER NOT NULL,
        game_key       TEXT NOT NULL,
        size_label     TEXT NOT NULL DEFAULT '',  -- '' = every size of the game
        standard_emoji TEXT,                      -- used in channel names (and cards)
        server_emoji   TEXT,                      -- <:name:id>, cards only
        PRIMARY KEY (guild_id, game_key, size_label)
    );
    """,
    # 5: a name the captain gives the session ("Boxer's Fort Night")
    """
    ALTER TABLE crews ADD COLUMN title TEXT;
    """,
    # 6: Voyages (scheduled sessions) and their RSVPs
    """
    ALTER TABLE guild_settings ADD COLUMN voyage_channel_id INTEGER;
    CREATE TABLE voyages (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id       INTEGER NOT NULL,
        channel_id     INTEGER NOT NULL,
        message_id     INTEGER,
        organizer_id   INTEGER NOT NULL,
        title          TEXT NOT NULL,
        description    TEXT,
        game_key       TEXT,
        size_label     TEXT,
        capacity       INTEGER,                  -- NULL = no limit
        starts_at      TEXT NOT NULL,
        duration_min   INTEGER NOT NULL DEFAULT 120,
        reminders      TEXT NOT NULL DEFAULT '1440,60',
        reminders_sent TEXT NOT NULL DEFAULT '',
        repeat         TEXT NOT NULL DEFAULT 'none',
        series_id      INTEGER,
        status         TEXT NOT NULL DEFAULT 'scheduled',  -- scheduled, started, ended, cancelled
        event_id       INTEGER,
        crew_id        INTEGER,
        created_at     TEXT NOT NULL
    );
    CREATE INDEX voyages_status ON voyages (status, starts_at);
    CREATE TABLE voyage_rsvps (
        voyage_id  INTEGER NOT NULL REFERENCES voyages (id) ON DELETE CASCADE,
        user_id    INTEGER NOT NULL,
        status     TEXT NOT NULL,   -- aboard, maybe, cant, waitlist
        updated_at TEXT NOT NULL,
        PRIMARY KEY (voyage_id, user_id)
    );
    """,
    # 7: one channel for every crew card (crew calls and voyages that set sail)
    """
    ALTER TABLE guild_settings ADD COLUMN crew_channel_id INTEGER;
    """,
    # 8: each member's own time zone, used to read the times they type
    """
    CREATE TABLE member_timezones (
        user_id  INTEGER PRIMARY KEY,
        timezone TEXT NOT NULL
    );
    """,
    # 9: region roles stand for time zones; remember whether a member's zone came from one
    """
    ALTER TABLE member_timezones ADD COLUMN source TEXT NOT NULL DEFAULT 'manual';
    CREATE TABLE region_zones (
        guild_id INTEGER NOT NULL,
        role_id  INTEGER NOT NULL,
        timezone TEXT NOT NULL,
        PRIMARY KEY (guild_id, role_id)
    );
    """,
    # 10: Gangplank, the airlock in #introductions
    """
    ALTER TABLE guild_settings ADD COLUMN gangplank_enabled INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE guild_settings ADD COLUMN intro_channel_id INTEGER;
    ALTER TABLE guild_settings ADD COLUMN pending_role_id INTEGER;
    ALTER TABLE guild_settings ADD COLUMN harbormaster_role_id INTEGER;
    ALTER TABLE guild_settings ADD COLUMN rules_channel_id INTEGER;
    ALTER TABLE guild_settings ADD COLUMN orientation_channel_id INTEGER;
    ALTER TABLE guild_settings ADD COLUMN gangplank_alert_channel_id INTEGER;
    ALTER TABLE guild_settings ADD COLUMN approve_emoji TEXT;
    ALTER TABLE guild_settings ADD COLUMN reject_emoji TEXT;
    ALTER TABLE guild_settings ADD COLUMN gangplank_remind_days INTEGER NOT NULL DEFAULT 3;
    ALTER TABLE guild_settings ADD COLUMN gangplank_kick_days INTEGER NOT NULL DEFAULT 7;
    CREATE TABLE gangplank (
        guild_id          INTEGER NOT NULL,
        user_id           INTEGER NOT NULL,
        joined_at         TEXT NOT NULL,
        prompt_message_id INTEGER,
        responded_at      TEXT,
        reminded_at       TEXT,
        PRIMARY KEY (guild_id, user_id)
    );
    """,
    # 11: a picture on voyage and crew cards (a file name under /data/images)
    """
    ALTER TABLE voyages ADD COLUMN image TEXT;
    ALTER TABLE crews ADD COLUMN image TEXT;
    ALTER TABLE voyages ADD COLUMN ping_role TEXT NOT NULL DEFAULT 'posted';
    """,
    # 12: Colours (role menus), Notice Board pages, the Game Index
    """
    CREATE TABLE role_menus (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id    INTEGER NOT NULL,
        key         TEXT NOT NULL,
        title       TEXT NOT NULL,
        description TEXT,
        mode        TEXT NOT NULL DEFAULT 'multi',
        channel_id  INTEGER,
        message_id  INTEGER,
        onboarding  INTEGER NOT NULL DEFAULT 0,
        position    INTEGER NOT NULL DEFAULT 0,
        UNIQUE (guild_id, key)
    );
    CREATE TABLE role_menu_options (
        menu_id     INTEGER NOT NULL REFERENCES role_menus(id) ON DELETE CASCADE,
        role_id     INTEGER NOT NULL,
        emoji       TEXT,
        label       TEXT,
        description TEXT,
        position    INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (menu_id, role_id)
    );
    CREATE TABLE pages (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id    INTEGER NOT NULL,
        key         TEXT NOT NULL,
        title       TEXT NOT NULL,
        kind        TEXT NOT NULL DEFAULT 'custom',
        channel_id  INTEGER,
        message_ids TEXT NOT NULL DEFAULT '',
        UNIQUE (guild_id, key)
    );
    CREATE TABLE page_sections (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        page_id  INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        heading  TEXT,
        body     TEXT,
        colour   INTEGER,
        image    TEXT
    );
    ALTER TABLE guild_settings ADD COLUMN forum_channel_id INTEGER;
    """,
    # 13: a section's picture can sit above it as a banner instead of inside it
    """
    ALTER TABLE page_sections ADD COLUMN image_style TEXT NOT NULL DEFAULT 'inside';
    """,
]


@dataclass
class GuildSettings:
    guild_id: int
    timezone: str | None = None
    birthday_channel_id: int | None = None
    birthday_hour: int = 9
    birthday_role_id: int | None = None
    birthday_last_announced: str | None = None
    crew_category_id: int | None = None
    crew_cleanup_minutes: int = 5
    crew_expire_minutes: int = 60
    voyage_channel_id: int | None = None
    crew_channel_id: int | None = None
    gangplank_enabled: int = 0
    intro_channel_id: int | None = None
    pending_role_id: int | None = None
    harbormaster_role_id: int | None = None
    rules_channel_id: int | None = None
    orientation_channel_id: int | None = None
    gangplank_alert_channel_id: int | None = None
    approve_emoji: str | None = None
    reject_emoji: str | None = None
    gangplank_remind_days: int = 3
    gangplank_kick_days: int = 7
    forum_channel_id: int | None = None


@dataclass
class MenuOption:
    role_id: int
    emoji: str | None = None
    label: str | None = None
    description: str | None = None
    position: int = 0


@dataclass
class RoleMenu:
    id: int
    guild_id: int
    key: str
    title: str
    description: str | None = None
    mode: str = "multi"  # multi: any number; single: one at most
    channel_id: int | None = None
    message_id: int | None = None
    onboarding: int = 0  # offered to newcomers when they're let aboard
    position: int = 0
    options: list[MenuOption] = field(default_factory=list)


@dataclass
class PageSection:
    id: int
    page_id: int
    position: int
    heading: str | None = None
    body: str | None = None
    colour: int | None = None
    image: str | None = None
    image_style: str = "inside"  # inside: at the bottom of the section; banner: on its own, above it


@dataclass
class Page:
    id: int
    guild_id: int
    key: str
    title: str
    kind: str = "custom"  # custom | game_index
    channel_id: int | None = None
    message_ids: str = ""
    sections: list[PageSection] = field(default_factory=list)

    @property
    def messages(self) -> list[int]:
        return [int(x) for x in self.message_ids.split(",") if x]


@dataclass
class Boarding:
    """A newcomer waiting on the gangplank."""
    guild_id: int
    user_id: int
    joined_at: str
    prompt_message_id: int | None = None
    responded_at: str | None = None
    reminded_at: str | None = None


_SETTING_COLUMNS = {"forum_channel_id", "gangplank_enabled", "intro_channel_id", "pending_role_id", "harbormaster_role_id",
                    "rules_channel_id", "orientation_channel_id", "gangplank_alert_channel_id",
                    "approve_emoji", "reject_emoji", "gangplank_remind_days", "gangplank_kick_days",
                    "timezone", "birthday_channel_id", "birthday_hour", "birthday_role_id",
                    "birthday_last_announced", "crew_category_id", "crew_cleanup_minutes",
                    "crew_expire_minutes", "voyage_channel_id", "crew_channel_id"}


@dataclass
class Voyage:
    id: int
    guild_id: int
    channel_id: int
    message_id: int | None
    organizer_id: int
    title: str
    description: str | None
    game_key: str | None
    size_label: str | None
    capacity: int | None
    starts_at: str
    duration_min: int
    reminders: str
    reminders_sent: str
    repeat: str
    series_id: int | None
    status: str
    event_id: int | None
    crew_id: int | None
    created_at: str
    image: str | None = None
    ping_role: str = "posted"  # off | posted | reminders: when the game's ping role is tagged

    @property
    def reminder_minutes(self) -> list[int]:
        return [int(x) for x in self.reminders.split(",") if x]

    @property
    def sent_minutes(self) -> list[int]:
        return [int(x) for x in self.reminders_sent.split(",") if x]


_VOYAGE_COLUMNS = {"channel_id", "message_id", "title", "description", "game_key", "size_label", "capacity",
                   "starts_at", "duration_min", "reminders", "reminders_sent", "repeat", "series_id", "status",
                   "event_id", "crew_id", "image", "ping_role"}


@dataclass
class Crew:
    id: int
    guild_id: int
    channel_id: int
    message_id: int | None
    captain_id: int
    game_key: str
    size_label: str
    capacity: int
    activity: str | None
    note: str | None
    status: str
    voice_channel_id: int | None
    voice_empty_since: str | None
    voice_occupied: int
    created_at: str
    expires_at: str
    sailed_at: str | None
    ended_at: str | None
    title: str | None = None
    image: str | None = None
    members: list[int] = field(default_factory=list)  # join order, captain first

    @property
    def active(self) -> bool:
        return self.status in ("open", "sailing")

    @property
    def full(self) -> bool:
        return len(self.members) >= self.capacity


_CREW_COLUMNS = {"message_id", "status", "voice_channel_id", "voice_empty_since", "voice_occupied",
                 "sailed_at", "ended_at", "title", "image"}


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA foreign_keys = ON")
        await self.conn.execute("PRAGMA journal_mode = WAL")
        await self.migrate()

    async def close(self) -> None:
        if self.conn is not None:
            await self.conn.close()
            self.conn = None

    async def migrate(self) -> int:
        """Run any migrations this database hasn't seen. Returns the schema version."""
        c = self.conn
        await c.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = await (await c.execute("SELECT MAX(version) FROM schema_version")).fetchone()
        current = row[0] or 0
        for number, sql in enumerate(MIGRATIONS, start=1):
            if number <= current:
                continue
            log.info("Applying database migration %s", number)
            await c.executescript(f"BEGIN;\n{sql}\nINSERT INTO schema_version VALUES ({number});\nCOMMIT;")
            current = number
        return current

    # ------------------------------------------------------------ settings
    async def get_settings(self, guild_id: int) -> GuildSettings:
        row = await (await self.conn.execute(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))).fetchone()
        if row is None:
            return GuildSettings(guild_id=guild_id)
        return GuildSettings(**{k: row[k] for k in row.keys()})

    async def all_settings(self) -> list[GuildSettings]:
        rows = await (await self.conn.execute("SELECT * FROM guild_settings")).fetchall()
        return [GuildSettings(**{k: r[k] for k in r.keys()}) for r in rows]

    async def update_settings(self, guild_id: int, **values) -> GuildSettings:
        bad = set(values) - _SETTING_COLUMNS
        if bad:
            raise ValueError(f"Unknown settings: {', '.join(sorted(bad))}")
        await self.conn.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,))
        if values:
            cols = ", ".join(f"{k} = ?" for k in values)
            await self.conn.execute(f"UPDATE guild_settings SET {cols} WHERE guild_id = ?",
                                    (*values.values(), guild_id))
        await self.conn.commit()
        return await self.get_settings(guild_id)

    # ------------------------------------------------------------ birthdays
    async def set_birthday(self, guild_id: int, user_id: int, month: int, day: int) -> None:
        await self.conn.execute(
            "INSERT INTO birthdays (guild_id, user_id, month, day) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (guild_id, user_id) DO UPDATE SET month = excluded.month, day = excluded.day, "
            "set_at = datetime('now')",
            (guild_id, user_id, month, day))
        await self.conn.commit()

    async def remove_birthday(self, guild_id: int, user_id: int) -> bool:
        cur = await self.conn.execute("DELETE FROM birthdays WHERE guild_id = ? AND user_id = ?",
                                      (guild_id, user_id))
        await self.conn.commit()
        return cur.rowcount > 0

    async def get_birthday(self, guild_id: int, user_id: int) -> tuple[int, int] | None:
        row = await (await self.conn.execute(
            "SELECT month, day FROM birthdays WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id))).fetchone()
        return (row["month"], row["day"]) if row else None

    async def birthdays(self, guild_id: int) -> list[tuple[int, int, int]]:
        """Every (user_id, month, day) on this server."""
        rows = await (await self.conn.execute(
            "SELECT user_id, month, day FROM birthdays WHERE guild_id = ?", (guild_id,))).fetchall()
        return [(r["user_id"], r["month"], r["day"]) for r in rows]

    async def last_birthday_change(self, guild_id: int, user_id: int) -> str | None:
        row = await (await self.conn.execute(
            "SELECT changed_at FROM birthday_changes WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id))).fetchone()
        return row["changed_at"] if row else None

    async def record_birthday_change(self, guild_id: int, user_id: int, changed_at: str) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO birthday_changes (guild_id, user_id, changed_at) VALUES (?, ?, ?)",
            (guild_id, user_id, changed_at))
        await self.conn.commit()

    async def count_birthdays(self) -> int:
        row = await (await self.conn.execute("SELECT COUNT(*) FROM birthdays")).fetchone()
        return row[0]

    async def record_role_grant(self, guild_id: int, user_id: int, role_id: int, granted_on: str) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO birthday_role_grants (guild_id, user_id, role_id, granted_on) "
            "VALUES (?, ?, ?, ?)", (guild_id, user_id, role_id, granted_on))
        await self.conn.commit()

    async def stale_role_grants(self, guild_id: int, today: str) -> list[tuple[int, int]]:
        """(user_id, role_id) for birthday roles handed out on an earlier day."""
        rows = await (await self.conn.execute(
            "SELECT user_id, role_id FROM birthday_role_grants WHERE guild_id = ? AND granted_on < ?",
            (guild_id, today))).fetchall()
        return [(r["user_id"], r["role_id"]) for r in rows]

    async def clear_role_grant(self, guild_id: int, user_id: int) -> None:
        await self.conn.execute("DELETE FROM birthday_role_grants WHERE guild_id = ? AND user_id = ?",
                                (guild_id, user_id))
        await self.conn.commit()

    # ------------------------------------------------------------ game settings
    async def game_ping_roles(self, guild_id: int) -> dict[str, int]:
        rows = await (await self.conn.execute(
            "SELECT game_key, ping_role_id FROM game_settings WHERE guild_id = ? AND ping_role_id IS NOT NULL",
            (guild_id,))).fetchall()
        return {r["game_key"]: r["ping_role_id"] for r in rows}

    async def set_game_ping_role(self, guild_id: int, game_key: str, role_id: int | None) -> None:
        await self.conn.execute(
            "INSERT INTO game_settings (guild_id, game_key, ping_role_id) VALUES (?, ?, ?) "
            "ON CONFLICT (guild_id, game_key) DO UPDATE SET ping_role_id = excluded.ping_role_id",
            (guild_id, game_key, role_id))
        await self.conn.commit()

    # ------------------------------------------------------------ crews
    async def create_crew(self, *, guild_id: int, channel_id: int, captain_id: int, game_key: str,
                          size_label: str, capacity: int, activity: str | None, note: str | None,
                          created_at: str, expires_at: str, title: str | None = None,
                          image: str | None = None) -> Crew:
        cur = await self.conn.execute(
            "INSERT INTO crews (guild_id, channel_id, captain_id, game_key, size_label, capacity, activity, "
            "note, created_at, expires_at, title, image) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, channel_id, captain_id, game_key, size_label, capacity, activity, note,
             created_at, expires_at, title, image))
        crew_id = cur.lastrowid
        await self.conn.execute("INSERT INTO crew_members (crew_id, user_id, joined_at) VALUES (?, ?, ?)",
                                (crew_id, captain_id, created_at))
        await self.conn.commit()
        return await self.get_crew(crew_id)

    async def get_crew(self, crew_id: int) -> Crew | None:
        row = await (await self.conn.execute("SELECT * FROM crews WHERE id = ?", (crew_id,))).fetchone()
        if row is None:
            return None
        crew = Crew(**{k: row[k] for k in row.keys()})
        members = await (await self.conn.execute(
            "SELECT user_id FROM crew_members WHERE crew_id = ? ORDER BY joined_at, rowid", (crew_id,))).fetchall()
        crew.members = [m["user_id"] for m in members]
        return crew

    async def active_crews(self, guild_id: int | None = None) -> list[Crew]:
        sql = "SELECT id FROM crews WHERE status IN ('open', 'sailing')"
        args: tuple = ()
        if guild_id is not None:
            sql += " AND guild_id = ?"
            args = (guild_id,)
        rows = await (await self.conn.execute(sql + " ORDER BY id", args)).fetchall()
        return [c for c in [await self.get_crew(r["id"]) for r in rows] if c is not None]

    async def active_crew_led_by(self, guild_id: int, captain_id: int) -> Crew | None:
        row = await (await self.conn.execute(
            "SELECT id FROM crews WHERE guild_id = ? AND captain_id = ? AND status IN ('open', 'sailing') "
            "ORDER BY id DESC LIMIT 1", (guild_id, captain_id))).fetchone()
        return await self.get_crew(row["id"]) if row else None

    async def update_crew(self, crew_id: int, **values) -> Crew | None:
        bad = set(values) - _CREW_COLUMNS
        if bad:
            raise ValueError(f"Unknown crew fields: {', '.join(sorted(bad))}")
        if values:
            cols = ", ".join(f"{k} = ?" for k in values)
            await self.conn.execute(f"UPDATE crews SET {cols} WHERE id = ?", (*values.values(), crew_id))
            await self.conn.commit()
        return await self.get_crew(crew_id)

    async def add_crew_member(self, crew_id: int, user_id: int, joined_at: str) -> bool:
        """Adds the member if there's a free seat. Returns False if full, closed or already aboard.

        Callers serialise crew changes with the Crew Call cog's lock, so the check and the
        insert can't interleave with another join.
        """
        row = await (await self.conn.execute(
            "SELECT c.capacity, c.status, (SELECT COUNT(*) FROM crew_members m WHERE m.crew_id = c.id) AS n, "
            "EXISTS (SELECT 1 FROM crew_members m WHERE m.crew_id = c.id AND m.user_id = ?) AS aboard "
            "FROM crews c WHERE c.id = ?", (user_id, crew_id))).fetchone()
        if row is None or row["aboard"] or row["n"] >= row["capacity"] or row["status"] not in ("open", "sailing"):
            return False
        await self.conn.execute("INSERT INTO crew_members (crew_id, user_id, joined_at) VALUES (?, ?, ?)",
                                (crew_id, user_id, joined_at))
        await self.conn.commit()
        return True

    async def remove_crew_member(self, crew_id: int, user_id: int) -> bool:
        cur = await self.conn.execute("DELETE FROM crew_members WHERE crew_id = ? AND user_id = ?",
                                      (crew_id, user_id))
        await self.conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------ crew emoji
    async def crew_emoji(self, guild_id: int) -> dict[tuple[str, str], tuple[str | None, str | None]]:
        rows = await (await self.conn.execute(
            "SELECT game_key, size_label, standard_emoji, server_emoji FROM crew_emoji WHERE guild_id = ?",
            (guild_id,))).fetchall()
        return {(r["game_key"], r["size_label"]): (r["standard_emoji"], r["server_emoji"]) for r in rows}

    async def set_crew_emoji(self, guild_id: int, game_key: str, size_label: str, *,
                             standard: str | None = ..., server: str | None = ...) -> None:
        """Set either kind (pass None to clear it); leave the other kind as it was."""
        await self.conn.execute(
            "INSERT OR IGNORE INTO crew_emoji (guild_id, game_key, size_label) VALUES (?, ?, ?)",
            (guild_id, game_key, size_label))
        if standard is not ...:
            await self.conn.execute(
                "UPDATE crew_emoji SET standard_emoji = ? WHERE guild_id = ? AND game_key = ? AND size_label = ?",
                (standard, guild_id, game_key, size_label))
        if server is not ...:
            await self.conn.execute(
                "UPDATE crew_emoji SET server_emoji = ? WHERE guild_id = ? AND game_key = ? AND size_label = ?",
                (server, guild_id, game_key, size_label))
        await self.conn.execute(
            "DELETE FROM crew_emoji WHERE standard_emoji IS NULL AND server_emoji IS NULL")
        await self.conn.commit()

    # ------------------------------------------------------------ voyages
    async def create_voyage(self, **values) -> "Voyage":
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        cur = await self.conn.execute(f"INSERT INTO voyages ({cols}) VALUES ({marks})", tuple(values.values()))
        await self.conn.commit()
        return await self.get_voyage(cur.lastrowid)

    async def get_voyage(self, voyage_id: int) -> "Voyage | None":
        row = await (await self.conn.execute("SELECT * FROM voyages WHERE id = ?", (voyage_id,))).fetchone()
        return Voyage(**{k: row[k] for k in row.keys()}) if row else None

    async def update_voyage(self, voyage_id: int, **values) -> "Voyage | None":
        bad = set(values) - _VOYAGE_COLUMNS
        if bad:
            raise ValueError(f"Unknown voyage fields: {', '.join(sorted(bad))}")
        if values:
            cols = ", ".join(f"{k} = ?" for k in values)
            await self.conn.execute(f"UPDATE voyages SET {cols} WHERE id = ?", (*values.values(), voyage_id))
            await self.conn.commit()
        return await self.get_voyage(voyage_id)

    async def voyages_with_status(self, *statuses: str, guild_id: int | None = None) -> list["Voyage"]:
        marks = ", ".join("?" for _ in statuses)
        sql = f"SELECT * FROM voyages WHERE status IN ({marks})"
        args: list = list(statuses)
        if guild_id is not None:
            sql += " AND guild_id = ?"
            args.append(guild_id)
        rows = await (await self.conn.execute(sql + " ORDER BY starts_at, id", args)).fetchall()
        return [Voyage(**{k: r[k] for k in r.keys()}) for r in rows]

    async def voyage_by_crew(self, crew_id: int) -> "Voyage | None":
        row = await (await self.conn.execute("SELECT id FROM voyages WHERE crew_id = ?", (crew_id,))).fetchone()
        return await self.get_voyage(row["id"]) if row else None

    async def rsvps(self, voyage_id: int):
        from .voyage_logic import Rsvps
        rows = await (await self.conn.execute(
            "SELECT user_id, status FROM voyage_rsvps WHERE voyage_id = ? ORDER BY updated_at, rowid",
            (voyage_id,))).fetchall()
        out = Rsvps()
        for r in rows:
            getattr(out, r["status"]).append(r["user_id"])
        return out

    async def set_rsvp(self, voyage_id: int, user_id: int, status: str | None, at: str) -> None:
        """Record a member's answer; None removes it. Changing answer moves them to the back of that list."""
        if status is None:
            await self.conn.execute("DELETE FROM voyage_rsvps WHERE voyage_id = ? AND user_id = ?",
                                    (voyage_id, user_id))
        else:
            await self.conn.execute(
                "INSERT INTO voyage_rsvps (voyage_id, user_id, status, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (voyage_id, user_id) DO UPDATE SET status = excluded.status, "
                "updated_at = excluded.updated_at",
                (voyage_id, user_id, status, at))
        await self.conn.commit()

    # ------------------------------------------------------------ member time zones
    async def member_timezone(self, user_id: int) -> str | None:
        found = await self.member_timezone_source(user_id)
        return found[0] if found else None

    async def member_timezone_source(self, user_id: int) -> tuple[str, str] | None:
        """(zone, source) where source is "manual" or "region"."""
        row = await (await self.conn.execute(
            "SELECT timezone, source FROM member_timezones WHERE user_id = ?", (user_id,))).fetchone()
        return (row["timezone"], row["source"]) if row else None

    async def set_member_timezone(self, user_id: int, tz: str | None, source: str = "manual") -> None:
        if tz is None:
            await self.conn.execute("DELETE FROM member_timezones WHERE user_id = ?", (user_id,))
        else:
            await self.conn.execute(
                "INSERT INTO member_timezones (user_id, timezone, source) VALUES (?, ?, ?) "
                "ON CONFLICT (user_id) DO UPDATE SET timezone = excluded.timezone, source = excluded.source",
                (user_id, tz, source))
        await self.conn.commit()

    # ------------------------------------------------------------ region roles
    async def region_zones(self, guild_id: int) -> dict[int, str]:
        rows = await (await self.conn.execute(
            "SELECT role_id, timezone FROM region_zones WHERE guild_id = ?", (guild_id,))).fetchall()
        return {r["role_id"]: r["timezone"] for r in rows}

    async def set_region_zone(self, guild_id: int, role_id: int, tz: str | None) -> None:
        if tz is None:
            await self.conn.execute("DELETE FROM region_zones WHERE guild_id = ? AND role_id = ?",
                                    (guild_id, role_id))
        else:
            await self.conn.execute(
                "INSERT INTO region_zones (guild_id, role_id, timezone) VALUES (?, ?, ?) "
                "ON CONFLICT (guild_id, role_id) DO UPDATE SET timezone = excluded.timezone",
                (guild_id, role_id, tz))
        await self.conn.commit()

    # ------------------------------------------------------------ gangplank
    async def add_boarding(self, guild_id: int, user_id: int, joined_at: str,
                           prompt_message_id: int | None = None, responded_at: str | None = None) -> None:
        """Start (or restart, on a rejoin) someone's wait on the gangplank."""
        await self.conn.execute(
            "INSERT INTO gangplank (guild_id, user_id, joined_at, prompt_message_id, responded_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT (guild_id, user_id) DO UPDATE SET "
            "joined_at = excluded.joined_at, prompt_message_id = excluded.prompt_message_id, "
            "responded_at = excluded.responded_at, reminded_at = NULL",
            (guild_id, user_id, joined_at, prompt_message_id, responded_at))
        await self.conn.commit()

    async def get_boarding(self, guild_id: int, user_id: int) -> Boarding | None:
        row = await (await self.conn.execute(
            "SELECT * FROM gangplank WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))).fetchone()
        return Boarding(**{k: row[k] for k in row.keys()}) if row else None

    async def boarding_by_prompt(self, guild_id: int, message_id: int) -> Boarding | None:
        row = await (await self.conn.execute(
            "SELECT * FROM gangplank WHERE guild_id = ? AND prompt_message_id = ?",
            (guild_id, message_id))).fetchone()
        return Boarding(**{k: row[k] for k in row.keys()}) if row else None

    async def boardings(self, guild_id: int) -> list[Boarding]:
        rows = await (await self.conn.execute(
            "SELECT * FROM gangplank WHERE guild_id = ? ORDER BY joined_at", (guild_id,))).fetchall()
        return [Boarding(**{k: r[k] for k in r.keys()}) for r in rows]

    async def update_boarding(self, guild_id: int, user_id: int, **values) -> None:
        bad = set(values) - {"prompt_message_id", "responded_at", "reminded_at"}
        if bad:
            raise ValueError(f"Unknown gangplank columns: {', '.join(sorted(bad))}")
        cols = ", ".join(f"{k} = ?" for k in values)
        await self.conn.execute(f"UPDATE gangplank SET {cols} WHERE guild_id = ? AND user_id = ?",
                                (*values.values(), guild_id, user_id))
        await self.conn.commit()

    async def remove_boarding(self, guild_id: int, user_id: int) -> bool:
        cur = await self.conn.execute("DELETE FROM gangplank WHERE guild_id = ? AND user_id = ?",
                                      (guild_id, user_id))
        await self.conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------ role menus (Colours)
    async def _menu(self, row) -> RoleMenu:
        menu = RoleMenu(**{k: row[k] for k in row.keys()})
        opts = await (await self.conn.execute(
            "SELECT role_id, emoji, label, description, position FROM role_menu_options WHERE menu_id = ? "
            "ORDER BY position, rowid", (menu.id,))).fetchall()
        menu.options = [MenuOption(**{k: o[k] for k in o.keys()}) for o in opts]
        return menu

    async def create_menu(self, guild_id: int, key: str, title: str, description: str | None, mode: str) -> RoleMenu:
        row = await (await self.conn.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 AS p FROM role_menus WHERE guild_id = ?", (guild_id,))).fetchone()
        cur = await self.conn.execute(
            "INSERT INTO role_menus (guild_id, key, title, description, mode, position) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, key, title, description, mode, row["p"]))
        await self.conn.commit()
        return await self.get_menu(cur.lastrowid)

    async def get_menu(self, menu_id: int) -> RoleMenu | None:
        row = await (await self.conn.execute("SELECT * FROM role_menus WHERE id = ?", (menu_id,))).fetchone()
        return await self._menu(row) if row else None

    async def menu_by_key(self, guild_id: int, key: str) -> RoleMenu | None:
        row = await (await self.conn.execute(
            "SELECT * FROM role_menus WHERE guild_id = ? AND key = ?", (guild_id, key))).fetchone()
        return await self._menu(row) if row else None

    async def menus(self, guild_id: int) -> list[RoleMenu]:
        rows = await (await self.conn.execute(
            "SELECT * FROM role_menus WHERE guild_id = ? ORDER BY position, id", (guild_id,))).fetchall()
        return [await self._menu(r) for r in rows]

    async def update_menu(self, menu_id: int, **values) -> RoleMenu | None:
        bad = set(values) - {"key", "title", "description", "mode", "channel_id", "message_id", "onboarding",
                             "position"}
        if bad:
            raise ValueError(f"Unknown menu fields: {', '.join(sorted(bad))}")
        cols = ", ".join(f"{k} = ?" for k in values)
        await self.conn.execute(f"UPDATE role_menus SET {cols} WHERE id = ?", (*values.values(), menu_id))
        await self.conn.commit()
        return await self.get_menu(menu_id)

    async def delete_menu(self, menu_id: int) -> None:
        await self.conn.execute("DELETE FROM role_menu_options WHERE menu_id = ?", (menu_id,))
        await self.conn.execute("DELETE FROM role_menus WHERE id = ?", (menu_id,))
        await self.conn.commit()

    async def set_menu_option(self, menu_id: int, role_id: int, emoji: str | None, label: str | None,
                              description: str | None) -> None:
        row = await (await self.conn.execute(
            "SELECT position FROM role_menu_options WHERE menu_id = ? AND role_id = ?", (menu_id, role_id))).fetchone()
        if row is None:
            nxt = await (await self.conn.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 AS p FROM role_menu_options WHERE menu_id = ?",
                (menu_id,))).fetchone()
            position = nxt["p"]
        else:
            position = row["position"]
        await self.conn.execute(
            "INSERT INTO role_menu_options (menu_id, role_id, emoji, label, description, position) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (menu_id, role_id) DO UPDATE SET emoji = excluded.emoji, "
            "label = excluded.label, description = excluded.description",
            (menu_id, role_id, emoji, label, description, position))
        await self.conn.commit()

    async def remove_menu_option(self, menu_id: int, role_id: int) -> bool:
        cur = await self.conn.execute("DELETE FROM role_menu_options WHERE menu_id = ? AND role_id = ?",
                                      (menu_id, role_id))
        await self.conn.commit()
        return cur.rowcount > 0

    async def move_menu_option(self, menu_id: int, role_id: int, position: int) -> None:
        menu = await self.get_menu(menu_id)
        ids = [o.role_id for o in menu.options if o.role_id != role_id]
        ids.insert(max(0, min(position - 1, len(ids))), role_id)
        for i, rid in enumerate(ids, start=1):
            await self.conn.execute("UPDATE role_menu_options SET position = ? WHERE menu_id = ? AND role_id = ?",
                                    (i, menu_id, rid))
        await self.conn.commit()

    # ------------------------------------------------------------ Notice Board pages
    async def _page(self, row) -> Page:
        page = Page(**{k: row[k] for k in row.keys()})
        secs = await (await self.conn.execute(
            "SELECT * FROM page_sections WHERE page_id = ? ORDER BY position, id", (page.id,))).fetchall()
        page.sections = [PageSection(**{k: r[k] for k in r.keys()}) for r in secs]
        return page

    async def create_page(self, guild_id: int, key: str, title: str, kind: str = "custom") -> Page:
        cur = await self.conn.execute("INSERT INTO pages (guild_id, key, title, kind) VALUES (?, ?, ?, ?)",
                                      (guild_id, key, title, kind))
        await self.conn.commit()
        return await self.get_page(cur.lastrowid)

    async def get_page(self, page_id: int) -> Page | None:
        row = await (await self.conn.execute("SELECT * FROM pages WHERE id = ?", (page_id,))).fetchone()
        return await self._page(row) if row else None

    async def page_by_key(self, guild_id: int, key: str) -> Page | None:
        row = await (await self.conn.execute(
            "SELECT * FROM pages WHERE guild_id = ? AND key = ?", (guild_id, key))).fetchone()
        return await self._page(row) if row else None

    async def pages(self, guild_id: int) -> list[Page]:
        rows = await (await self.conn.execute(
            "SELECT * FROM pages WHERE guild_id = ? ORDER BY id", (guild_id,))).fetchall()
        return [await self._page(r) for r in rows]

    async def update_page(self, page_id: int, **values) -> Page | None:
        bad = set(values) - {"key", "title", "channel_id", "message_ids"}
        if bad:
            raise ValueError(f"Unknown page fields: {', '.join(sorted(bad))}")
        cols = ", ".join(f"{k} = ?" for k in values)
        await self.conn.execute(f"UPDATE pages SET {cols} WHERE id = ?", (*values.values(), page_id))
        await self.conn.commit()
        return await self.get_page(page_id)

    async def delete_page(self, page_id: int) -> None:
        await self.conn.execute("DELETE FROM page_sections WHERE page_id = ?", (page_id,))
        await self.conn.execute("DELETE FROM pages WHERE id = ?", (page_id,))
        await self.conn.commit()

    async def add_section(self, page_id: int, heading: str | None, body: str | None, colour: int | None = None,
                          image: str | None = None, position: int | None = None,
                          image_style: str = "inside") -> PageSection:
        page = await self.get_page(page_id)
        count = len(page.sections)
        position = count + 1 if position is None else max(1, min(position, count + 1))
        await self.conn.execute("UPDATE page_sections SET position = position + 1 WHERE page_id = ? AND position >= ?",
                                (page_id, position))
        cur = await self.conn.execute(
            "INSERT INTO page_sections (page_id, position, heading, body, colour, image, image_style) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", (page_id, position, heading, body, colour, image, image_style))
        await self.conn.commit()
        await self._renumber(page_id)
        row = await (await self.conn.execute("SELECT * FROM page_sections WHERE id = ?", (cur.lastrowid,))).fetchone()
        return PageSection(**{k: row[k] for k in row.keys()})

    async def update_section(self, section_id: int, **values) -> None:
        bad = set(values) - {"heading", "body", "colour", "image", "image_style"}
        if bad:
            raise ValueError(f"Unknown section fields: {', '.join(sorted(bad))}")
        cols = ", ".join(f"{k} = ?" for k in values)
        await self.conn.execute(f"UPDATE page_sections SET {cols} WHERE id = ?", (*values.values(), section_id))
        await self.conn.commit()

    async def remove_section(self, page_id: int, section_id: int) -> None:
        await self.conn.execute("DELETE FROM page_sections WHERE id = ? AND page_id = ?", (section_id, page_id))
        await self.conn.commit()
        await self._renumber(page_id)

    async def move_section(self, page_id: int, section_id: int, position: int) -> None:
        page = await self.get_page(page_id)
        ids = [s.id for s in page.sections if s.id != section_id]
        ids.insert(max(0, min(position - 1, len(ids))), section_id)
        for i, sid in enumerate(ids, start=1):
            await self.conn.execute("UPDATE page_sections SET position = ? WHERE id = ?", (i, sid))
        await self.conn.commit()

    async def _renumber(self, page_id: int) -> None:
        rows = await (await self.conn.execute(
            "SELECT id FROM page_sections WHERE page_id = ? ORDER BY position, id", (page_id,))).fetchall()
        for i, r in enumerate(rows, start=1):
            await self.conn.execute("UPDATE page_sections SET position = ? WHERE id = ?", (i, r["id"]))
        await self.conn.commit()
