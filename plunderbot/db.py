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


_SETTING_COLUMNS = {"timezone", "birthday_channel_id", "birthday_hour", "birthday_role_id",
                    "birthday_last_announced", "crew_category_id", "crew_cleanup_minutes",
                    "crew_expire_minutes"}


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
    members: list[int] = field(default_factory=list)  # join order, captain first

    @property
    def active(self) -> bool:
        return self.status in ("open", "sailing")

    @property
    def full(self) -> bool:
        return len(self.members) >= self.capacity


_CREW_COLUMNS = {"message_id", "status", "voice_channel_id", "voice_empty_since", "voice_occupied",
                 "sailed_at", "ended_at"}


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
                          created_at: str, expires_at: str) -> Crew:
        cur = await self.conn.execute(
            "INSERT INTO crews (guild_id, channel_id, captain_id, game_key, size_label, capacity, activity, "
            "note, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, channel_id, captain_id, game_key, size_label, capacity, activity, note,
             created_at, expires_at))
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
