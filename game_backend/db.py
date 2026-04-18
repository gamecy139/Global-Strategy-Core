"""
DATABASE LAYER
--------------
SQLite persistence for all per-server, per-country game state.

Tables
------
  country_state       — per-country economic, social, and military summary
  army_units          — individual army units (infantry, cavalry, etc.)
  recruitment_tracking — mass-recruitment penalty tracking
  province_state      — province ownership, core status, religion, conversions

All reads and writes are isolated by server_id so multiple Discord servers
share a single SQLite file without interfering with each other.

Usage
-----
    from game_backend.db import Database

    db = Database("game.db")   # or ":memory:" for tests/demos
    db.init()                  # creates / migrates tables
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Generator


# ---------------------------------------------------------------------------
# Default values (kept here to avoid magic numbers across system files)
# ---------------------------------------------------------------------------

DEFAULT_TREASURY:           float = 0.0
DEFAULT_DAILY_INCOME:       float = 0.0
DEFAULT_BASE_POPULATION:    int   = 1_000_000
DEFAULT_BASE_GROWTH_RATE:   float = 0.01     # 1 %/month
DEFAULT_BONUS_GROWTH_RATE:  float = 0.0
DEFAULT_RELIGION:           str   = "Atheism"
DEFAULT_TAX_LEVEL:          str   = "Standard Contribution"
DEFAULT_OPINION:            int   = 50
DEFAULT_UNREST:             float = 0.0

# Columns allowed in update_fields() for country_state
_COUNTRY_STATE_COLUMNS: frozenset[str] = frozenset({
    "treasury", "daily_income",
    "population", "growth_rate",          # legacy aliases kept for backward compat
    "base_population", "current_population",
    "base_growth_rate", "bonus_growth_rate",
    "growth_investment_count", "last_growth_investment_time",
    "population_opinion", "unrest",
    "tax_level", "total_army_size",
    "persecution_active",
    "last_riot_day", "last_rebellion_day",
    "religion",
})


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

class Database:
    """
    Central SQLite wrapper.  All CRUD for every table lives here.

    Parameters
    ----------
    db_path : str
        File path or ``":memory:"`` for an in-memory database.
        In-memory mode keeps a single persistent connection so data is not
        lost between calls (each ``connect(":memory:")`` is a fresh DB).
    """

    def __init__(self, db_path: str = "game.db") -> None:
        self.db_path = db_path
        self._mem_conn: sqlite3.Connection | None = None
        if db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.execute("PRAGMA journal_mode=WAL")
            self._mem_conn.execute("PRAGMA foreign_keys=ON")

    # ------------------------------------------------------------------
    # Setup & migration
    # ------------------------------------------------------------------

    def init(self) -> None:
        """
        Create all tables and migrate any missing columns.
        Safe to call on every startup (fully idempotent).
        """
        with self._connection() as conn:
            self._create_country_state(conn)
            self._create_army_units(conn)
            self._create_recruitment_tracking(conn)
            self._create_province_state(conn)
            self._migrate_country_state(conn)

    # ---- table DDL -------------------------------------------------------

    @staticmethod
    def _create_country_state(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS country_state (
                server_id                   TEXT    NOT NULL,
                country_id                  TEXT    NOT NULL,

                -- Economy
                treasury                    REAL    NOT NULL DEFAULT 0.0,
                daily_income                REAL    NOT NULL DEFAULT 0.0,

                -- Population (legacy columns kept for backward compat)
                population                  INTEGER NOT NULL DEFAULT 1000000,
                growth_rate                 REAL    NOT NULL DEFAULT 0.01,

                -- Population (extended)
                base_population             INTEGER NOT NULL DEFAULT 1000000,
                current_population          INTEGER NOT NULL DEFAULT 1000000,
                base_growth_rate            REAL    NOT NULL DEFAULT 0.01,
                bonus_growth_rate           REAL    NOT NULL DEFAULT 0.0,
                growth_investment_count     INTEGER NOT NULL DEFAULT 0,
                last_growth_investment_time INTEGER NOT NULL DEFAULT 0,

                -- Religion / culture
                religion                    TEXT    NOT NULL DEFAULT 'Atheism',
                persecution_active          INTEGER NOT NULL DEFAULT 0,

                -- Society
                population_opinion          INTEGER NOT NULL DEFAULT 50,
                unrest                      REAL    NOT NULL DEFAULT 0.0,
                tax_level                   TEXT    NOT NULL DEFAULT 'Standard Contribution',

                -- Military
                total_army_size             INTEGER NOT NULL DEFAULT 0,

                -- Unrest event cooldowns
                last_riot_day               INTEGER NOT NULL DEFAULT 0,
                last_rebellion_day          INTEGER NOT NULL DEFAULT 0,

                PRIMARY KEY (server_id, country_id)
            )
        """)

    @staticmethod
    def _create_army_units(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS army_units (
                server_id       TEXT    NOT NULL,
                unit_id         TEXT    NOT NULL,
                country_id      TEXT    NOT NULL,
                type            TEXT    NOT NULL DEFAULT 'infantry',
                size            INTEGER NOT NULL DEFAULT 0,
                location        TEXT    NOT NULL DEFAULT '',
                status          TEXT    NOT NULL DEFAULT 'idle',
                target_location TEXT,
                arrival_day     INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (server_id, unit_id)
            )
        """)

    @staticmethod
    def _create_recruitment_tracking(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recruitment_tracking (
                server_id                  TEXT    NOT NULL,
                country_id                 TEXT    NOT NULL,
                recent_recruitment_amount  INTEGER NOT NULL DEFAULT 0,
                recent_recruitment_count   INTEGER NOT NULL DEFAULT 0,
                recruitment_window_start   INTEGER NOT NULL DEFAULT 0,
                penalty_active             INTEGER NOT NULL DEFAULT 0,
                penalty_end_time           INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (server_id, country_id)
            )
        """)

    @staticmethod
    def _create_province_state(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS province_state (
                server_id                     TEXT    NOT NULL,
                province_id                   TEXT    NOT NULL,
                owner_country                 TEXT    NOT NULL DEFAULT '',
                is_core                       INTEGER NOT NULL DEFAULT 1,
                religion                      TEXT    NOT NULL DEFAULT 'Atheism',
                core_conversion_target        TEXT,
                core_conversion_start_day     INTEGER DEFAULT 0,
                religion_conversion_target    TEXT,
                religion_conversion_start_day INTEGER DEFAULT 0,
                PRIMARY KEY (server_id, province_id)
            )
        """)

    @staticmethod
    def _migrate_country_state(conn: sqlite3.Connection) -> None:
        """
        Add any columns that do not yet exist in country_state.
        Handles upgrading databases created before this schema version.
        """
        new_columns = [
            ("base_population",             "INTEGER NOT NULL DEFAULT 1000000"),
            ("current_population",          "INTEGER NOT NULL DEFAULT 1000000"),
            ("base_growth_rate",            "REAL    NOT NULL DEFAULT 0.01"),
            ("bonus_growth_rate",           "REAL    NOT NULL DEFAULT 0.0"),
            ("growth_investment_count",     "INTEGER NOT NULL DEFAULT 0"),
            ("last_growth_investment_time", "INTEGER NOT NULL DEFAULT 0"),
            ("persecution_active",          "INTEGER NOT NULL DEFAULT 0"),
            ("population_opinion",          "INTEGER NOT NULL DEFAULT 50"),
            ("unrest",                      "REAL    NOT NULL DEFAULT 0.0"),
            ("tax_level",                   "TEXT    NOT NULL DEFAULT 'Standard Contribution'"),
            ("total_army_size",             "INTEGER NOT NULL DEFAULT 0"),
            ("last_riot_day",               "INTEGER NOT NULL DEFAULT 0"),
            ("last_rebellion_day",          "INTEGER NOT NULL DEFAULT 0"),
        ]
        for col, typedef in new_columns:
            try:
                conn.execute(
                    f"ALTER TABLE country_state ADD COLUMN {col} {typedef}"
                )
            except sqlite3.OperationalError:
                pass  # Column already exists — safe to ignore

    # ------------------------------------------------------------------
    # country_state — read
    # ------------------------------------------------------------------

    def get_country(self, server_id: str, country_id: str) -> dict | None:
        """Return one country's full state dict, or None if not found."""
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM country_state WHERE server_id=? AND country_id=?",
                (server_id, country_id),
            ).fetchone()
        return dict(row) if row else None

    def get_or_create_country(self, server_id: str, country_id: str) -> dict:
        """Return a country row, creating it with defaults if absent."""
        existing = self.get_country(server_id, country_id)
        if existing:
            return existing
        self._insert_country_defaults(server_id, country_id)
        return self.get_country(server_id, country_id)  # type: ignore[return-value]

    def get_all_countries(self, server_id: str) -> list[dict]:
        """Return all country rows for a server, sorted by country_id."""
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM country_state WHERE server_id=? ORDER BY country_id",
                (server_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # country_state — write
    # ------------------------------------------------------------------

    def upsert_country(
        self,
        server_id:    str,
        country_id:   str,
        treasury:     float | None = None,
        daily_income: float | None = None,
        population:   int   | None = None,
        growth_rate:  float | None = None,
        religion:     str   | None = None,
    ) -> None:
        """
        Insert or fully replace a country row (backward-compatible API).
        For partial updates use ``update_fields()``.
        """
        self._insert_country_defaults(
            server_id, country_id,
            treasury     = treasury,
            daily_income = daily_income,
            population   = population,
            growth_rate  = growth_rate,
            religion     = religion,
        )

    def update_fields(
        self,
        server_id:  str,
        country_id: str,
        **fields,
    ) -> None:
        """
        Update only the specified columns for an existing country row.
        The row must exist (call ``get_or_create_country`` first).
        Column names are validated against the known schema.
        """
        if not fields:
            return
        invalid = set(fields) - _COUNTRY_STATE_COLUMNS
        if invalid:
            raise ValueError(f"Unknown column(s) for country_state: {invalid}")
        set_clause = ", ".join(f"{col}=?" for col in fields)
        values     = list(fields.values()) + [server_id, country_id]
        with self._connection() as conn:
            conn.execute(
                f"UPDATE country_state SET {set_clause} "
                f"WHERE server_id=? AND country_id=?",
                values,
            )

    def delete_country(self, server_id: str, country_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM country_state WHERE server_id=? AND country_id=?",
                (server_id, country_id),
            )

    def delete_server(self, server_id: str) -> None:
        """Remove all data (all tables) for a server."""
        with self._connection() as conn:
            for table in ("country_state", "army_units",
                          "recruitment_tracking", "province_state"):
                conn.execute(f"DELETE FROM {table} WHERE server_id=?", (server_id,))

    # ------------------------------------------------------------------
    # army_units — read
    # ------------------------------------------------------------------

    def get_army_unit(self, server_id: str, unit_id: str) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM army_units WHERE server_id=? AND unit_id=?",
                (server_id, unit_id),
            ).fetchone()
        return dict(row) if row else None

    def get_army_units_by_country(self, server_id: str, country_id: str) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM army_units WHERE server_id=? AND country_id=?",
                (server_id, country_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all_army_units(self, server_id: str) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM army_units WHERE server_id=?", (server_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_moving_units(self, server_id: str) -> list[dict]:
        """Return units currently in transit."""
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM army_units WHERE server_id=? AND status='moving'",
                (server_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # army_units — write
    # ------------------------------------------------------------------

    def upsert_army_unit(
        self,
        server_id:       str,
        unit_id:         str,
        country_id:      str,
        unit_type:       str,
        size:            int,
        location:        str,
        status:          str        = "idle",
        target_location: str | None = None,
        arrival_day:     int        = 0,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO army_units
                    (server_id, unit_id, country_id, type, size,
                     location, status, target_location, arrival_day)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(server_id, unit_id) DO UPDATE SET
                    country_id      = excluded.country_id,
                    type            = excluded.type,
                    size            = excluded.size,
                    location        = excluded.location,
                    status          = excluded.status,
                    target_location = excluded.target_location,
                    arrival_day     = excluded.arrival_day
            """, (server_id, unit_id, country_id, unit_type, size,
                  location, status, target_location, arrival_day))

    def update_army_unit_fields(
        self,
        server_id: str,
        unit_id:   str,
        **fields,
    ) -> None:
        """Partial update for army_units row."""
        allowed = {"country_id", "type", "size", "location",
                   "status", "target_location", "arrival_day"}
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(f"Unknown column(s) for army_units: {invalid}")
        if not fields:
            return
        set_clause = ", ".join(f"{col}=?" for col in fields)
        values     = list(fields.values()) + [server_id, unit_id]
        with self._connection() as conn:
            conn.execute(
                f"UPDATE army_units SET {set_clause} "
                f"WHERE server_id=? AND unit_id=?",
                values,
            )

    def delete_army_unit(self, server_id: str, unit_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM army_units WHERE server_id=? AND unit_id=?",
                (server_id, unit_id),
            )

    # ------------------------------------------------------------------
    # recruitment_tracking — read / write
    # ------------------------------------------------------------------

    def get_recruitment_tracking(
        self, server_id: str, country_id: str
    ) -> dict:
        """Return tracking row, creating defaults if absent."""
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM recruitment_tracking "
                "WHERE server_id=? AND country_id=?",
                (server_id, country_id),
            ).fetchone()
        if row:
            return dict(row)
        # Auto-create
        self.update_recruitment_tracking(server_id, country_id)
        return self.get_recruitment_tracking(server_id, country_id)

    def update_recruitment_tracking(
        self,
        server_id:                 str,
        country_id:                str,
        recent_recruitment_amount: int   = 0,
        recent_recruitment_count:  int   = 0,
        recruitment_window_start:  int   = 0,
        penalty_active:            bool  = False,
        penalty_end_time:          int   = 0,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO recruitment_tracking
                    (server_id, country_id, recent_recruitment_amount,
                     recent_recruitment_count, recruitment_window_start,
                     penalty_active, penalty_end_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(server_id, country_id) DO UPDATE SET
                    recent_recruitment_amount = excluded.recent_recruitment_amount,
                    recent_recruitment_count  = excluded.recent_recruitment_count,
                    recruitment_window_start  = excluded.recruitment_window_start,
                    penalty_active            = excluded.penalty_active,
                    penalty_end_time          = excluded.penalty_end_time
            """, (server_id, country_id,
                  recent_recruitment_amount, recent_recruitment_count,
                  recruitment_window_start, int(penalty_active), penalty_end_time))

    # ------------------------------------------------------------------
    # province_state — read
    # ------------------------------------------------------------------

    def get_province(self, server_id: str, province_id: str) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM province_state WHERE server_id=? AND province_id=?",
                (server_id, province_id),
            ).fetchone()
        return dict(row) if row else None

    def get_provinces_by_owner(self, server_id: str, owner_country: str) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM province_state "
                "WHERE server_id=? AND owner_country=?",
                (server_id, owner_country),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all_provinces(self, server_id: str) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM province_state WHERE server_id=?", (server_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_provinces_with_active_conversion(self, server_id: str) -> list[dict]:
        """Return provinces that have a core or religion conversion in progress."""
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM province_state WHERE server_id=? "
                "AND (core_conversion_target IS NOT NULL "
                "     OR religion_conversion_target IS NOT NULL)",
                (server_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # province_state — write
    # ------------------------------------------------------------------

    def upsert_province(
        self,
        server_id:     str,
        province_id:   str,
        owner_country: str  = "",
        is_core:       bool = True,
        religion:      str  = DEFAULT_RELIGION,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO province_state
                    (server_id, province_id, owner_country, is_core, religion)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(server_id, province_id) DO UPDATE SET
                    owner_country = excluded.owner_country,
                    is_core       = excluded.is_core,
                    religion      = excluded.religion
            """, (server_id, province_id, owner_country, int(is_core), religion))

    def update_province_fields(
        self,
        server_id:   str,
        province_id: str,
        **fields,
    ) -> None:
        allowed = {
            "owner_country", "is_core", "religion",
            "core_conversion_target", "core_conversion_start_day",
            "religion_conversion_target", "religion_conversion_start_day",
        }
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(f"Unknown column(s) for province_state: {invalid}")
        if not fields:
            return
        set_clause = ", ".join(f"{col}=?" for col in fields)
        values     = list(fields.values()) + [server_id, province_id]
        with self._connection() as conn:
            conn.execute(
                f"UPDATE province_state SET {set_clause} "
                f"WHERE server_id=? AND province_id=?",
                values,
            )

    def delete_province(self, server_id: str, province_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM province_state WHERE server_id=? AND province_id=?",
                (server_id, province_id),
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _insert_country_defaults(
        self,
        server_id:    str,
        country_id:   str,
        treasury:     float | None = None,
        daily_income: float | None = None,
        population:   int   | None = None,
        growth_rate:  float | None = None,
        religion:     str   | None = None,
    ) -> None:
        pop = population if population is not None else DEFAULT_BASE_POPULATION
        gr  = growth_rate if growth_rate is not None else DEFAULT_BASE_GROWTH_RATE
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO country_state (
                    server_id, country_id, treasury, daily_income,
                    population, growth_rate,
                    base_population, current_population,
                    base_growth_rate, bonus_growth_rate,
                    religion, tax_level, population_opinion, unrest
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(server_id, country_id) DO UPDATE SET
                    treasury         = excluded.treasury,
                    daily_income     = excluded.daily_income,
                    population       = excluded.population,
                    growth_rate      = excluded.growth_rate,
                    base_population  = excluded.base_population,
                    current_population = excluded.current_population,
                    base_growth_rate = excluded.base_growth_rate,
                    religion         = excluded.religion
            """, (
                server_id, country_id,
                treasury     if treasury     is not None else DEFAULT_TREASURY,
                daily_income if daily_income is not None else DEFAULT_DAILY_INCOME,
                pop, gr, pop, pop, gr,
                DEFAULT_BONUS_GROWTH_RATE,
                religion  if religion  is not None else DEFAULT_RELIGION,
                DEFAULT_TAX_LEVEL, DEFAULT_OPINION, DEFAULT_UNREST,
            ))

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Yield a connection, committing on success or rolling back on error.
        In-memory databases reuse a single persistent connection.
        """
        if self._mem_conn is not None:
            try:
                yield self._mem_conn
                self._mem_conn.commit()
            except Exception:
                self._mem_conn.rollback()
                raise
        else:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
