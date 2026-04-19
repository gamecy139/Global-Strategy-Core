"""
WW1 ECONOMY — DATABASE LAYER
------------------------------
SQLite persistence for the WW1 scenario economy system.

Tables
------
  buildings        — one row per building per province (Tier 1 and Tier 2)
  country_storage  — one row per country; each storable resource is a column

All data is keyed by (server_id, scenario_id) so multiple Discord servers
and multiple scenario instances never interfere with each other.

Usage
-----
    from ww1_economy.db import EconomyDB

    db = EconomyDB("ww1.db")   # or ":memory:" for tests
    db.init()
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Generator

from ww1_economy.resources import STORABLE_RESOURCES


# ---------------------------------------------------------------------------
# Allowed columns — used to validate update_building_fields()
# ---------------------------------------------------------------------------

_BUILDING_COLUMNS: frozenset[str] = frozenset({
    "country_id",
    "building_type",
    "resource_type",
    "construction_start_time",
    "construction_end_time",
    "is_completed",
})

_STORAGE_COLUMNS: frozenset[str] = frozenset(STORABLE_RESOURCES)


# ---------------------------------------------------------------------------
# EconomyDB
# ---------------------------------------------------------------------------

class EconomyDB:
    """
    Manages the SQLite connection and all CRUD operations for the WW1
    economy tables.

    Parameters
    ----------
    db_path : str
        Path to the SQLite file, or ``":memory:"`` for an in-memory database.
    """

    def __init__(self, db_path: str = "ww1_economy.db") -> None:
        self.db_path = db_path
        self._mem_conn: sqlite3.Connection | None = None
        if db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.execute("PRAGMA journal_mode=WAL")
            self._mem_conn.execute("PRAGMA foreign_keys=ON")

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Create all tables. Safe to call on every startup (idempotent)."""
        with self._connection() as conn:
            self._create_buildings(conn)
            self._create_country_storage(conn)

    # ---- DDL ---------------------------------------------------------

    @staticmethod
    def _create_buildings(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS buildings (
                server_id                TEXT    NOT NULL,
                scenario_id              TEXT    NOT NULL,
                province_id              TEXT    NOT NULL,
                country_id               TEXT    NOT NULL,
                building_type            TEXT    NOT NULL,
                resource_type            TEXT,
                construction_start_time  INTEGER NOT NULL DEFAULT 0,
                construction_end_time    INTEGER NOT NULL DEFAULT 0,
                is_completed             INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (server_id, scenario_id, province_id, building_type)
            )
        """)

    @staticmethod
    def _create_country_storage(conn: sqlite3.Connection) -> None:
        resource_cols = "\n".join(
            f"    {r:<14} INTEGER NOT NULL DEFAULT 0,"
            for r in STORABLE_RESOURCES
        ).rstrip(",")

        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS country_storage (
                server_id   TEXT    NOT NULL,
                scenario_id TEXT    NOT NULL,
                country_id  TEXT    NOT NULL,
                {resource_cols}
                ,
                PRIMARY KEY (server_id, scenario_id, country_id)
            )
        """)

    # ------------------------------------------------------------------
    # buildings — read
    # ------------------------------------------------------------------

    def get_building(
        self,
        server_id:    str,
        scenario_id:  str,
        province_id:  str,
        building_type: str,
    ) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM buildings "
                "WHERE server_id=? AND scenario_id=? "
                "AND province_id=? AND building_type=?",
                (server_id, scenario_id, province_id, building_type),
            ).fetchone()
        return dict(row) if row else None

    def get_buildings_in_province(
        self,
        server_id:   str,
        scenario_id: str,
        province_id: str,
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM buildings "
                "WHERE server_id=? AND scenario_id=? AND province_id=?",
                (server_id, scenario_id, province_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_completed_buildings(
        self,
        server_id:   str,
        scenario_id: str,
    ) -> list[dict]:
        """Return all completed buildings across the entire scenario."""
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM buildings "
                "WHERE server_id=? AND scenario_id=? AND is_completed=1",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_buildings_by_country(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM buildings "
                "WHERE server_id=? AND scenario_id=? AND country_id=?",
                (server_id, scenario_id, country_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_under_construction(
        self,
        server_id:   str,
        scenario_id: str,
    ) -> list[dict]:
        """Return all buildings not yet completed."""
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM buildings "
                "WHERE server_id=? AND scenario_id=? AND is_completed=0",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all_buildings(
        self,
        server_id:   str,
        scenario_id: str,
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM buildings WHERE server_id=? AND scenario_id=?",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # buildings — write
    # ------------------------------------------------------------------

    def insert_building(
        self,
        server_id:               str,
        scenario_id:             str,
        province_id:             str,
        country_id:              str,
        building_type:           str,
        resource_type:           str | None,
        construction_start_time: int,
        construction_end_time:   int,
        is_completed:            bool = False,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO buildings (
                    server_id, scenario_id, province_id, country_id,
                    building_type, resource_type,
                    construction_start_time, construction_end_time, is_completed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                server_id, scenario_id, province_id, country_id,
                building_type, resource_type,
                construction_start_time, construction_end_time,
                int(is_completed),
            ))

    def update_building_fields(
        self,
        server_id:    str,
        scenario_id:  str,
        province_id:  str,
        building_type: str,
        **fields,
    ) -> None:
        if not fields:
            return
        invalid = set(fields) - _BUILDING_COLUMNS
        if invalid:
            raise ValueError(f"Unknown column(s) for buildings: {invalid}")
        set_clause = ", ".join(f"{col}=?" for col in fields)
        values     = list(fields.values()) + [
            server_id, scenario_id, province_id, building_type
        ]
        with self._connection() as conn:
            conn.execute(
                f"UPDATE buildings SET {set_clause} "
                f"WHERE server_id=? AND scenario_id=? "
                f"AND province_id=? AND building_type=?",
                values,
            )

    def delete_building(
        self,
        server_id:    str,
        scenario_id:  str,
        province_id:  str,
        building_type: str,
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM buildings "
                "WHERE server_id=? AND scenario_id=? "
                "AND province_id=? AND building_type=?",
                (server_id, scenario_id, province_id, building_type),
            )

    def delete_scenario_buildings(
        self, server_id: str, scenario_id: str
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM buildings WHERE server_id=? AND scenario_id=?",
                (server_id, scenario_id),
            )

    # ------------------------------------------------------------------
    # country_storage — read
    # ------------------------------------------------------------------

    def get_storage(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM country_storage "
                "WHERE server_id=? AND scenario_id=? AND country_id=?",
                (server_id, scenario_id, country_id),
            ).fetchone()
        return dict(row) if row else None

    def get_or_create_storage(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> dict:
        row = self.get_storage(server_id, scenario_id, country_id)
        if row:
            return row
        with self._connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO country_storage "
                "(server_id, scenario_id, country_id) VALUES (?, ?, ?)",
                (server_id, scenario_id, country_id),
            )
        return self.get_storage(server_id, scenario_id, country_id)  # type: ignore

    def get_all_storage(
        self, server_id: str, scenario_id: str
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM country_storage "
                "WHERE server_id=? AND scenario_id=?",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # country_storage — write
    # ------------------------------------------------------------------

    def update_storage_resource(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        resource:    str,
        new_amount:  int,
    ) -> None:
        if resource not in _STORAGE_COLUMNS:
            raise ValueError(
                f"'{resource}' is not a storable resource. "
                f"Valid: {sorted(_STORAGE_COLUMNS)}"
            )
        self.get_or_create_storage(server_id, scenario_id, country_id)
        with self._connection() as conn:
            conn.execute(
                f"UPDATE country_storage SET {resource}=? "
                f"WHERE server_id=? AND scenario_id=? AND country_id=?",
                (new_amount, server_id, scenario_id, country_id),
            )

    def add_to_storage(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        resource:    str,
        amount:      int,
    ) -> int:
        """
        Add ``amount`` of ``resource`` to storage (atomic SQL update).
        Returns the new total.
        """
        if resource not in _STORAGE_COLUMNS:
            raise ValueError(
                f"'{resource}' is not a storable resource. "
                f"Valid: {sorted(_STORAGE_COLUMNS)}"
            )
        self.get_or_create_storage(server_id, scenario_id, country_id)
        with self._connection() as conn:
            conn.execute(
                f"UPDATE country_storage SET {resource} = {resource} + ? "
                f"WHERE server_id=? AND scenario_id=? AND country_id=?",
                (amount, server_id, scenario_id, country_id),
            )
        row = self.get_storage(server_id, scenario_id, country_id)
        return int(row[resource])  # type: ignore

    def deduct_from_storage(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        resource:    str,
        amount:      int,
    ) -> int:
        """
        Deduct ``amount`` from storage, flooring at 0.
        Returns the new total.
        """
        if resource not in _STORAGE_COLUMNS:
            raise ValueError(
                f"'{resource}' is not a storable resource. "
                f"Valid: {sorted(_STORAGE_COLUMNS)}"
            )
        row = self.get_or_create_storage(server_id, scenario_id, country_id)
        current = int(row.get(resource, 0))
        new_val = max(0, current - amount)
        self.update_storage_resource(
            server_id, scenario_id, country_id, resource, new_val
        )
        return new_val

    def delete_scenario_storage(
        self, server_id: str, scenario_id: str
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM country_storage WHERE server_id=? AND scenario_id=?",
                (server_id, scenario_id),
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
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
