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

_MIL_TECH_COLUMNS: frozenset[str] = frozenset({
    "is_unlocked",
    "is_researching",
    "research_start_day",
    "research_duration_days",
    "research_end_day",
})

_TROOP_DEF_COLUMNS: frozenset[str] = frozenset({
    "category",
    "required_tech",
    "population_required",
    "gold_cost",
    "recruitment_time_days",
    "speed_modifier",
    "battle_points",
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
            self._create_technologies(conn)
            self._create_reforms(conn)
            self._create_military_technologies(conn)
            self._create_troop_definitions(conn)
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
    # technologies — DDL + CRUD
    # ------------------------------------------------------------------

    @staticmethod
    def _create_technologies(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS technologies (
                server_id          TEXT    NOT NULL,
                scenario_id        TEXT    NOT NULL,
                country_id         TEXT    NOT NULL,
                tech_id            TEXT    NOT NULL,
                is_unlocked        INTEGER NOT NULL DEFAULT 0,
                is_researching     INTEGER NOT NULL DEFAULT 0,
                research_start_day INTEGER NOT NULL DEFAULT 0,
                research_end_day   INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (server_id, scenario_id, country_id, tech_id)
            )
        """)

    def upsert_technology(
        self,
        server_id:          str,
        scenario_id:        str,
        country_id:         str,
        tech_id:            str,
        is_unlocked:        bool = False,
        is_researching:     bool = False,
        research_start_day: int  = 0,
        research_end_day:   int  = 0,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO technologies
                    (server_id, scenario_id, country_id, tech_id,
                     is_unlocked, is_researching,
                     research_start_day, research_end_day)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(server_id, scenario_id, country_id, tech_id)
                DO UPDATE SET
                    is_unlocked        = excluded.is_unlocked,
                    is_researching     = excluded.is_researching,
                    research_start_day = excluded.research_start_day,
                    research_end_day   = excluded.research_end_day
            """, (
                server_id, scenario_id, country_id, tech_id,
                int(is_unlocked), int(is_researching),
                research_start_day, research_end_day,
            ))

    def get_technology(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        tech_id:     str,
    ) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM technologies "
                "WHERE server_id=? AND scenario_id=? "
                "AND country_id=? AND tech_id=?",
                (server_id, scenario_id, country_id, tech_id),
            ).fetchone()
        return dict(row) if row else None

    def get_technologies_for_country(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM technologies "
                "WHERE server_id=? AND scenario_id=? AND country_id=? "
                "ORDER BY tech_id",
                (server_id, scenario_id, country_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_active_research(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> dict | None:
        """Return the currently-researching technology row, or None."""
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM technologies "
                "WHERE server_id=? AND scenario_id=? "
                "AND country_id=? AND is_researching=1",
                (server_id, scenario_id, country_id),
            ).fetchone()
        return dict(row) if row else None

    def get_researching_techs_for_scenario(
        self,
        server_id:   str,
        scenario_id: str,
    ) -> list[dict]:
        """Return all countries' currently-researching technology rows."""
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM technologies "
                "WHERE server_id=? AND scenario_id=? AND is_researching=1",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def complete_technology(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        tech_id:     str,
    ) -> None:
        """Mark a technology as unlocked and clear the researching flag."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE technologies "
                "SET is_unlocked=1, is_researching=0 "
                "WHERE server_id=? AND scenario_id=? "
                "AND country_id=? AND tech_id=?",
                (server_id, scenario_id, country_id, tech_id),
            )

    # ------------------------------------------------------------------
    # reforms — DDL + CRUD
    # ------------------------------------------------------------------

    @staticmethod
    def _create_reforms(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reforms (
                server_id          TEXT    NOT NULL,
                scenario_id        TEXT    NOT NULL,
                country_id         TEXT    NOT NULL,
                reform_id          TEXT    NOT NULL,
                is_unlocked        INTEGER NOT NULL DEFAULT 0,
                is_adopted         INTEGER NOT NULL DEFAULT 0,
                is_researching     INTEGER NOT NULL DEFAULT 0,
                research_start_day INTEGER NOT NULL DEFAULT 0,
                research_end_day   INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (server_id, scenario_id, country_id, reform_id)
            )
        """)

    def upsert_reform(
        self,
        server_id:          str,
        scenario_id:        str,
        country_id:         str,
        reform_id:          str,
        is_unlocked:        bool = False,
        is_adopted:         bool = False,
        is_researching:     bool = False,
        research_start_day: int  = 0,
        research_end_day:   int  = 0,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO reforms
                    (server_id, scenario_id, country_id, reform_id,
                     is_unlocked, is_adopted, is_researching,
                     research_start_day, research_end_day)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(server_id, scenario_id, country_id, reform_id)
                DO UPDATE SET
                    is_unlocked        = excluded.is_unlocked,
                    is_adopted         = excluded.is_adopted,
                    is_researching     = excluded.is_researching,
                    research_start_day = excluded.research_start_day,
                    research_end_day   = excluded.research_end_day
            """, (
                server_id, scenario_id, country_id, reform_id,
                int(is_unlocked), int(is_adopted), int(is_researching),
                research_start_day, research_end_day,
            ))

    def get_reform(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        reform_id:   str,
    ) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM reforms "
                "WHERE server_id=? AND scenario_id=? "
                "AND country_id=? AND reform_id=?",
                (server_id, scenario_id, country_id, reform_id),
            ).fetchone()
        return dict(row) if row else None

    def get_reforms_for_country(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM reforms "
                "WHERE server_id=? AND scenario_id=? AND country_id=? "
                "ORDER BY reform_id",
                (server_id, scenario_id, country_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_adopted_reforms(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM reforms "
                "WHERE server_id=? AND scenario_id=? "
                "AND country_id=? AND is_adopted=1",
                (server_id, scenario_id, country_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_active_reform_research(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> dict | None:
        """Return the currently-researching reform row, or None."""
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM reforms "
                "WHERE server_id=? AND scenario_id=? "
                "AND country_id=? AND is_researching=1",
                (server_id, scenario_id, country_id),
            ).fetchone()
        return dict(row) if row else None

    def get_researching_reforms_for_scenario(
        self,
        server_id:   str,
        scenario_id: str,
    ) -> list[dict]:
        """Return all countries' currently-researching reform rows."""
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM reforms "
                "WHERE server_id=? AND scenario_id=? AND is_researching=1",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def complete_reform(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        reform_id:   str,
    ) -> None:
        """Mark a reform as unlocked (but not yet adopted) and clear researching."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE reforms "
                "SET is_unlocked=1, is_researching=0 "
                "WHERE server_id=? AND scenario_id=? "
                "AND country_id=? AND reform_id=?",
                (server_id, scenario_id, country_id, reform_id),
            )

    def adopt_reform(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        reform_id:   str,
    ) -> None:
        """Mark a reform as adopted (requires is_unlocked=1 to be valid)."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE reforms SET is_adopted=1 "
                "WHERE server_id=? AND scenario_id=? "
                "AND country_id=? AND reform_id=?",
                (server_id, scenario_id, country_id, reform_id),
            )

    def unadopt_reform(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        reform_id:   str,
    ) -> None:
        """Remove the adopted flag from a reform."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE reforms SET is_adopted=0 "
                "WHERE server_id=? AND scenario_id=? "
                "AND country_id=? AND reform_id=?",
                (server_id, scenario_id, country_id, reform_id),
            )

    # ------------------------------------------------------------------
    # military_technologies — DDL + CRUD
    # ------------------------------------------------------------------

    @staticmethod
    def _create_military_technologies(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS military_technologies (
                server_id              TEXT    NOT NULL,
                scenario_id            TEXT    NOT NULL,
                country_id             TEXT    NOT NULL,
                tech_id                TEXT    NOT NULL,
                is_unlocked            INTEGER NOT NULL DEFAULT 0,
                is_researching         INTEGER NOT NULL DEFAULT 0,
                research_start_day     INTEGER NOT NULL DEFAULT 0,
                research_duration_days INTEGER NOT NULL DEFAULT 0,
                research_end_day       INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (server_id, scenario_id, country_id, tech_id)
            )
        """)

    def upsert_military_technology(
        self,
        server_id:              str,
        scenario_id:            str,
        country_id:             str,
        tech_id:                str,
        is_unlocked:            bool = False,
        is_researching:         bool = False,
        research_start_day:     int  = 0,
        research_duration_days: int  = 0,
        research_end_day:       int  = 0,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO military_technologies
                    (server_id, scenario_id, country_id, tech_id,
                     is_unlocked, is_researching,
                     research_start_day, research_duration_days, research_end_day)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(server_id, scenario_id, country_id, tech_id)
                DO UPDATE SET
                    is_unlocked            = excluded.is_unlocked,
                    is_researching         = excluded.is_researching,
                    research_start_day     = excluded.research_start_day,
                    research_duration_days = excluded.research_duration_days,
                    research_end_day       = excluded.research_end_day
            """, (
                server_id, scenario_id, country_id, tech_id,
                int(is_unlocked), int(is_researching),
                research_start_day, research_duration_days, research_end_day,
            ))

    def get_military_technology(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        tech_id:     str,
    ) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM military_technologies "
                "WHERE server_id=? AND scenario_id=? "
                "AND country_id=? AND tech_id=?",
                (server_id, scenario_id, country_id, tech_id),
            ).fetchone()
        return dict(row) if row else None

    def get_military_technologies_for_country(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM military_technologies "
                "WHERE server_id=? AND scenario_id=? AND country_id=? "
                "ORDER BY tech_id",
                (server_id, scenario_id, country_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_active_military_research(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> dict | None:
        """Return the currently-researching military technology row, or None."""
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM military_technologies "
                "WHERE server_id=? AND scenario_id=? "
                "AND country_id=? AND is_researching=1",
                (server_id, scenario_id, country_id),
            ).fetchone()
        return dict(row) if row else None

    def get_researching_military_techs_for_scenario(
        self,
        server_id:   str,
        scenario_id: str,
    ) -> list[dict]:
        """Return all countries' currently-researching military technology rows."""
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM military_technologies "
                "WHERE server_id=? AND scenario_id=? AND is_researching=1",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def complete_military_technology(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        tech_id:     str,
    ) -> None:
        """Mark a military technology as unlocked and clear the researching flag."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE military_technologies "
                "SET is_unlocked=1, is_researching=0 "
                "WHERE server_id=? AND scenario_id=? "
                "AND country_id=? AND tech_id=?",
                (server_id, scenario_id, country_id, tech_id),
            )

    def delete_scenario_military_technologies(
        self, server_id: str, scenario_id: str
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM military_technologies "
                "WHERE server_id=? AND scenario_id=?",
                (server_id, scenario_id),
            )

    # ------------------------------------------------------------------
    # troop_definitions — DDL + CRUD
    # ------------------------------------------------------------------

    @staticmethod
    def _create_troop_definitions(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS troop_definitions (
                server_id              TEXT    NOT NULL,
                scenario_id            TEXT    NOT NULL,
                unit_name              TEXT    NOT NULL,
                category               TEXT    NOT NULL,
                required_tech          TEXT    NOT NULL,
                population_required    INTEGER NOT NULL,
                gold_cost              REAL    NOT NULL,
                recruitment_time_days  INTEGER NOT NULL,
                speed_modifier         REAL    NOT NULL,
                battle_points          INTEGER NOT NULL,
                PRIMARY KEY (server_id, scenario_id, unit_name)
            )
        """)

    def seed_troop_definition(
        self,
        server_id:             str,
        scenario_id:           str,
        unit_name:             str,
        category:              str,
        required_tech:         str,
        population_required:   int,
        gold_cost:             float,
        recruitment_time_days: int,
        speed_modifier:        float,
        battle_points:         int,
    ) -> None:
        """Insert a troop definition row if it does not already exist (idempotent)."""
        with self._connection() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO troop_definitions
                    (server_id, scenario_id, unit_name, category, required_tech,
                     population_required, gold_cost, recruitment_time_days,
                     speed_modifier, battle_points)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                server_id, scenario_id, unit_name, category, required_tech,
                population_required, float(gold_cost), recruitment_time_days,
                float(speed_modifier), battle_points,
            ))

    def get_troop_definition(
        self,
        server_id:   str,
        scenario_id: str,
        unit_name:   str,
    ) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM troop_definitions "
                "WHERE server_id=? AND scenario_id=? AND unit_name=?",
                (server_id, scenario_id, unit_name),
            ).fetchone()
        return dict(row) if row else None

    def get_all_troop_definitions(
        self,
        server_id:   str,
        scenario_id: str,
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM troop_definitions "
                "WHERE server_id=? AND scenario_id=? "
                "ORDER BY category, unit_name",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_troop_definitions_by_category(
        self,
        server_id:   str,
        scenario_id: str,
        category:    str,
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM troop_definitions "
                "WHERE server_id=? AND scenario_id=? AND category=? "
                "ORDER BY unit_name",
                (server_id, scenario_id, category),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_troop_definitions_by_tech(
        self,
        server_id:   str,
        scenario_id: str,
        tech_id:     str,
    ) -> list[dict]:
        """Return all unit definitions that require the given military tech_id."""
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM troop_definitions "
                "WHERE server_id=? AND scenario_id=? AND required_tech=? "
                "ORDER BY unit_name",
                (server_id, scenario_id, tech_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_scenario_troop_definitions(
        self, server_id: str, scenario_id: str
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM troop_definitions "
                "WHERE server_id=? AND scenario_id=?",
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
