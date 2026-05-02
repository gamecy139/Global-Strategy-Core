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
    "base_income_floor",
    "tax_multiplier",
    "tax_level",
    "economy_efficiency",
    "war_victory_end_month",
    "war_start_month",
    "in_active_war",
    "population_opinion",
    "unrest",
    "population_growth_rate",
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
            # Economy core
            self._create_buildings(conn)
            self._create_country_storage(conn)
            self._create_countries(conn)
            self._create_provinces(conn)
            self._create_global_market(conn)
            self._create_technologies(conn)
            self._create_reforms(conn)
            # Military
            self._create_military_technologies(conn)
            self._create_troop_definitions(conn)
            # Religion
            self._create_country_religions(conn)
            self._create_province_religions(conn)
            # Diplomacy
            self._create_relations(conn)
            self._create_alliances(conn)
            self._create_alliance_members(conn)
            # War
            self._create_wars(conn)
            self._create_war_participants(conn)
            # Armies & battle
            self._create_armies(conn)
            self._create_army_units(conn)
            self._create_battles(conn)
            # Occupation & post-war
            self._create_province_occupation(conn)
            self._create_province_cores(conn)
            self._create_province_religion_conversion(conn)
            self._create_war_reparations(conn)
            self._create_puppet_states(conn)
            # Migrations
            self._migrate_buildings(conn)
            self._migrate_countries(conn)
            self._migrate_armies(conn)

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
            ("treasury",                "REAL    NOT NULL DEFAULT 0.0"),
            ("daily_base_income",       "REAL    NOT NULL DEFAULT 0.0"),
            ("base_income_floor",       "REAL    NOT NULL DEFAULT 0.0"),
            ("tax_multiplier",          "REAL    NOT NULL DEFAULT 1.0"),
            ("tax_level",               "TEXT    NOT NULL DEFAULT 'standard'"),
            ("economy_efficiency",      "REAL    NOT NULL DEFAULT 1.0"),
            ("war_victory_end_month",   "INTEGER NOT NULL DEFAULT 0"),
            ("war_start_month",         "INTEGER NOT NULL DEFAULT 0"),
            ("in_active_war",           "INTEGER NOT NULL DEFAULT 0"),
            ("population_opinion",      "INTEGER NOT NULL DEFAULT 50"),
            ("unrest",                  "REAL    NOT NULL DEFAULT 0.0"),
            ("population_growth_rate",      "REAL    NOT NULL DEFAULT 0.6"),
            ("recruitment_used_percent",    "REAL    NOT NULL DEFAULT 0.0"),
            ("recruitment_last_reset_month","INTEGER NOT NULL DEFAULT 0"),
        ]
        for name, typedef in new_cols:
            if name not in cols:
                conn.execute(
                    f"ALTER TABLE countries ADD COLUMN {name} {typedef}"
                )

    @staticmethod
    def _migrate_armies(conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(armies)")}
        if "recruitment_end_day" not in cols:
            conn.execute(
                "ALTER TABLE armies ADD COLUMN recruitment_end_day INTEGER NOT NULL DEFAULT 0"
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

    def update_province_fields(
        self,
        server_id:   str,
        scenario_id: str,
        province_id: str,
        **fields,
    ) -> None:
        """Update arbitrary province columns (owner_country, resource_type, etc.)."""
        allowed = {"owner_country", "province_name", "resource_type", "population"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Unknown province fields: {bad}")
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._connection() as conn:
            conn.execute(
                f"UPDATE provinces SET {sets} "
                "WHERE server_id=? AND scenario_id=? AND province_id=?",
                (*fields.values(), server_id, scenario_id, province_id),
            )

    def update_storage_fields(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        **fields,
    ) -> None:
        """Update multiple storable resource columns at once."""
        bad = set(fields) - _STORAGE_COLUMNS
        if bad:
            raise ValueError(
                f"Unknown storage columns: {bad}. Valid: {sorted(_STORAGE_COLUMNS)}"
            )
        if not fields:
            return
        self.get_or_create_storage(server_id, scenario_id, country_id)
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._connection() as conn:
            conn.execute(
                f"UPDATE country_storage SET {sets} "
                "WHERE server_id=? AND scenario_id=? AND country_id=?",
                (*fields.values(), server_id, scenario_id, country_id),
            )

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

    # ==================================================================
    # RELIGION — country_religions, province_religions
    # ==================================================================

    @staticmethod
    def _create_country_religions(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS country_religions (
                server_id           TEXT    NOT NULL,
                scenario_id         TEXT    NOT NULL,
                country_id          TEXT    NOT NULL,
                religion            TEXT    NOT NULL,
                persecution_active  INTEGER NOT NULL DEFAULT 0,
                persecuted_religion TEXT,
                PRIMARY KEY (server_id, scenario_id, country_id)
            )
        """)

    @staticmethod
    def _create_province_religions(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS province_religions (
                server_id   TEXT NOT NULL,
                scenario_id TEXT NOT NULL,
                province_id TEXT NOT NULL,
                religion    TEXT NOT NULL,
                PRIMARY KEY (server_id, scenario_id, province_id)
            )
        """)

    def upsert_country_religion(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        religion:    str,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO country_religions (server_id, scenario_id, country_id, religion)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(server_id, scenario_id, country_id)
                DO UPDATE SET religion=excluded.religion
            """, (server_id, scenario_id, country_id, religion))

    def get_country_religion(
        self, server_id: str, scenario_id: str, country_id: str
    ) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM country_religions "
                "WHERE server_id=? AND scenario_id=? AND country_id=?",
                (server_id, scenario_id, country_id),
            ).fetchone()
        return dict(row) if row else None

    def get_all_country_religions(
        self, server_id: str, scenario_id: str
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM country_religions WHERE server_id=? AND scenario_id=?",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_country_religion_fields(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        **fields,
    ) -> None:
        allowed = {"religion", "persecution_active", "persecuted_religion"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Unknown country_religions fields: {bad}")
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._connection() as conn:
            conn.execute(
                f"UPDATE country_religions SET {sets} "
                "WHERE server_id=? AND scenario_id=? AND country_id=?",
                (*fields.values(), server_id, scenario_id, country_id),
            )

    def upsert_province_religion(
        self,
        server_id:   str,
        scenario_id: str,
        province_id: str,
        religion:    str,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO province_religions (server_id, scenario_id, province_id, religion)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(server_id, scenario_id, province_id)
                DO UPDATE SET religion=excluded.religion
            """, (server_id, scenario_id, province_id, religion))

    def get_province_religion(
        self, server_id: str, scenario_id: str, province_id: str
    ) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM province_religions "
                "WHERE server_id=? AND scenario_id=? AND province_id=?",
                (server_id, scenario_id, province_id),
            ).fetchone()
        return dict(row) if row else None

    def get_all_province_religions(
        self, server_id: str, scenario_id: str
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM province_religions WHERE server_id=? AND scenario_id=?",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    # ==================================================================
    # DIPLOMACY — relations, alliances, alliance_members
    # ==================================================================

    @staticmethod
    def _create_relations(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS relations (
                server_id    TEXT    NOT NULL,
                scenario_id  TEXT    NOT NULL,
                country_a    TEXT    NOT NULL,
                country_b    TEXT    NOT NULL,
                base_relation REAL   NOT NULL DEFAULT 50,
                PRIMARY KEY (server_id, scenario_id, country_a, country_b)
            )
        """)

    @staticmethod
    def _create_alliances(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alliances (
                alliance_id  TEXT NOT NULL PRIMARY KEY,
                server_id    TEXT NOT NULL,
                scenario_id  TEXT NOT NULL,
                alliance_name TEXT NOT NULL DEFAULT ''
            )
        """)

    @staticmethod
    def _create_alliance_members(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alliance_members (
                alliance_id TEXT NOT NULL,
                country_id  TEXT NOT NULL,
                server_id   TEXT NOT NULL,
                scenario_id TEXT NOT NULL,
                PRIMARY KEY (alliance_id, country_id)
            )
        """)

    def _canonical_pair(self, a: str, b: str) -> tuple[str, str]:
        return (a, b) if a <= b else (b, a)

    def upsert_relation(
        self,
        server_id:    str,
        scenario_id:  str,
        country_a:    str,
        country_b:    str,
        base_relation: float,
    ) -> None:
        ca, cb = self._canonical_pair(country_a, country_b)
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO relations (server_id, scenario_id, country_a, country_b, base_relation)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(server_id, scenario_id, country_a, country_b)
                DO UPDATE SET base_relation=excluded.base_relation
            """, (server_id, scenario_id, ca, cb, float(base_relation)))

    def get_relation(
        self,
        server_id:   str,
        scenario_id: str,
        country_a:   str,
        country_b:   str,
    ) -> dict | None:
        ca, cb = self._canonical_pair(country_a, country_b)
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM relations "
                "WHERE server_id=? AND scenario_id=? AND country_a=? AND country_b=?",
                (server_id, scenario_id, ca, cb),
            ).fetchone()
        return dict(row) if row else None

    def adjust_base_relation(
        self,
        server_id:   str,
        scenario_id: str,
        country_a:   str,
        country_b:   str,
        delta:       float,
    ) -> float:
        """Add delta to base_relation, clamped to [0, 100]. Returns new value."""
        ca, cb = self._canonical_pair(country_a, country_b)
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT base_relation FROM relations "
                "WHERE server_id=? AND scenario_id=? AND country_a=? AND country_b=?",
                (server_id, scenario_id, ca, cb),
            ).fetchone()
            current = float(row["base_relation"]) if row else 50.0
            new_val = max(0.0, min(100.0, current + delta))
            conn.execute("""
                INSERT INTO relations (server_id, scenario_id, country_a, country_b, base_relation)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(server_id, scenario_id, country_a, country_b)
                DO UPDATE SET base_relation=excluded.base_relation
            """, (server_id, scenario_id, ca, cb, new_val))
        return new_val

    def get_all_relations(
        self, server_id: str, scenario_id: str
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM relations WHERE server_id=? AND scenario_id=?",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def insert_alliance(
        self,
        alliance_id:   str,
        server_id:     str,
        scenario_id:   str,
        alliance_name: str = "",
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO alliances "
                "(alliance_id, server_id, scenario_id, alliance_name) "
                "VALUES (?, ?, ?, ?)",
                (alliance_id, server_id, scenario_id, alliance_name),
            )

    def get_alliance(self, alliance_id: str) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM alliances WHERE alliance_id=?",
                (alliance_id,),
            ).fetchone()
        return dict(row) if row else None

    def delete_alliance(self, alliance_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM alliance_members WHERE alliance_id=?",
                (alliance_id,),
            )
            conn.execute(
                "DELETE FROM alliances WHERE alliance_id=?",
                (alliance_id,),
            )

    def add_alliance_member(
        self,
        alliance_id: str,
        country_id:  str,
        server_id:   str,
        scenario_id: str,
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO alliance_members "
                "(alliance_id, country_id, server_id, scenario_id) "
                "VALUES (?, ?, ?, ?)",
                (alliance_id, country_id, server_id, scenario_id),
            )

    def remove_alliance_member(self, alliance_id: str, country_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM alliance_members "
                "WHERE alliance_id=? AND country_id=?",
                (alliance_id, country_id),
            )

    def get_alliance_members(self, alliance_id: str) -> list[str]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT country_id FROM alliance_members WHERE alliance_id=?",
                (alliance_id,),
            ).fetchall()
        return [r[0] for r in rows]

    def get_country_alliances(
        self, server_id: str, scenario_id: str, country_id: str
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT a.* FROM alliances a "
                "JOIN alliance_members m ON a.alliance_id=m.alliance_id "
                "WHERE a.server_id=? AND a.scenario_id=? AND m.country_id=?",
                (server_id, scenario_id, country_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_scenario_alliances(
        self, server_id: str, scenario_id: str
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM alliances WHERE server_id=? AND scenario_id=?",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    # ==================================================================
    # WARS — wars, war_participants
    # ==================================================================

    @staticmethod
    def _create_wars(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS wars (
                war_id               TEXT NOT NULL PRIMARY KEY,
                server_id            TEXT NOT NULL,
                scenario_id          TEXT NOT NULL,
                attacker             TEXT NOT NULL,
                defender             TEXT NOT NULL,
                start_day            INTEGER NOT NULL DEFAULT 0,
                status               TEXT NOT NULL DEFAULT 'active',
                war_score_attacker   REAL NOT NULL DEFAULT 50,
                war_score_defender   REAL NOT NULL DEFAULT 50,
                ceasefire_requested_by TEXT,
                ceasefire_accepted   INTEGER NOT NULL DEFAULT 0
            )
        """)

    @staticmethod
    def _create_war_participants(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS war_participants (
                war_id     TEXT NOT NULL,
                country_id TEXT NOT NULL,
                side       TEXT NOT NULL,
                is_leader  INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (war_id, country_id)
            )
        """)

    def insert_war(
        self,
        war_id:      str,
        server_id:   str,
        scenario_id: str,
        attacker:    str,
        defender:    str,
        start_day:   int,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO wars
                    (war_id, server_id, scenario_id, attacker, defender,
                     start_day, status, war_score_attacker, war_score_defender)
                VALUES (?, ?, ?, ?, ?, ?, 'active', 50, 50)
            """, (war_id, server_id, scenario_id, attacker, defender, start_day))

    def get_war(self, war_id: str) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM wars WHERE war_id=?", (war_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_active_wars(self, server_id: str, scenario_id: str) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM wars "
                "WHERE server_id=? AND scenario_id=? AND status='active'",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_country_active_wars(
        self, server_id: str, scenario_id: str, country_id: str
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT w.* FROM wars w
                LEFT JOIN war_participants wp ON w.war_id=wp.war_id
                WHERE w.server_id=? AND w.scenario_id=? AND w.status='active'
                AND (w.attacker=? OR w.defender=? OR wp.country_id=?)
            """, (server_id, scenario_id, country_id, country_id, country_id)
            ).fetchall()
        return [dict(r) for r in rows]

    def update_war_fields(self, war_id: str, **fields) -> None:
        allowed = {
            "status", "war_score_attacker", "war_score_defender",
            "ceasefire_requested_by", "ceasefire_accepted",
        }
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Unknown war fields: {bad}")
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._connection() as conn:
            conn.execute(
                f"UPDATE wars SET {sets} WHERE war_id=?",
                (*fields.values(), war_id),
            )

    def insert_war_participant(
        self,
        war_id:     str,
        country_id: str,
        side:       str,
        is_leader:  bool = False,
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO war_participants "
                "(war_id, country_id, side, is_leader) VALUES (?, ?, ?, ?)",
                (war_id, country_id, side, int(is_leader)),
            )

    def get_war_participants(self, war_id: str) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM war_participants WHERE war_id=?", (war_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def remove_war_participant(self, war_id: str, country_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM war_participants WHERE war_id=? AND country_id=?",
                (war_id, country_id),
            )

    # ==================================================================
    # ARMIES — armies, army_units
    # ==================================================================

    @staticmethod
    def _create_armies(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS armies (
                army_id                 TEXT NOT NULL PRIMARY KEY,
                server_id               TEXT NOT NULL,
                scenario_id             TEXT NOT NULL,
                country_id              TEXT NOT NULL,
                province_id             TEXT NOT NULL,
                state                   TEXT NOT NULL DEFAULT 'idle',
                strength_pct            REAL NOT NULL DEFAULT 100.0,
                base_province_id        TEXT NOT NULL,
                last_supply_day         INTEGER NOT NULL DEFAULT 0,
                destination_province_id TEXT,
                movement_start_day      INTEGER,
                movement_end_day        INTEGER,
                provinces_traversed     INTEGER NOT NULL DEFAULT 0
            )
        """)

    @staticmethod
    def _create_army_units(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS army_units (
                army_unit_id TEXT NOT NULL PRIMARY KEY,
                army_id      TEXT NOT NULL,
                unit_name    TEXT NOT NULL,
                quantity     INTEGER NOT NULL DEFAULT 0,
                server_id    TEXT NOT NULL,
                scenario_id  TEXT NOT NULL,
                UNIQUE (army_id, unit_name)
            )
        """)

    def insert_army(
        self,
        army_id:         str,
        server_id:       str,
        scenario_id:     str,
        country_id:      str,
        province_id:     str,
        base_province_id: str,
        last_supply_day: int = 0,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO armies
                    (army_id, server_id, scenario_id, country_id, province_id,
                     base_province_id, state, strength_pct, last_supply_day)
                VALUES (?, ?, ?, ?, ?, ?, 'idle', 100.0, ?)
            """, (army_id, server_id, scenario_id, country_id, province_id,
                  base_province_id, last_supply_day))

    def get_army(self, army_id: str) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM armies WHERE army_id=?", (army_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_armies_in_province(
        self, server_id: str, scenario_id: str, province_id: str
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM armies "
                "WHERE server_id=? AND scenario_id=? AND province_id=? "
                "AND state != 'destroyed'",
                (server_id, scenario_id, province_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_country_armies(
        self, server_id: str, scenario_id: str, country_id: str
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM armies "
                "WHERE server_id=? AND scenario_id=? AND country_id=?",
                (server_id, scenario_id, country_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all_armies(
        self, server_id: str, scenario_id: str
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM armies WHERE server_id=? AND scenario_id=?",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_army_fields(self, army_id: str, **fields) -> None:
        allowed = {
            "province_id", "state", "strength_pct", "base_province_id",
            "last_supply_day", "destination_province_id",
            "movement_start_day", "movement_end_day", "provinces_traversed",
            "country_id", "recruitment_end_day",
        }
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Unknown army fields: {bad}")
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._connection() as conn:
            conn.execute(
                f"UPDATE armies SET {sets} WHERE army_id=?",
                (*fields.values(), army_id),
            )

    def delete_army(self, army_id: str) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM army_units WHERE army_id=?", (army_id,))
            conn.execute("DELETE FROM armies WHERE army_id=?", (army_id,))

    def upsert_army_unit(
        self,
        army_unit_id: str,
        army_id:      str,
        unit_name:    str,
        quantity:     int,
        server_id:    str,
        scenario_id:  str,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO army_units
                    (army_unit_id, army_id, unit_name, quantity, server_id, scenario_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(army_id, unit_name)
                DO UPDATE SET quantity=quantity+excluded.quantity
            """, (army_unit_id, army_id, unit_name, quantity, server_id, scenario_id))

    def set_army_unit_quantity(
        self, army_id: str, unit_name: str, quantity: int
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE army_units SET quantity=? "
                "WHERE army_id=? AND unit_name=?",
                (quantity, army_id, unit_name),
            )

    def get_army_units(self, army_id: str) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM army_units WHERE army_id=? AND quantity>0",
                (army_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def remove_army_unit(self, army_id: str, unit_name: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM army_units WHERE army_id=? AND unit_name=?",
                (army_id, unit_name),
            )

    # ==================================================================
    # BATTLES — battles
    # ==================================================================

    @staticmethod
    def _create_battles(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS battles (
                battle_id       TEXT NOT NULL PRIMARY KEY,
                war_id          TEXT NOT NULL,
                server_id       TEXT NOT NULL,
                scenario_id     TEXT NOT NULL,
                province_id     TEXT NOT NULL,
                army_a_id       TEXT NOT NULL,
                army_b_id       TEXT NOT NULL,
                start_day       INTEGER NOT NULL,
                status          TEXT NOT NULL DEFAULT 'active',
                winner_army_id  TEXT,
                last_tick_day   INTEGER NOT NULL DEFAULT 0
            )
        """)

    def insert_battle(
        self,
        battle_id:   str,
        war_id:      str,
        server_id:   str,
        scenario_id: str,
        province_id: str,
        army_a_id:   str,
        army_b_id:   str,
        start_day:   int,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO battles
                    (battle_id, war_id, server_id, scenario_id, province_id,
                     army_a_id, army_b_id, start_day, status, last_tick_day)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
            """, (battle_id, war_id, server_id, scenario_id, province_id,
                  army_a_id, army_b_id, start_day, start_day))

    def get_battle(self, battle_id: str) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM battles WHERE battle_id=?", (battle_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_active_battles(self, server_id: str, scenario_id: str) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM battles "
                "WHERE server_id=? AND scenario_id=? AND status='active'",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_battle_in_province(
        self, server_id: str, scenario_id: str, province_id: str
    ) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM battles "
                "WHERE server_id=? AND scenario_id=? AND province_id=? AND status='active'",
                (server_id, scenario_id, province_id),
            ).fetchone()
        return dict(row) if row else None

    def update_battle_fields(self, battle_id: str, **fields) -> None:
        allowed = {"status", "winner_army_id", "last_tick_day"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Unknown battle fields: {bad}")
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._connection() as conn:
            conn.execute(
                f"UPDATE battles SET {sets} WHERE battle_id=?",
                (*fields.values(), battle_id),
            )

    # ==================================================================
    # OCCUPATION — province_occupation
    # ==================================================================

    @staticmethod
    def _create_province_occupation(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS province_occupation (
                server_id            TEXT    NOT NULL,
                scenario_id          TEXT    NOT NULL,
                province_id          TEXT    NOT NULL,
                war_id               TEXT    NOT NULL,
                occupying_country    TEXT    NOT NULL,
                occupation_start_day INTEGER NOT NULL,
                is_occupied          INTEGER NOT NULL DEFAULT 0,
                war_score_awarded    INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (server_id, scenario_id, province_id)
            )
        """)

    def upsert_province_occupation(
        self,
        server_id:            str,
        scenario_id:          str,
        province_id:          str,
        war_id:               str,
        occupying_country:    str,
        occupation_start_day: int,
        is_occupied:          int = 0,
        war_score_awarded:    int = 0,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO province_occupation
                    (server_id, scenario_id, province_id, war_id, occupying_country,
                     occupation_start_day, is_occupied, war_score_awarded)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(server_id, scenario_id, province_id)
                DO UPDATE SET
                    war_id=excluded.war_id,
                    occupying_country=excluded.occupying_country,
                    occupation_start_day=excluded.occupation_start_day,
                    is_occupied=excluded.is_occupied,
                    war_score_awarded=excluded.war_score_awarded
            """, (server_id, scenario_id, province_id, war_id, occupying_country,
                  occupation_start_day, is_occupied, war_score_awarded))

    def get_province_occupation(
        self, server_id: str, scenario_id: str, province_id: str
    ) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM province_occupation "
                "WHERE server_id=? AND scenario_id=? AND province_id=?",
                (server_id, scenario_id, province_id),
            ).fetchone()
        return dict(row) if row else None

    def get_war_occupations(self, war_id: str) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM province_occupation WHERE war_id=?",
                (war_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_province_occupation_fields(
        self, server_id: str, scenario_id: str, province_id: str, **fields
    ) -> None:
        allowed = {"is_occupied", "war_score_awarded", "occupying_country",
                   "occupation_start_day", "war_id"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"Unknown occupation fields: {bad}")
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._connection() as conn:
            conn.execute(
                f"UPDATE province_occupation SET {sets} "
                "WHERE server_id=? AND scenario_id=? AND province_id=?",
                (*fields.values(), server_id, scenario_id, province_id),
            )

    def delete_province_occupation(
        self, server_id: str, scenario_id: str, province_id: str
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM province_occupation "
                "WHERE server_id=? AND scenario_id=? AND province_id=?",
                (server_id, scenario_id, province_id),
            )

    # ==================================================================
    # PROVINCE CORES — province_cores
    # ==================================================================

    @staticmethod
    def _create_province_cores(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS province_cores (
                server_id           TEXT    NOT NULL,
                scenario_id         TEXT    NOT NULL,
                province_id         TEXT    NOT NULL,
                country_id          TEXT    NOT NULL,
                is_core             INTEGER NOT NULL DEFAULT 1,
                conversion_start_day INTEGER,
                conversion_end_day   INTEGER,
                PRIMARY KEY (server_id, scenario_id, province_id, country_id)
            )
        """)

    def upsert_province_core(
        self,
        server_id:            str,
        scenario_id:          str,
        province_id:          str,
        country_id:           str,
        is_core:              int = 1,
        conversion_start_day: int | None = None,
        conversion_end_day:   int | None = None,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO province_cores
                    (server_id, scenario_id, province_id, country_id,
                     is_core, conversion_start_day, conversion_end_day)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(server_id, scenario_id, province_id, country_id)
                DO UPDATE SET
                    is_core=excluded.is_core,
                    conversion_start_day=excluded.conversion_start_day,
                    conversion_end_day=excluded.conversion_end_day
            """, (server_id, scenario_id, province_id, country_id,
                  is_core, conversion_start_day, conversion_end_day))

    def get_province_core(
        self, server_id: str, scenario_id: str, province_id: str, country_id: str
    ) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM province_cores "
                "WHERE server_id=? AND scenario_id=? "
                "AND province_id=? AND country_id=?",
                (server_id, scenario_id, province_id, country_id),
            ).fetchone()
        return dict(row) if row else None

    def get_pending_core_conversions(
        self, server_id: str, scenario_id: str
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM province_cores "
                "WHERE server_id=? AND scenario_id=? AND is_core=0",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_non_core_provinces(
        self, server_id: str, scenario_id: str, country_id: str
    ) -> int:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM province_cores "
                "WHERE server_id=? AND scenario_id=? AND country_id=? AND is_core=0",
                (server_id, scenario_id, country_id),
            ).fetchone()
        return row[0] if row else 0

    def count_province_religion_mismatches(
        self, server_id: str, scenario_id: str, country_id: str
    ) -> int:
        """
        Count provinces owned by country_id whose religion differs from the
        country's main religion.  Provinces with no religion entry are also
        counted as a mismatch.  Returns 0 if the country has no religion row.
        """
        with self._connection() as conn:
            cr = conn.execute(
                "SELECT religion FROM country_religions "
                "WHERE server_id=? AND scenario_id=? AND country_id=?",
                (server_id, scenario_id, country_id),
            ).fetchone()
            if cr is None:
                return 0
            country_religion = cr[0]
            row = conn.execute(
                """
                SELECT COUNT(*) FROM provinces p
                LEFT JOIN province_religions pr
                    ON pr.province_id  = p.province_id
                    AND pr.server_id   = p.server_id
                    AND pr.scenario_id = p.scenario_id
                WHERE p.server_id=? AND p.scenario_id=? AND p.owner_country=?
                AND (pr.religion IS NULL OR pr.religion != ?)
                """,
                (server_id, scenario_id, country_id, country_religion),
            ).fetchone()
        return row[0] if row else 0

    # ==================================================================
    # PROVINCE RELIGION CONVERSION — province_religion_conversion
    # ==================================================================

    @staticmethod
    def _create_province_religion_conversion(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS province_religion_conversion (
                server_id           TEXT    NOT NULL,
                scenario_id         TEXT    NOT NULL,
                province_id         TEXT    NOT NULL,
                from_religion       TEXT    NOT NULL,
                to_religion         TEXT    NOT NULL,
                conversion_start_day INTEGER NOT NULL,
                conversion_end_day   INTEGER NOT NULL,
                PRIMARY KEY (server_id, scenario_id, province_id)
            )
        """)

    def upsert_province_religion_conversion(
        self,
        server_id:           str,
        scenario_id:         str,
        province_id:         str,
        from_religion:       str,
        to_religion:         str,
        conversion_start_day: int,
        conversion_end_day:   int,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT INTO province_religion_conversion
                    (server_id, scenario_id, province_id, from_religion,
                     to_religion, conversion_start_day, conversion_end_day)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(server_id, scenario_id, province_id)
                DO UPDATE SET
                    from_religion=excluded.from_religion,
                    to_religion=excluded.to_religion,
                    conversion_start_day=excluded.conversion_start_day,
                    conversion_end_day=excluded.conversion_end_day
            """, (server_id, scenario_id, province_id, from_religion,
                  to_religion, conversion_start_day, conversion_end_day))

    def get_province_religion_conversion(
        self, server_id: str, scenario_id: str, province_id: str
    ) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM province_religion_conversion "
                "WHERE server_id=? AND scenario_id=? AND province_id=?",
                (server_id, scenario_id, province_id),
            ).fetchone()
        return dict(row) if row else None

    def get_pending_religion_conversions(
        self, server_id: str, scenario_id: str
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM province_religion_conversion "
                "WHERE server_id=? AND scenario_id=?",
                (server_id, scenario_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_province_religion_conversion(
        self, server_id: str, scenario_id: str, province_id: str
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM province_religion_conversion "
                "WHERE server_id=? AND scenario_id=? AND province_id=?",
                (server_id, scenario_id, province_id),
            )

    # ==================================================================
    # WAR REPARATIONS — war_reparations
    # ==================================================================

    @staticmethod
    def _create_war_reparations(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS war_reparations (
                war_id          TEXT    NOT NULL,
                loser_country   TEXT    NOT NULL,
                winner_country  TEXT    NOT NULL,
                server_id       TEXT    NOT NULL,
                scenario_id     TEXT    NOT NULL,
                start_day       INTEGER NOT NULL,
                end_day         INTEGER NOT NULL,
                PRIMARY KEY (war_id, loser_country, winner_country)
            )
        """)

    def insert_war_reparations(
        self,
        war_id:         str,
        loser_country:  str,
        winner_country: str,
        server_id:      str,
        scenario_id:    str,
        start_day:      int,
        end_day:        int,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO war_reparations
                    (war_id, loser_country, winner_country, server_id, scenario_id,
                     start_day, end_day)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (war_id, loser_country, winner_country, server_id, scenario_id,
                  start_day, end_day))

    def get_active_reparations(
        self, server_id: str, scenario_id: str, current_day: int
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM war_reparations "
                "WHERE server_id=? AND scenario_id=? "
                "AND start_day<=? AND end_day>=?",
                (server_id, scenario_id, current_day, current_day),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_country_reparations_as_loser(
        self, server_id: str, scenario_id: str, country_id: str, current_day: int
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM war_reparations "
                "WHERE server_id=? AND scenario_id=? "
                "AND loser_country=? AND end_day>=?",
                (server_id, scenario_id, country_id, current_day),
            ).fetchall()
        return [dict(r) for r in rows]

    # ==================================================================
    # PUPPET STATES — puppet_states
    # ==================================================================

    @staticmethod
    def _create_puppet_states(conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS puppet_states (
                server_id        TEXT NOT NULL,
                scenario_id      TEXT NOT NULL,
                puppet_country   TEXT NOT NULL,
                overlord_country TEXT NOT NULL,
                PRIMARY KEY (server_id, scenario_id, puppet_country)
            )
        """)

    def insert_puppet_state(
        self,
        server_id:        str,
        scenario_id:      str,
        puppet_country:   str,
        overlord_country: str,
    ) -> None:
        with self._connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO puppet_states
                    (server_id, scenario_id, puppet_country, overlord_country)
                VALUES (?, ?, ?, ?)
            """, (server_id, scenario_id, puppet_country, overlord_country))

    def get_puppet_state(
        self, server_id: str, scenario_id: str, puppet_country: str
    ) -> dict | None:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM puppet_states "
                "WHERE server_id=? AND scenario_id=? AND puppet_country=?",
                (server_id, scenario_id, puppet_country),
            ).fetchone()
        return dict(row) if row else None

    def get_overlord_puppets(
        self, server_id: str, scenario_id: str, overlord_country: str
    ) -> list[dict]:
        with self._connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM puppet_states "
                "WHERE server_id=? AND scenario_id=? AND overlord_country=?",
                (server_id, scenario_id, overlord_country),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_puppet_state(
        self, server_id: str, scenario_id: str, puppet_country: str
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM puppet_states "
                "WHERE server_id=? AND scenario_id=? AND puppet_country=?",
                (server_id, scenario_id, puppet_country),
            )

    def is_puppet(
        self, server_id: str, scenario_id: str, country_id: str
    ) -> bool:
        return self.get_puppet_state(server_id, scenario_id, country_id) is not None

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
