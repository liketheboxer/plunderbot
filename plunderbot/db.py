"""The SQLite database in /data, and its migrations.

Every schema change is a new entry at the end of MIGRATIONS. Never edit one that has
shipped: existing databases have already run it. Migrations run in order at startup and
each is recorded in schema_version, so a refit upgrades the data in place.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
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
]


@dataclass
class GuildSettings:
    guild_id: int
    timezone: str | None = None
    birthday_channel_id: int | None = None
    birthday_hour: int = 9
    birthday_role_id: int | None = None
    birthday_last_announced: str | None = None


_SETTING_COLUMNS = {"timezone", "birthday_channel_id", "birthday_hour", "birthday_role_id",
                    "birthday_last_announced"}


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
