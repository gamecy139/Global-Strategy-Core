"""
SQLite store for per-guild game sessions, speed, tick clock, investments,
country assignments, and paused research.
All data persists across bot restarts.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager

DB_PATH = "bot_state.db"

SPEED_OPTIONS: list[dict] = [
    {"label": "⏸  Paused",          "value": "paused", "desc": "Time is frozen."},
    {"label": "🐢  Slow (1×)",       "value": "1x",     "desc": "1 game-day per real minute."},
    {"label": "🚶  Normal (2×)",     "value": "2x",     "desc": "1 game-day per 30 real seconds."},
    {"label": "🏃  Fast (3×)",       "value": "3x",     "desc": "1 game-day per 20 real seconds."},
    {"label": "⚡  Very Fast (4×)",  "value": "4x",     "desc": "1 game-day per 15 real seconds."},
    {"label": "🔥  Maximum (5×)",    "value": "5x",     "desc": "1 game-day per 10 real seconds."},
]
DEFAULT_SPEED = "1x"

SPEED_SECS_PER_DAY: dict[str, float] = {
    "paused": 0.0,
    "1x":    60.0,
    "2x":    30.0,
    "3x":    20.0,
    "4x":    15.0,
    "5x":    10.0,
}

GAME_START_YEAR    = 1910
DAYS_PER_MONTH     = 30
MONTHS_PER_YEAR    = 12
DAYS_PER_YEAR      = 360
MONTH_NAMES        = [
    "January","February","March","April","May","June",
    "July","August","September","October","November","December",
]

BASE_GROWTH_RATE   = 0.6
MAX_GROWTH_RATE    = 2.0
GROWTH_STEP        = 0.05
BASE_INVEST_COST   = 20.0


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


def _add_col_if_missing(con: sqlite3.Connection, table: str,
                         col: str, typedef: str) -> None:
    cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    if col not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")


def init() -> None:
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS game_sessions (
                guild_id         TEXT NOT NULL PRIMARY KEY,
                scenario_id      TEXT NOT NULL DEFAULT 'ww1',
                channel_id       TEXT NOT NULL,
                started_at       INTEGER NOT NULL,
                game_speed       TEXT NOT NULL DEFAULT '1x',
                game_day         INTEGER NOT NULL DEFAULT 0,
                last_tick_real_s REAL NOT NULL DEFAULT 0.0
            )
        """)
        _add_col_if_missing(con, "game_sessions", "game_speed",       "TEXT NOT NULL DEFAULT '1x'")
        _add_col_if_missing(con, "game_sessions", "game_day",         "INTEGER NOT NULL DEFAULT 0")
        _add_col_if_missing(con, "game_sessions", "last_tick_real_s", "REAL NOT NULL DEFAULT 0.0")

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
        con.execute("""
            CREATE TABLE IF NOT EXISTS country_investments (
                guild_id          TEXT NOT NULL,
                country_id        TEXT NOT NULL,
                growth_bonus      REAL NOT NULL DEFAULT 0.0,
                next_invest_cost  REAL NOT NULL DEFAULT 20.0,
                PRIMARY KEY (guild_id, country_id)
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS paused_research (
                guild_id        TEXT NOT NULL,
                country_id      TEXT NOT NULL,
                research_id     TEXT NOT NULL,
                research_type   TEXT NOT NULL DEFAULT 'tech',
                remaining_days  INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, country_id, research_id)
            )
        """)


# ── Calendar helpers ──────────────────────────────────────────────────────────

def game_date_str(game_day: int) -> str:
    day_of_month = (game_day % DAYS_PER_MONTH) + 1
    month_idx    = (game_day // DAYS_PER_MONTH) % MONTHS_PER_YEAR
    year         = GAME_START_YEAR + game_day // DAYS_PER_YEAR
    return f"{day_of_month} {MONTH_NAMES[month_idx]}, {year}"


def game_year_from_day(game_day: int) -> int:
    return GAME_START_YEAR + game_day // DAYS_PER_YEAR


# ── Session helpers ───────────────────────────────────────────────────────────

def start_game(guild_id: str, channel_id: str, scenario_id: str = "ww1") -> None:
    now = time.time()
    with _conn() as con:
        con.execute("""
            INSERT INTO game_sessions
                (guild_id, scenario_id, channel_id, started_at, game_speed, game_day, last_tick_real_s)
            VALUES (?, ?, ?, ?, '1x', 0, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                scenario_id      = excluded.scenario_id,
                channel_id       = excluded.channel_id,
                started_at       = excluded.started_at,
                game_speed       = '1x',
                game_day         = 0,
                last_tick_real_s = excluded.last_tick_real_s
        """, (guild_id, scenario_id, channel_id, int(now), now))


def get_session(guild_id: str) -> sqlite3.Row | None:
    with _conn() as con:
        return con.execute(
            "SELECT * FROM game_sessions WHERE guild_id=?", (guild_id,)
        ).fetchone()


def is_game_running(guild_id: str) -> bool:
    return get_session(guild_id) is not None


def get_all_sessions() -> list[sqlite3.Row]:
    with _conn() as con:
        return con.execute("SELECT * FROM game_sessions").fetchall()


def set_speed(guild_id: str, speed_value: str) -> None:
    now = time.time()
    with _conn() as con:
        con.execute(
            "UPDATE game_sessions SET game_speed=?, last_tick_real_s=? WHERE guild_id=?",
            (speed_value, now, guild_id),
        )


def get_speed(guild_id: str) -> str:
    row = get_session(guild_id)
    return row["game_speed"] if row else DEFAULT_SPEED


def get_game_day(guild_id: str) -> int:
    row = get_session(guild_id)
    return row["game_day"] if row else 0


def get_game_date(guild_id: str) -> str:
    return game_date_str(get_game_day(guild_id))


def get_game_year(guild_id: str) -> int:
    return game_year_from_day(get_game_day(guild_id))


def advance_tick(guild_id: str) -> tuple[int, int]:
    """
    Compute how many game days have elapsed since the last tick.
    Returns (days_advanced, new_game_day).
    """
    now = time.time()
    row = get_session(guild_id)
    if row is None:
        return 0, 0

    speed        = row["game_speed"]
    secs_per_day = SPEED_SECS_PER_DAY.get(speed, 0.0)
    last_tick    = row["last_tick_real_s"] or now
    game_day     = row["game_day"]

    if secs_per_day <= 0.0:
        with _conn() as con:
            con.execute(
                "UPDATE game_sessions SET last_tick_real_s=? WHERE guild_id=?",
                (now, guild_id),
            )
        return 0, game_day

    elapsed_secs  = now - last_tick
    days_advanced = int(elapsed_secs / secs_per_day)

    if days_advanced <= 0:
        return 0, game_day

    new_day  = game_day + days_advanced
    new_last = last_tick + days_advanced * secs_per_day

    with _conn() as con:
        con.execute(
            "UPDATE game_sessions SET game_day=?, last_tick_real_s=? WHERE guild_id=?",
            (new_day, new_last, guild_id),
        )
    return days_advanced, new_day


def reset_all_tick_clocks() -> None:
    """
    Call on bot startup — sets last_tick_real_s to NOW for every active
    session so offline time does not accumulate as game-days.
    """
    now = time.time()
    with _conn() as con:
        con.execute("UPDATE game_sessions SET last_tick_real_s=?", (now,))


def reset_guild_game(guild_id: str) -> None:
    """Wipe all game state for a single guild (does NOT touch ww1_scenario.db)."""
    with _conn() as con:
        con.execute("DELETE FROM game_sessions        WHERE guild_id=?", (guild_id,))
        con.execute("DELETE FROM country_assignments  WHERE guild_id=?", (guild_id,))
        con.execute("DELETE FROM user_country         WHERE guild_id=?", (guild_id,))
        con.execute("DELETE FROM country_investments  WHERE guild_id=?", (guild_id,))
        con.execute("DELETE FROM paused_research      WHERE guild_id=?", (guild_id,))


# ── Country assignment helpers ────────────────────────────────────────────────

def assign_country(guild_id: str, country_id: str,
                   user_id: str, user_name: str) -> str | None:
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


def get_country_owner_id(guild_id: str, country_id: str) -> str | None:
    """Return the user_id of the player controlling country_id, or None."""
    with _conn() as con:
        row = con.execute(
            "SELECT user_id FROM country_assignments WHERE guild_id=? AND country_id=?",
            (guild_id, country_id),
        ).fetchone()
    return row["user_id"] if row else None


# ── Investment helpers ────────────────────────────────────────────────────────

def get_investment(guild_id: str, country_id: str) -> dict:
    with _conn() as con:
        row = con.execute(
            "SELECT growth_bonus, next_invest_cost FROM country_investments "
            "WHERE guild_id=? AND country_id=?",
            (guild_id, country_id),
        ).fetchone()
    if row:
        return {"growth_bonus": row["growth_bonus"], "next_invest_cost": row["next_invest_cost"]}
    return {"growth_bonus": 0.0, "next_invest_cost": BASE_INVEST_COST}


def save_investment(guild_id: str, country_id: str,
                    growth_bonus: float, next_invest_cost: float) -> None:
    with _conn() as con:
        con.execute("""
            INSERT INTO country_investments (guild_id, country_id, growth_bonus, next_invest_cost)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, country_id) DO UPDATE SET
                growth_bonus     = excluded.growth_bonus,
                next_invest_cost = excluded.next_invest_cost
        """, (guild_id, country_id, growth_bonus, next_invest_cost))


# ── Paused research helpers ───────────────────────────────────────────────────

def save_paused_research(guild_id: str, country_id: str,
                          research_id: str, research_type: str,
                          remaining_days: int) -> None:
    with _conn() as con:
        con.execute("""
            INSERT INTO paused_research
                (guild_id, country_id, research_id, research_type, remaining_days)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, country_id, research_id) DO UPDATE SET
                research_type  = excluded.research_type,
                remaining_days = excluded.remaining_days
        """, (guild_id, country_id, research_id, research_type, remaining_days))


def get_paused_research(guild_id: str, country_id: str,
                         research_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM paused_research "
            "WHERE guild_id=? AND country_id=? AND research_id=?",
            (guild_id, country_id, research_id),
        ).fetchone()
    return dict(row) if row else None


def clear_paused_research(guild_id: str, country_id: str, research_id: str) -> None:
    with _conn() as con:
        con.execute(
            "DELETE FROM paused_research "
            "WHERE guild_id=? AND country_id=? AND research_id=?",
            (guild_id, country_id, research_id),
        )
