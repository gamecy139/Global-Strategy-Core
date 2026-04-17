"""
DATABASE LAYER
--------------
SQLite persistence for all per-server, per-country state.

Table: country_state
  Columns: server_id, country_id, treasury, daily_income,
           population, growth_rate, religion

All reads and writes are isolated by (server_id, country_id) so multiple
Discord servers can share a single SQLite file without interfering with
each other.

Usage
-----
    from game_backend.db import Database

    db = Database("game.db")      # or ":memory:" for tests
    db.init()                     # create tables if not present
    db.upsert_country(server_id="guild_123", country_id="Evoria",
                      religion="Islam")
    row = db.get_country(server_id="guild_123", country_id="Evoria")
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Generator


# ---------------------------------------------------------------------------
# Default column values — avoids magic numbers scattered across systems
# ---------------------------------------------------------------------------

DEFAULT_TREASURY:     float = 0.0
DEFAULT_DAILY_INCOME: float = 0.0
DEFAULT_POPULATION:   int   = 1_000_000
DEFAULT_GROWTH_RATE:  float = 0.01    # 1% per in-game month
DEFAULT_RELIGION:     str   = "Atheism"


# ---------------------------------------------------------------------------
# Database — thin wrapper around sqlite3
# ---------------------------------------------------------------------------

class Database:
    """
    Manages the SQLite connection and all CRUD operations for ``country_state``.

    Parameters
    ----------
    db_path : str
        Path to the SQLite file, or ``":memory:"`` for an in-memory database
        (useful for unit tests and demos).

    Note: when ``db_path`` is ``":memory:"``, a single persistent connection is
    reused for all operations because each ``sqlite3.connect(":memory:")`` call
    creates a completely separate database — data written in one connection
    would be invisible to another.
    """

    def __init__(self, db_path: str = "game.db") -> None:
        self.db_path = db_path
        # For in-memory databases, maintain a single persistent connection
        # so all operations share the same database instance.
        self._mem_conn: sqlite3.Connection | None = None
        if db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.execute("PRAGMA journal_mode=WAL")
            self._mem_conn.execute("PRAGMA foreign_keys=ON")

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def init(self) -> None:
        """
        Create all required tables if they do not already exist.
        Safe to call on every startup (idempotent).
        """
        with self._connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS country_state (
                    server_id     TEXT    NOT NULL,
                    country_id    TEXT    NOT NULL,
                    treasury      REAL    NOT NULL DEFAULT 0.0,
                    daily_income  REAL    NOT NULL DEFAULT 0.0,
                    population    INTEGER NOT NULL DEFAULT 1000000,
                    growth_rate   REAL    NOT NULL DEFAULT 0.01,
                    religion      TEXT    NOT NULL DEFAULT 'Atheism',
                    PRIMARY KEY (server_id, country_id)
                )
            """)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_country(self, server_id: str, country_id: str) -> dict | None:
        """
        Return a single country's state as a dict, or ``None`` if not found.

        Keys: server_id, country_id, treasury, daily_income,
              population, growth_rate, religion
        """
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM country_state WHERE server_id=? AND country_id=?",
                (server_id, country_id),
            ).fetchone()
        return dict(row) if row else None

    def get_or_create_country(self, server_id: str, country_id: str) -> dict:
        """
        Return a country's state, inserting a row with defaults if absent.
        """
        existing = self.get_country(server_id, country_id)
        if existing:
            return existing
        self.upsert_country(server_id, country_id)
        return self.get_country(server_id, country_id)  # type: ignore[return-value]

    def get_all_countries(self, server_id: str) -> list[dict]:
        """Return all country rows for a given server."""
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM country_state WHERE server_id=? ORDER BY country_id",
                (server_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Write
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
        Insert or update a country row.
        Only the columns explicitly provided are written; all others keep their
        current value (or defaults for a new row).
        """
        treasury     = DEFAULT_TREASURY     if treasury     is None else treasury
        daily_income = DEFAULT_DAILY_INCOME if daily_income is None else daily_income
        population   = DEFAULT_POPULATION   if population   is None else population
        growth_rate  = DEFAULT_GROWTH_RATE  if growth_rate  is None else growth_rate
        religion     = DEFAULT_RELIGION     if religion     is None else religion

        with self._connection() as conn:
            conn.execute("""
                INSERT INTO country_state
                    (server_id, country_id, treasury, daily_income,
                     population, growth_rate, religion)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(server_id, country_id) DO UPDATE SET
                    treasury     = excluded.treasury,
                    daily_income = excluded.daily_income,
                    population   = excluded.population,
                    growth_rate  = excluded.growth_rate,
                    religion     = excluded.religion
            """, (server_id, country_id, treasury, daily_income,
                  population, growth_rate, religion))

    def update_fields(
        self,
        server_id:  str,
        country_id: str,
        **fields,
    ) -> None:
        """
        Update only specific columns for an existing row.
        Raises KeyError if the row does not exist (call get_or_create_country first).

        Example
        -------
            db.update_fields("guild_1", "Evoria", treasury=5000.0, population=2_000_000)
        """
        if not fields:
            return

        allowed = {"treasury", "daily_income", "population", "growth_rate", "religion"}
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(f"Unknown column(s): {invalid}")

        set_clause = ", ".join(f"{col}=?" for col in fields)
        values     = list(fields.values()) + [server_id, country_id]

        with self._connection() as conn:
            conn.execute(
                f"UPDATE country_state SET {set_clause} "
                f"WHERE server_id=? AND country_id=?",
                values,
            )

    def delete_country(self, server_id: str, country_id: str) -> None:
        """Remove a country from the database."""
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM country_state WHERE server_id=? AND country_id=?",
                (server_id, country_id),
            )

    def delete_server(self, server_id: str) -> None:
        """Remove all country records for an entire server."""
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM country_state WHERE server_id=?",
                (server_id,),
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Yield a sqlite3 connection with WAL mode and foreign-key support.
        Automatically commits on success or rolls back on exception.

        For in-memory databases, the single persistent connection is reused
        (it is never closed so data is not lost between calls).
        """
        if self._mem_conn is not None:
            # In-memory: reuse the persistent connection; never close it
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
