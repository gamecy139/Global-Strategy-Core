"""
SQLite store for per-guild game sessions, speed settings, and country assignments.
All data persists across bot restarts — nothing is held only in memory.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager

DB_PATH = "bot_state.db"

SPEED_OPTIONS: list[dict] = [
    {"label": "⏸  Paused",     "value": "paused",     "desc": "Time is frozen."},
    {"label": "🐢  Slow (1×)",  "value": "1x",         "desc": "1 game-day per real day."},
    {"label": "🚶  Normal (2×)", "value": "2x",         "desc": "2 game-days per real day."},
    {"label": "🏃  Fast (3×)",  "value": "3x",         "desc": "3 game-days per real day."},
    {"label": "⚡  Very Fast (4×)", "value": "4x",     "desc": "4 game-days per real day."},
    {"label": "🔥  Maximum (5×)", "value": "5x",       "desc": "5 game-days per real day."},
]
DEFAULT_SPEED = "1x"
GAME_START_YEAR = 1910


@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS game_sessions (
                guild_id    TEXT NOT NULL PRIMARY KEY,
                scenario_id TEXT NOT NULL DEFAULT 'ww1',
                channel_id  TEXT NOT NULL,
                started_at  INTEGER NOT NULL,
                game_speed  TEXT NOT NULL DEFAULT '1x',
                game_day    INTEGER NOT NULL DEFAULT 0
            )
        """)
        # Migrations for existing DBs
        _add_col_if_missing(con, "game_sessions", "game_speed", "TEXT NOT NULL DEFAULT '1x'")
        _add_col_if_missing(con, "game_sessions", "game_day",   "INTEGER NOT NULL DEFAULT 0")

        con.execute("""
            CREATE TABLE IF NOT EXISTS country_assignments (
                guild_id    TEXT NOT NULL,
                country_id  TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                user_name   TEXT NOT NULL,
                assigned_at INTEGER NOT NULL,
                PRIMARY KEY (guild_id, country_id)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS user_country (
                guild_id   TEXT NOT NULL,
                user_id    TEXT NOT NULL,
                country_id TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
        """)


def _add_col_if_missing(con: sqlite3.Connection, table: str,
                         col: str, typedef: str) -> None:
    cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    if col not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")


# ── Session helpers ───────────────────────────────────────────────────────────

def start_game(guild_id: str, channel_id: str, scenario_id: str = "ww1") -> None:
    with _conn() as con:
        con.execute("""
            INSERT INTO game_sessions
                (guild_id, scenario_id, channel_id, started_at, game_speed, game_day)
            VALUES (?, ?, ?, ?, ?, 0)
            ON CONFLICT(guild_id) DO UPDATE SET
                scenario_id = excluded.scenario_id,
                channel_id  = excluded.channel_id,
                started_at  = excluded.started_at,
                game_speed  = '1x',
                game_day    = 0
        """, (guild_id, scenario_id, channel_id, int(time.time())))


def get_session(guild_id: str) -> sqlite3.Row | None:
    with _conn() as con:
        return con.execute(
            "SELECT * FROM game_sessions WHERE guild_id = ?", (guild_id,)
        ).fetchone()


def is_game_running(guild_id: str) -> bool:
    return get_session(guild_id) is not None


def set_speed(guild_id: str, speed_value: str) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE game_sessions SET game_speed=? WHERE guild_id=?",
            (speed_value, guild_id),
        )


def get_speed(guild_id: str) -> str:
    row = get_session(guild_id)
    return row["game_speed"] if row else DEFAULT_SPEED


def get_game_year(guild_id: str) -> int:
    row = get_session(guild_id)
    day = row["game_day"] if row else 0
    return GAME_START_YEAR + (day // 365)


# ── Country assignment helpers ────────────────────────────────────────────────

def assign_country(guild_id: str, country_id: str,
                   user_id: str, user_name: str) -> str | None:
    """Returns None on success, or an error string."""
    with _conn() as con:
        existing = con.execute(
            "SELECT user_id, user_name FROM country_assignments "
            "WHERE guild_id=? AND country_id=?",
            (guild_id, country_id),
        ).fetchone()
        if existing:
            return f"**{country_id}** is already taken by **{existing['user_name']}**."

        current = con.execute(
            "SELECT country_id FROM user_country WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        ).fetchone()
        if current:
            return f"You already control **{current['country_id']}**. Release it first."

        con.execute("""
            INSERT INTO country_assignments
                (guild_id, country_id, user_id, user_name, assigned_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, country_id) DO UPDATE SET
                user_id = excluded.user_id,
                user_name = excluded.user_name,
                assigned_at = excluded.assigned_at
        """, (guild_id, country_id, user_id, user_name, int(time.time())))

        con.execute("""
            INSERT INTO user_country (guild_id, user_id, country_id)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                country_id = excluded.country_id
        """, (guild_id, user_id, country_id))
        return None


def get_assignments(guild_id: str) -> dict[str, str]:
    """Returns {country_id: user_name}."""
    with _conn() as con:
        rows = con.execute(
            "SELECT country_id, user_name FROM country_assignments WHERE guild_id=?",
            (guild_id,),
        ).fetchall()
    return {r["country_id"]: r["user_name"] for r in rows}


def get_user_country(guild_id: str, user_id: str) -> str | None:
    with _conn() as con:
        row = con.execute(
            "SELECT country_id FROM user_country WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        ).fetchone()
    return row["country_id"] if row else None
