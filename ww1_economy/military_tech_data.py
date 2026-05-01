"""
WW1 MILITARY TECHNOLOGY — STATIC TREE DEFINITIONS
---------------------------------------------------
Pure data module.  No I/O, no database access.

Defines the military technology tree and the mapping from technology
unlocks → recruitable unit names.  All durations are expressed in
in-game months; use MilTechDef.duration_days for day-based arithmetic.

Tech IDs use snake_case strings (e.g. "pre_industrial_military_doctrine").
"""

from __future__ import annotations

from dataclasses import dataclass

from ww1_economy.tech_data import DAYS_PER_MONTH   # 30 — shared constant


# ---------------------------------------------------------------------------
# Military technology definition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MilTechDef:
    """Immutable definition of one military technology node."""

    tech_id:         str
    name:            str
    duration_months: int
    prerequisites:   tuple[str, ...]   # mil tech_ids that must be unlocked first
    unlocks_units:   tuple[str, ...]   # unit_name strings recruitable on completion

    @property
    def duration_days(self) -> int:
        return self.duration_months * DAYS_PER_MONTH


# ---------------------------------------------------------------------------
# Military technology tree
# ---------------------------------------------------------------------------

MILITARY_TECH_TREE: dict[str, MilTechDef] = {

    # ── Root ─────────────────────────────────────────────────────────────────

    "pre_industrial_military_doctrine": MilTechDef(
        tech_id         = "pre_industrial_military_doctrine",
        name            = "Pre-Industrial Military Doctrine",
        duration_months = 1,
        prerequisites   = (),
        unlocks_units   = (),
    ),

    # ── 1. Early Infantry branch ──────────────────────────────────────────────

    "early_infantry": MilTechDef(
        tech_id         = "early_infantry",
        name            = "Early Infantry",
        duration_months = 2,
        prerequisites   = ("pre_industrial_military_doctrine",),
        unlocks_units   = ("Line Infantry",),
    ),

    "line_infantry": MilTechDef(
        tech_id         = "line_infantry",
        name            = "Line Infantry",
        duration_months = 3,
        prerequisites   = ("early_infantry",),
        unlocks_units   = (),
    ),

    "elite_line_infantry": MilTechDef(
        tech_id         = "elite_line_infantry",
        name            = "Elite Line Infantry",
        duration_months = 6,
        prerequisites   = ("line_infantry",),
        unlocks_units   = ("Elite Line Infantry",),
    ),

    # ── 2. Grenadier branch ───────────────────────────────────────────────────

    "grenadier": MilTechDef(
        tech_id         = "grenadier",
        name            = "Grenadier",
        duration_months = 2,
        prerequisites   = ("pre_industrial_military_doctrine",),
        unlocks_units   = ("Grenadier",),
    ),

    "elite_grenadier": MilTechDef(
        tech_id         = "elite_grenadier",
        name            = "Elite Grenadier",
        duration_months = 3,
        prerequisites   = ("grenadier",),
        unlocks_units   = ("Elite Grenadier",),
    ),

    # ── 3. Cavalry branch ─────────────────────────────────────────────────────

    "cavalry": MilTechDef(
        tech_id         = "cavalry",
        name            = "Cavalry",
        duration_months = 2,
        prerequisites   = ("pre_industrial_military_doctrine",),
        unlocks_units   = (),
    ),

    "heavy_cavalry": MilTechDef(
        tech_id         = "heavy_cavalry",
        name            = "Heavy Cavalry",
        duration_months = 3,
        prerequisites   = ("cavalry",),
        unlocks_units   = ("Heavy Cavalry",),
    ),

    "elite_cavalry": MilTechDef(
        tech_id         = "elite_cavalry",
        name            = "Elite Cavalry",
        duration_months = 5,
        prerequisites   = ("heavy_cavalry",),
        unlocks_units   = ("Elite Cavalry",),
    ),

    # ── 4. Support Units branch ───────────────────────────────────────────────

    "support_units": MilTechDef(
        tech_id         = "support_units",
        name            = "Support Units",
        duration_months = 3,
        prerequisites   = ("pre_industrial_military_doctrine",),
        unlocks_units   = ("Elite Archers",),
    ),

    "elite_archers": MilTechDef(
        tech_id         = "elite_archers",
        name            = "Elite Archers Tech",
        duration_months = 2,
        prerequisites   = ("support_units",),
        unlocks_units   = (),
    ),

    "recon_rifleman": MilTechDef(
        tech_id         = "recon_rifleman",
        name            = "Recon Rifleman",
        duration_months = 3,
        prerequisites   = ("support_units",),
        unlocks_units   = ("Recon Rifleman",),
    ),

    "cannons": MilTechDef(
        tech_id         = "cannons",
        name            = "Cannons",
        duration_months = 3,
        prerequisites   = ("support_units",),
        unlocks_units   = ("Cannons",),
    ),

    "elite_cannons": MilTechDef(
        tech_id         = "elite_cannons",
        name            = "Elite Cannons",
        duration_months = 4,
        prerequisites   = ("cannons",),
        unlocks_units   = ("Elite Cannons",),
    ),

    # ── 5. Naval Warfare branch ───────────────────────────────────────────────

    "naval_warfare_doctrine": MilTechDef(
        tech_id         = "naval_warfare_doctrine",
        name            = "Naval Warfare Doctrine",
        duration_months = 3,
        prerequisites   = ("pre_industrial_military_doctrine",),
        unlocks_units   = (),
    ),

    "gunboats": MilTechDef(
        tech_id         = "gunboats",
        name            = "Gunboats",
        duration_months = 6,
        prerequisites   = ("naval_warfare_doctrine",),
        unlocks_units   = ("Gunboats",),
    ),

    "early_battleships": MilTechDef(
        tech_id         = "early_battleships",
        name            = "Early Battleships",
        duration_months = 8,
        prerequisites   = ("naval_warfare_doctrine",),
        unlocks_units   = ("Early Battleships",),
    ),

    "battleships": MilTechDef(
        tech_id         = "battleships",
        name            = "Battleships",
        duration_months = 12,
        prerequisites   = ("early_battleships",),
        unlocks_units   = ("Battleships",),
    ),

    "early_destroyers": MilTechDef(
        tech_id         = "early_destroyers",
        name            = "Early Destroyers",
        duration_months = 9,
        prerequisites   = ("naval_warfare_doctrine",),
        unlocks_units   = ("Early Destroyers",),
    ),

    "light_carriers": MilTechDef(
        tech_id         = "light_carriers",
        name            = "Light Carriers",
        duration_months = 18,
        prerequisites   = ("naval_warfare_doctrine",),
        unlocks_units   = ("Light Carriers",),
    ),

    # ── 6. Modern Warfare branch ──────────────────────────────────────────────

    "modern_warfare_doctrine": MilTechDef(
        tech_id         = "modern_warfare_doctrine",
        name            = "Modern Warfare Doctrine",
        duration_months = 6,
        prerequisites   = ("pre_industrial_military_doctrine",),
        unlocks_units   = (),
    ),

    "rifleman": MilTechDef(
        tech_id         = "rifleman",
        name            = "Rifleman",
        duration_months = 9,
        prerequisites   = ("modern_warfare_doctrine",),
        unlocks_units   = ("Rifleman",),
    ),

    "early_trench_infantry": MilTechDef(
        tech_id         = "early_trench_infantry",
        name            = "Early Trench Infantry",
        duration_months = 12,
        prerequisites   = ("modern_warfare_doctrine",),
        unlocks_units   = ("Early Trench Infantry",),
    ),

    "mechanised_army": MilTechDef(
        tech_id         = "mechanised_army",
        name            = "Mechanised Army",
        duration_months = 6,
        prerequisites   = ("modern_warfare_doctrine",),
        unlocks_units   = (),
    ),

    "early_tanks": MilTechDef(
        tech_id         = "early_tanks",
        name            = "Early Tanks",
        duration_months = 18,
        prerequisites   = ("mechanised_army",),
        unlocks_units   = ("Early Tanks",),
    ),

    "tanks": MilTechDef(
        tech_id         = "tanks",
        name            = "Tanks",
        duration_months = 24,
        prerequisites   = ("mechanised_army",),
        unlocks_units   = ("Tanks",),
    ),

    "early_mechanised_infantry": MilTechDef(
        tech_id         = "early_mechanised_infantry",
        name            = "Early Mechanised Infantry",
        duration_months = 6,
        prerequisites   = ("mechanised_army",),
        unlocks_units   = (),
    ),

    "mechanised_infantry": MilTechDef(
        tech_id         = "mechanised_infantry",
        name            = "Mechanised Infantry",
        duration_months = 12,
        prerequisites   = ("mechanised_army",),
        unlocks_units   = ("Mechanised Infantry", "Advanced Mechanised Infantry"),
    ),

    "artillery": MilTechDef(
        tech_id         = "artillery",
        name            = "Artillery",
        duration_months = 6,
        prerequisites   = ("mechanised_army",),
        unlocks_units   = ("Artillery",),
    ),

    # ── 7. Aerial Warfare branch ──────────────────────────────────────────────

    "aerial_warfare": MilTechDef(
        tech_id         = "aerial_warfare",
        name            = "Aerial Warfare",
        duration_months = 6,
        prerequisites   = ("pre_industrial_military_doctrine",),
        unlocks_units   = (),
    ),

    "observation_balloons": MilTechDef(
        tech_id         = "observation_balloons",
        name            = "Observation Balloons",
        duration_months = 9,
        prerequisites   = ("aerial_warfare",),
        unlocks_units   = ("Observation Balloons",),
    ),

    "early_aviation": MilTechDef(
        tech_id         = "early_aviation",
        name            = "Early Aviation",
        duration_months = 6,
        prerequisites   = ("aerial_warfare",),
        unlocks_units   = ("Light Aircraft",),
    ),

    # Early Bombers: requires early_aviation + observation_balloons + artillery
    "early_bombers": MilTechDef(
        tech_id         = "early_bombers",
        name            = "Early Bombers",
        duration_months = 12,
        prerequisites   = ("early_aviation", "observation_balloons", "artillery"),
        unlocks_units   = ("Early Bombers",),
    ),

    # Early Fighters: requires early_aviation + observation_balloons
    "early_fighters": MilTechDef(
        tech_id         = "early_fighters",
        name            = "Early Fighters",
        duration_months = 18,
        prerequisites   = ("early_aviation", "observation_balloons"),
        unlocks_units   = ("Early Fighters",),
    ),
}


# ---------------------------------------------------------------------------
# Derived lookups
# ---------------------------------------------------------------------------

# Maps unit_name → mil tech_id required before that unit can be recruited.
# Built from MILITARY_TECH_TREE.unlocks_units.
UNIT_TECH_REQUIREMENTS: dict[str, str] = {}
for _tid, _tdef in MILITARY_TECH_TREE.items():
    for _uname in _tdef.unlocks_units:
        UNIT_TECH_REQUIREMENTS[_uname] = _tid

# Quick frozenset for O(1) membership checks
TECH_GATED_UNITS: frozenset[str] = frozenset(UNIT_TECH_REQUIREMENTS)
