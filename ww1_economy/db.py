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

from ww1_economy.resources import STORABLE_RESOURCES, MARKET_BASE_PRICES


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
    "is_active",
})

_STORAGE_COLUMNS: frozenset[str] = frozenset(STORABLE_RESOURCES)

_COUNTRY_COLUMNS: frozenset[str] = frozenset({
    "country_name",
    "total_population",
    "treasury",
    "daily_base_income",
    "tax_multiplier",
    "economy_efficiency",
    "war_victory_end_month",
    "in_active_war",
    "population_opinion",
    "unrest",
})

_MARKET_COLUMNS: frozenset[str] = frozenset({
    "base_price",
    "current_price",
    "current_month_demand",
    "previous_month_demand",
    "shortage",
    "shortage_end_month",
})


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
        """Create all tables. Safe to call on every startup (idempotent).
        Also runs in-place migrations to add new columns to existing DB
        files without losing data."""
        with self._connection() as conn:
            self._create_buildings(conn)
            self._create_country_storage(conn)
            self._create_countries(conn)
            self._create_provinces(conn)
            self._create_global_market(conn)
            self._migrate_buildings(conn)
            self._migrate_countries(conn)

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
    def _create_countries(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS countries (
                server_id        TEXT    NOT NULL,
                scenario_id      TEXT    NOT NULL,
                country_id       TEXT    NOT NULL,
                country_name     TEXT    NOT NULL,
                total_population INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (server_id, scenario_id, country_id)
            )
        """)

    @staticmethod
    def _create_provinces(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS provinces (
                server_id     TEXT    NOT NULL,
                scenario_id   TEXT    NOT NULL,
                province_id   INTEGER NOT NULL,
                province_name TEXT    NOT NULL,
                owner_country TEXT    NOT NULL,
                resource_type TEXT    NOT NULL,
                population    INTEGER NOT NULL,
                PRIMARY KEY (server_id, scenario_id, province_id)
            )
        """)

    @staticmethod
    def _create_global_market(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS global_market (
                server_id             TEXT    NOT NULL,
                scenario_id           TEXT    NOT NULL,
                resource_name         TEXT    NOT NULL,
                base_price            REAL    NOT NULL,
                current_price         REAL    NOT NULL,
                current_month_demand  INTEGER NOT NULL DEFAULT 0,
                previous_month_demand INTEGER NOT NULL DEFAULT 0,
                shortage              INTEGER NOT NULL DEFAULT 0,
                shortage_end_month    INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (server_id, scenario_id, resource_name)
            )
        """)

    # ---- migrations (additive only — never drops or re-types) --------

    @staticmethod
    def _migrate_buildings(conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(buildings)")}
        if "is_active" not in cols:
            conn.execute(
                "ALTER TABLE buildings "
                "ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
            )

    @staticmethod
    def _migrate_countries(conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(countries)")}
        new_cols: list[tuple[str, str]] = [
            ("treasury",              "REAL    NOT NULL DEFAULT 0.0"),
            ("daily_base_income",     "REAL    NOT NULL DEFAULT 0.0"),
            ("tax_multiplier",        "REAL    NOT NULL DEFAULT 1.0"),
            ("economy_efficiency",    "REAL    NOT NULL DEFAULT 1.0"),
            ("war_victory_end_month", "INTEGER NOT NULL DEFAULT 0"),
            ("in_active_war",         "INTEGER NOT NULL DEFAULT 0"),
            ("population_opinion",    "INTEGER NOT NULL DEFAULT 50"),
            ("unrest",                "REAL    NOT NULL DEFAULT 0.0"),
        ]
        for name, typedef in new_cols:
            if name not in cols:
                conn.execute(
                    f"ALTER TABLE countries ADD COLUMN {name} {typedef}"
                )

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
    # countries — read / write
    # ------------------------------------------------------------------

    def upsert_country(
        self,
        server_id:        str,
        scenario_id:      str,
        country_id:       str,
        country_name:     str,
        total_population: int,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO countries
                    (server_id, scenario_id, country_id, country_name, total_population)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(server_id, scenario_id, country_id)
                DO UPDATE SET
                    country_name     = excluded.country_name,
                    total_population = excluded.total_population
            """, (server_id, scenario_id, country_id, country_name, total_population))

    def get_country(
        self, server_id: str, scenario_id: str, country_id: str
    ) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM countries "
                "WHERE server_id=? AND scenario_id=? AND country_id=?",
                (server_id, scenario_id, country_id),
            ).fetchone()
        return dict(row) if row else None

    def get_all_countries(
        self, server_id: str, scenario_id: str
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM countries "
                "WHERE server_id=? AND scenario_id=? "
                "ORDER BY country_id",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_scenario_countries(
        self, server_id: str, scenario_id: str
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM countries WHERE server_id=? AND scenario_id=?",
                (server_id, scenario_id),
            )

    # ------------------------------------------------------------------
    # provinces — read / write
    # ------------------------------------------------------------------

    def upsert_province(
        self,
        server_id:     str,
        scenario_id:   str,
        province_id:   int,
        province_name: str,
        owner_country: str,
        resource_type: str,
        population:    int,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO provinces
                    (server_id, scenario_id, province_id, province_name,
                     owner_country, resource_type, population)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(server_id, scenario_id, province_id)
                DO UPDATE SET
                    province_name = excluded.province_name,
                    owner_country = excluded.owner_country,
                    resource_type = excluded.resource_type,
                    population    = excluded.population
            """, (
                server_id, scenario_id, province_id, province_name,
                owner_country, resource_type, population,
            ))

    def get_province(
        self, server_id: str, scenario_id: str, province_id: int
    ) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM provinces "
                "WHERE server_id=? AND scenario_id=? AND province_id=?",
                (server_id, scenario_id, province_id),
            ).fetchone()
        return dict(row) if row else None

    def get_all_provinces(
        self, server_id: str, scenario_id: str
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM provinces "
                "WHERE server_id=? AND scenario_id=? "
                "ORDER BY province_id",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_provinces_by_country(
        self, server_id: str, scenario_id: str, owner_country: str
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM provinces "
                "WHERE server_id=? AND scenario_id=? AND owner_country=? "
                "ORDER BY province_id",
                (server_id, scenario_id, owner_country),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_scenario_provinces(
        self, server_id: str, scenario_id: str
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM provinces WHERE server_id=? AND scenario_id=?",
                (server_id, scenario_id),
            )

    # ------------------------------------------------------------------
    # countries — economy field updates (treasury, opinion, unrest, etc.)
    # ------------------------------------------------------------------

    def update_country_fields(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        **fields,
    ) -> None:
        if not fields:
            return
        invalid = set(fields) - _COUNTRY_COLUMNS
        if invalid:
            raise ValueError(f"Unknown column(s) for countries: {invalid}")
        set_clause = ", ".join(f"{c}=?" for c in fields)
        values     = list(fields.values()) + [server_id, scenario_id, country_id]
        with self._connection() as conn:
            conn.execute(
                f"UPDATE countries SET {set_clause} "
                f"WHERE server_id=? AND scenario_id=? AND country_id=?",
                values,
            )

    def deduct_treasury(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        amount:      float,
    ) -> tuple[bool, float]:
        """
        Atomically deduct ``amount`` from the country's treasury IFF it has
        enough. Returns ``(success, new_balance)``.
        Treasury can never go negative — failure leaves the row untouched.
        """
        if amount < 0:
            raise ValueError(f"Deduction amount must be non-negative, got {amount}.")
        with self._connection() as conn:
            cur = conn.execute(
                "UPDATE countries SET treasury = treasury - ? "
                "WHERE server_id=? AND scenario_id=? AND country_id=? "
                "AND treasury >= ?",
                (amount, server_id, scenario_id, country_id, amount),
            )
            if cur.rowcount == 0:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT treasury FROM countries "
                    "WHERE server_id=? AND scenario_id=? AND country_id=?",
                    (server_id, scenario_id, country_id),
                ).fetchone()
                current = float(row["treasury"]) if row else 0.0
                return False, current
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT treasury FROM countries "
                "WHERE server_id=? AND scenario_id=? AND country_id=?",
                (server_id, scenario_id, country_id),
            ).fetchone()
            return True, float(row["treasury"])

    def deposit_treasury(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        amount:      float,
    ) -> float:
        """Add gold to a country's treasury. Returns the new balance."""
        if amount < 0:
            raise ValueError(f"Deposit amount must be non-negative, got {amount}.")
        with self._connection() as conn:
            conn.execute(
                "UPDATE countries SET treasury = treasury + ? "
                "WHERE server_id=? AND scenario_id=? AND country_id=?",
                (amount, server_id, scenario_id, country_id),
            )
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT treasury FROM countries "
                "WHERE server_id=? AND scenario_id=? AND country_id=?",
                (server_id, scenario_id, country_id),
            ).fetchone()
            return float(row["treasury"]) if row else 0.0

    # ------------------------------------------------------------------
    # buildings — active / inactive bulk updates
    # ------------------------------------------------------------------

    def set_buildings_active_for_country(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        is_active:   bool,
        building_types: list[str] | None = None,
    ) -> int:
        """
        Bulk-set ``is_active`` for all completed buildings of a country.
        If ``building_types`` is provided, only buildings of those types
        are updated.  Returns the number of rows affected.
        """
        with self._connection() as conn:
            if building_types is None:
                cur = conn.execute(
                    "UPDATE buildings SET is_active=? "
                    "WHERE server_id=? AND scenario_id=? "
                    "AND country_id=? AND is_completed=1",
                    (int(is_active), server_id, scenario_id, country_id),
                )
            else:
                if not building_types:
                    return 0
                placeholders = ",".join("?" * len(building_types))
                cur = conn.execute(
                    f"UPDATE buildings SET is_active=? "
                    f"WHERE server_id=? AND scenario_id=? "
                    f"AND country_id=? AND is_completed=1 "
                    f"AND building_type IN ({placeholders})",
                    [int(is_active), server_id, scenario_id, country_id, *building_types],
                )
            return cur.rowcount

    # ------------------------------------------------------------------
    # global_market — read / write
    # ------------------------------------------------------------------

    def init_market_prices(
        self,
        server_id:   str,
        scenario_id: str,
        prices:      dict[str, float] | None = None,
    ) -> None:
        """Insert one row per market resource using base prices.
        Existing rows are left untouched (idempotent)."""
        prices = prices or MARKET_BASE_PRICES
        with self._connection() as conn:
            for resource, base in prices.items():
                conn.execute(
                    "INSERT OR IGNORE INTO global_market "
                    "(server_id, scenario_id, resource_name, "
                    " base_price, current_price) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (server_id, scenario_id, resource, float(base), float(base)),
                )

    def get_market_resource(
        self,
        server_id:    str,
        scenario_id:  str,
        resource:     str,
    ) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM global_market "
                "WHERE server_id=? AND scenario_id=? AND resource_name=?",
                (server_id, scenario_id, resource),
            ).fetchone()
        return dict(row) if row else None

    def get_all_market(
        self, server_id: str, scenario_id: str
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM global_market "
                "WHERE server_id=? AND scenario_id=? "
                "ORDER BY resource_name",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_market_fields(
        self,
        server_id:   str,
        scenario_id: str,
        resource:    str,
        **fields,
    ) -> None:
        if not fields:
            return
        invalid = set(fields) - _MARKET_COLUMNS
        if invalid:
            raise ValueError(f"Unknown column(s) for global_market: {invalid}")
        set_clause = ", ".join(f"{c}=?" for c in fields)
        values     = list(fields.values()) + [server_id, scenario_id, resource]
        with self._connection() as conn:
            conn.execute(
                f"UPDATE global_market SET {set_clause} "
                f"WHERE server_id=? AND scenario_id=? AND resource_name=?",
                values,
            )

    def increment_market_demand(
        self,
        server_id:   str,
        scenario_id: str,
        resource:    str,
        quantity:    int,
    ) -> int:
        """Atomically add ``quantity`` to current_month_demand and return new value."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE global_market "
                "SET current_month_demand = current_month_demand + ? "
                "WHERE server_id=? AND scenario_id=? AND resource_name=?",
                (quantity, server_id, scenario_id, resource),
            )
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT current_month_demand FROM global_market "
                "WHERE server_id=? AND scenario_id=? AND resource_name=?",
                (server_id, scenario_id, resource),
            ).fetchone()
            return int(row["current_month_demand"]) if row else 0

    def delete_scenario_market(
        self, server_id: str, scenario_id: str
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM global_market WHERE server_id=? AND scenario_id=?",
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
