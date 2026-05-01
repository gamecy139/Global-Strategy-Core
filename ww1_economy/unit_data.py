"""
WW1 MILITARY — UNIT (TROOP) DEFINITIONS
-----------------------------------------
Pure data module.  No I/O, no database access.

Defines every recruitable unit with its static stats.  These definitions are
seeded into the ``troop_definitions`` DB table per (server_id, scenario_id)
by ``TroopDefinitionSystem.seed_definitions()``.

Categories
----------
  F1   — Frontline infantry (primary line)
  F2   — Frontline infantry (secondary / specialised)
  FL1  — Flank units (cavalry, armour)
  S1   — Support (reconnaissance, observation, air superiority)
  S2   — Support (fire support: artillery, bombers)
  N1   — Naval units

Fields
------
  unit_name             — human-readable name (PK in DB alongside server/scenario)
  category              — one of F1, F2, FL1, S1, S2, N1
  required_tech         — military tech_id that must be unlocked to recruit
  population_required   — population cost per unit
  gold_cost             — gold cost per unit
  recruitment_time_days — game-days to recruit one unit
  speed_modifier        — movement speed multiplier (1.0 = normal)
  battle_points         — combat strength value
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Unit definition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class UnitDef:
    """Immutable definition of one recruitable unit type."""

    unit_name:             str
    category:              str    # F1 | F2 | FL1 | S1 | S2 | N1
    required_tech:         str    # military tech_id
    population_required:   int
    gold_cost:             float
    recruitment_time_days: int
    speed_modifier:        float
    battle_points:         int


# ---------------------------------------------------------------------------
# All unit definitions
# ---------------------------------------------------------------------------

UNIT_DEFINITIONS: dict[str, UnitDef] = {

    # ── F1 — Frontline ────────────────────────────────────────────────────────

    "Line Infantry": UnitDef(
        unit_name             = "Line Infantry",
        category              = "F1",
        required_tech         = "early_infantry",
        population_required   = 1,
        gold_cost             = 3.0,
        recruitment_time_days = 30,
        speed_modifier        = 1.0,
        battle_points         = 10,
    ),

    "Elite Line Infantry": UnitDef(
        unit_name             = "Elite Line Infantry",
        category              = "F1",
        required_tech         = "elite_line_infantry",
        population_required   = 1,
        gold_cost             = 5.0,
        recruitment_time_days = 45,
        speed_modifier        = 1.0,
        battle_points         = 16,
    ),

    "Rifleman": UnitDef(
        unit_name             = "Rifleman",
        category              = "F1",
        required_tech         = "rifleman",
        population_required   = 1,
        gold_cost             = 7.0,
        recruitment_time_days = 60,
        speed_modifier        = 1.0,
        battle_points         = 24,
    ),

    "Early Trench Infantry": UnitDef(
        unit_name             = "Early Trench Infantry",
        category              = "F1",
        required_tech         = "early_trench_infantry",
        population_required   = 1,
        gold_cost             = 10.0,
        recruitment_time_days = 75,
        speed_modifier        = 0.9,
        battle_points         = 35,
    ),

    # ── F2 — Frontline (specialised) ─────────────────────────────────────────

    "Grenadier": UnitDef(
        unit_name             = "Grenadier",
        category              = "F2",
        required_tech         = "grenadier",
        population_required   = 1,
        gold_cost             = 4.0,
        recruitment_time_days = 36,
        speed_modifier        = 1.0,
        battle_points         = 12,
    ),

    "Elite Grenadier": UnitDef(
        unit_name             = "Elite Grenadier",
        category              = "F2",
        required_tech         = "elite_grenadier",
        population_required   = 1,
        gold_cost             = 6.0,
        recruitment_time_days = 54,
        speed_modifier        = 1.0,
        battle_points         = 18,
    ),

    "Mechanised Infantry": UnitDef(
        unit_name             = "Mechanised Infantry",
        category              = "F2",
        required_tech         = "mechanised_infantry",
        population_required   = 1,
        gold_cost             = 12.0,
        recruitment_time_days = 75,
        speed_modifier        = 0.9,
        battle_points         = 30,
    ),

    "Advanced Mechanised Infantry": UnitDef(
        unit_name             = "Advanced Mechanised Infantry",
        category              = "F2",
        required_tech         = "mechanised_infantry",
        population_required   = 1,
        gold_cost             = 16.0,
        recruitment_time_days = 90,
        speed_modifier        = 0.85,
        battle_points         = 42,
    ),

    # ── FL1 — Flank ───────────────────────────────────────────────────────────

    "Heavy Cavalry": UnitDef(
        unit_name             = "Heavy Cavalry",
        category              = "FL1",
        required_tech         = "heavy_cavalry",
        population_required   = 1,
        gold_cost             = 5.0,
        recruitment_time_days = 45,
        speed_modifier        = 1.2,
        battle_points         = 14,
    ),

    "Elite Cavalry": UnitDef(
        unit_name             = "Elite Cavalry",
        category              = "FL1",
        required_tech         = "elite_cavalry",
        population_required   = 1,
        gold_cost             = 7.0,
        recruitment_time_days = 60,
        speed_modifier        = 1.2,
        battle_points         = 20,
    ),

    "Early Tanks": UnitDef(
        unit_name             = "Early Tanks",
        category              = "FL1",
        required_tech         = "early_tanks",
        population_required   = 3,
        gold_cost             = 15.0,
        recruitment_time_days = 90,
        speed_modifier        = 0.8,
        battle_points         = 40,
    ),

    "Tanks": UnitDef(
        unit_name             = "Tanks",
        category              = "FL1",
        required_tech         = "tanks",
        population_required   = 3,
        gold_cost             = 20.0,
        recruitment_time_days = 120,
        speed_modifier        = 0.7,
        battle_points         = 55,
    ),

    # ── S1 — Support (recon / air superiority) ────────────────────────────────

    "Elite Archers": UnitDef(
        unit_name             = "Elite Archers",
        category              = "S1",
        required_tech         = "support_units",
        population_required   = 1,
        gold_cost             = 4.0,
        recruitment_time_days = 30,
        speed_modifier        = 1.0,
        battle_points         = 9,
    ),

    "Recon Rifleman": UnitDef(
        unit_name             = "Recon Rifleman",
        category              = "S1",
        required_tech         = "recon_rifleman",
        population_required   = 1,
        gold_cost             = 6.0,
        recruitment_time_days = 45,
        speed_modifier        = 1.1,
        battle_points         = 15,
    ),

    "Observation Balloons": UnitDef(
        unit_name             = "Observation Balloons",
        category              = "S1",
        required_tech         = "observation_balloons",
        population_required   = 4,
        gold_cost             = 8.0,
        recruitment_time_days = 60,
        speed_modifier        = 0.9,
        battle_points         = 22,
    ),

    "Early Fighters": UnitDef(
        unit_name             = "Early Fighters",
        category              = "S1",
        required_tech         = "early_fighters",
        population_required   = 2,
        gold_cost             = 14.0,
        recruitment_time_days = 90,
        speed_modifier        = 1.3,
        battle_points         = 38,
    ),

    "Light Aircraft": UnitDef(
        unit_name             = "Light Aircraft",
        category              = "S1",
        required_tech         = "early_aviation",
        population_required   = 2,
        gold_cost             = 18.0,
        recruitment_time_days = 120,
        speed_modifier        = 1.4,
        battle_points         = 50,
    ),

    # ── S2 — Support (fire support) ───────────────────────────────────────────

    "Cannons": UnitDef(
        unit_name             = "Cannons",
        category              = "S2",
        required_tech         = "cannons",
        population_required   = 3,
        gold_cost             = 6.0,
        recruitment_time_days = 45,
        speed_modifier        = 0.8,
        battle_points         = 16,
    ),

    "Elite Cannons": UnitDef(
        unit_name             = "Elite Cannons",
        category              = "S2",
        required_tech         = "elite_cannons",
        population_required   = 3,
        gold_cost             = 8.0,
        recruitment_time_days = 60,
        speed_modifier        = 0.8,
        battle_points         = 22,
    ),

    "Artillery": UnitDef(
        unit_name             = "Artillery",
        category              = "S2",
        required_tech         = "artillery",
        population_required   = 4,
        gold_cost             = 12.0,
        recruitment_time_days = 75,
        speed_modifier        = 0.7,
        battle_points         = 32,
    ),

    "Early Bombers": UnitDef(
        unit_name             = "Early Bombers",
        category              = "S2",
        required_tech         = "early_bombers",
        population_required   = 2,
        gold_cost             = 18.0,
        recruitment_time_days = 105,
        speed_modifier        = 1.1,
        battle_points         = 48,
    ),

    # ── N1 — Naval ────────────────────────────────────────────────────────────

    "Gunboats": UnitDef(
        unit_name             = "Gunboats",
        category              = "N1",
        required_tech         = "gunboats",
        population_required   = 3,
        gold_cost             = 10.0,
        recruitment_time_days = 90,
        speed_modifier        = 1.2,
        battle_points         = 25,
    ),

    "Early Battleships": UnitDef(
        unit_name             = "Early Battleships",
        category              = "N1",
        required_tech         = "early_battleships",
        population_required   = 3,
        gold_cost             = 18.0,
        recruitment_time_days = 150,
        speed_modifier        = 1.0,
        battle_points         = 45,
    ),

    "Battleships": UnitDef(
        unit_name             = "Battleships",
        category              = "N1",
        required_tech         = "battleships",
        population_required   = 5,
        gold_cost             = 25.0,
        recruitment_time_days = 210,
        speed_modifier        = 0.9,
        battle_points         = 70,
    ),

    "Early Destroyers": UnitDef(
        unit_name             = "Early Destroyers",
        category              = "N1",
        required_tech         = "early_destroyers",
        population_required   = 10,
        gold_cost             = 20.0,
        recruitment_time_days = 180,
        speed_modifier        = 1.1,
        battle_points         = 55,
    ),

    "Light Carriers": UnitDef(
        unit_name             = "Light Carriers",
        category              = "N1",
        required_tech         = "light_carriers",
        population_required   = 15,
        gold_cost             = 35.0,
        recruitment_time_days = 300,
        speed_modifier        = 1.0,
        battle_points         = 95,
    ),
}

# Sorted list of all valid categories for validation
UNIT_CATEGORIES: frozenset[str] = frozenset({"F1", "F2", "FL1", "S1", "S2", "N1"})
