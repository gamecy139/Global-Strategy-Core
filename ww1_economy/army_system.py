"""
WW1 ARMY SYSTEM
----------------
Manages armies: creation, unit composition, movement, and supply.

Movement:
    travel_time = ceil(provinces_count × 7 / army_speed_modifier)
    Army speed  = weighted average of unit speed_modifiers by quantity.

Supply (every 10 days, only when war > 10 days):
    army_pop = sum(unit.quantity × population_required)
    food_need     = ceil(army_pop / 100)   → drawn from meat first, then grain
    ammo_need     = ceil(army_pop / 80)    → drawn from ammunition
    medicine_need = ceil(army_pop / 250)   → drawn from medicines

Strength penalties (applied when a resource runs out, per 10-day period):
    no ammo     → -10% strength
    no food     → -20% strength
    no medicines → -15% strength

Strength bonus (per 10-day period, if opinion > 80):
    +5% strength (capped at 120%)

Strength bounds: [0%, 120%].
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field

from ww1_economy.db import EconomyDB


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRAVEL_DAYS_PER_PROVINCE: int   = 7
SUPPLY_INTERVAL_DAYS:     int   = 10   # supply consumed every 10 days
MIN_WAR_DAYS_FOR_SUPPLY:  int   = 10   # supply only if war > 10 days old

STRENGTH_BASE:  float = 100.0
STRENGTH_MIN:   float = 0.0
STRENGTH_MAX:   float = 120.0
STRENGTH_RETREAT_THRESHOLD: float = 30.0  # retreat if strength ≤ this

PENALTY_NO_AMMO:     float = -10.0
PENALTY_NO_FOOD:     float = -20.0
PENALTY_NO_MEDICINE: float = -15.0
BONUS_HIGH_OPINION:  float = 5.0
OPINION_BONUS_THRESHOLD: int = 80

FOOD_POP_DIVISOR:     int = 100
AMMO_POP_DIVISOR:     int = 80
MEDICINE_POP_DIVISOR: int = 250


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ArmyInfo:
    army_id:         str
    country_id:      str
    province_id:     str
    state:           str
    strength_pct:    float
    base_province_id: str
    destination:     str | None
    movement_end_day: int | None
    units:           list[dict] = field(default_factory=list)
    total_battle_power: float   = 0.0


@dataclass
class MoveResult:
    ok:           bool
    army_id:      str
    message:      str
    travel_days:  int = 0
    arrival_day:  int = 0


@dataclass
class SupplyResult:
    army_id:       str
    country_id:    str
    army_pop:      int
    food_needed:   int
    ammo_needed:   int
    medicine_needed: int
    food_met:      bool
    ammo_met:      bool
    medicine_met:  bool
    strength_before: float
    strength_after:  float
    penalty_applied: float
    bonus_applied:   float
    message:       str


@dataclass
class MovementCompletionEvent:
    army_id:      str
    country_id:   str
    province_id:  str   # arrived at


# ---------------------------------------------------------------------------
# ArmySystem
# ---------------------------------------------------------------------------

class ArmySystem:
    """
    Manages army creation, composition, movement, and supply consumption.

    Parameters
    ----------
    db : EconomyDB
    """

    def __init__(self, db: EconomyDB) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Create / delete
    # ------------------------------------------------------------------

    def create_army(
        self,
        server_id:       str,
        scenario_id:     str,
        country_id:      str,
        province_id:     str,
        base_province_id: str | None = None,
        current_day:     int = 0,
    ) -> str:
        """
        Create a new empty army in a province.

        Parameters
        ----------
        base_province_id : The home province for retreats. Defaults to province_id.

        Returns
        -------
        str — new army_id (UUID)
        """
        army_id = str(uuid.uuid4())
        base   = base_province_id or province_id
        self._db.insert_army(
            army_id, server_id, scenario_id, country_id,
            province_id, base, last_supply_day=current_day,
        )
        return army_id

    def delete_army(self, army_id: str) -> str:
        self._db.delete_army(army_id)
        return f"Army '{army_id}' deleted."

    # ------------------------------------------------------------------
    # Unit composition
    # ------------------------------------------------------------------

    def add_unit(
        self,
        army_id:     str,
        unit_name:   str,
        quantity:    int,
        server_id:   str,
        scenario_id: str,
    ) -> str:
        """
        Add units to an army.  Stacks if unit_name already exists.

        Returns
        -------
        str — confirmation
        """
        if quantity <= 0:
            return "Quantity must be positive."
        # Validate unit exists
        udef = self._db.get_troop_definition(server_id, scenario_id, unit_name)
        if udef is None:
            return (
                f"Unit '{unit_name}' not found in troop_definitions. "
                "Seed definitions first."
            )
        uid = str(uuid.uuid4())
        self._db.upsert_army_unit(uid, army_id, unit_name, quantity, server_id, scenario_id)
        return f"Added {quantity}× '{unit_name}' to army '{army_id}'."

    def remove_unit(
        self,
        army_id:   str,
        unit_name: str,
        quantity:  int,
    ) -> str:
        units = self._db.get_army_units(army_id)
        existing = next((u for u in units if u["unit_name"] == unit_name), None)
        if existing is None:
            return f"Unit '{unit_name}' not in army '{army_id}'."
        new_qty = existing["quantity"] - quantity
        if new_qty <= 0:
            self._db.remove_army_unit(army_id, unit_name)
        else:
            self._db.set_army_unit_quantity(army_id, unit_name, new_qty)
        return f"Removed {quantity}× '{unit_name}' from army '{army_id}'."

    def get_army_info(
        self,
        army_id:     str,
        server_id:   str,
        scenario_id: str,
    ) -> ArmyInfo | None:
        row = self._db.get_army(army_id)
        if row is None:
            return None
        units = self._db.get_army_units(army_id)
        power = self._compute_battle_power(army_id, server_id, scenario_id, row)
        return ArmyInfo(
            army_id          = army_id,
            country_id       = row["country_id"],
            province_id      = row["province_id"],
            state            = row["state"],
            strength_pct     = float(row["strength_pct"]),
            base_province_id = row["base_province_id"],
            destination      = row.get("destination_province_id"),
            movement_end_day = row.get("movement_end_day"),
            units            = units,
            total_battle_power = power,
        )

    # ------------------------------------------------------------------
    # Movement
    # ------------------------------------------------------------------

    def move_army(
        self,
        army_id:               str,
        destination_province_id: str,
        provinces_to_traverse:  int,
        current_day:           int,
        server_id:             str,
        scenario_id:           str,
    ) -> MoveResult:
        """
        Order an army to move.

        travel_time = ceil(provinces_to_traverse × 7 / speed_modifier)

        Returns
        -------
        MoveResult
        """
        row = self._db.get_army(army_id)
        if row is None:
            return MoveResult(ok=False, army_id=army_id, message="Army not found.")
        if row["state"] in ("in_combat", "destroyed"):
            return MoveResult(
                ok=False, army_id=army_id,
                message=f"Army is {row['state']} — cannot move.",
            )

        speed = self._compute_speed(army_id, server_id, scenario_id)
        base_time = provinces_to_traverse * TRAVEL_DAYS_PER_PROVINCE
        travel_days = max(1, math.ceil(base_time / speed))
        arrival_day = current_day + travel_days

        self._db.update_army_fields(
            army_id,
            state="moving",
            destination_province_id=destination_province_id,
            movement_start_day=current_day,
            movement_end_day=arrival_day,
            provinces_traversed=provinces_to_traverse,
        )
        return MoveResult(
            ok=True,
            army_id=army_id,
            message=(
                f"Army '{army_id}' moving to '{destination_province_id}' "
                f"({travel_days}d, arrives day {arrival_day})."
            ),
            travel_days=travel_days,
            arrival_day=arrival_day,
        )

    def process_movement(
        self,
        server_id:   str,
        scenario_id: str,
        current_day: int,
    ) -> list[MovementCompletionEvent]:
        """
        Check all moving armies; those that have arrived change state to 'idle'.

        Returns a list of completion events for arrived armies.
        """
        events: list[MovementCompletionEvent] = []
        armies = self._db.get_all_armies(server_id, scenario_id)
        for row in armies:
            if row["state"] != "moving":
                continue
            end_day = row.get("movement_end_day")
            if end_day is None or current_day < end_day:
                continue
            dest = row["destination_province_id"]
            self._db.update_army_fields(
                row["army_id"],
                state="idle",
                province_id=dest,
                destination_province_id=None,
                movement_start_day=None,
                movement_end_day=None,
            )
            events.append(MovementCompletionEvent(
                army_id=row["army_id"],
                country_id=row["country_id"],
                province_id=dest,
            ))
        return events

    def retreat_army(
        self,
        army_id:     str,
        server_id:   str,
        scenario_id: str,
        current_day: int,
    ) -> str:
        """
        Immediately retreat army to its base_province.
        State → 'retreating', then immediately placed at base (instant retreat).
        """
        row = self._db.get_army(army_id)
        if row is None:
            return "Army not found."
        base = row["base_province_id"]
        self._db.update_army_fields(
            army_id,
            state="retreating",
            province_id=base,
            destination_province_id=None,
            movement_start_day=None,
            movement_end_day=None,
        )
        return f"Army '{army_id}' retreated to base province '{base}'."

    def destroy_army(self, army_id: str) -> str:
        """Mark army as destroyed (strength → 0, state → destroyed)."""
        self._db.update_army_fields(army_id, state="destroyed", strength_pct=0.0)
        return f"Army '{army_id}' has been destroyed."

    # ------------------------------------------------------------------
    # Supply
    # ------------------------------------------------------------------

    def process_supply(
        self,
        army_id:      str,
        server_id:    str,
        scenario_id:  str,
        current_day:  int,
        war_start_day: int,
    ) -> SupplyResult | None:
        """
        Consume supply for one army.  Call every game day; only fires every
        SUPPLY_INTERVAL_DAYS if war has lasted > MIN_WAR_DAYS_FOR_SUPPLY.

        Returns None if it is not yet time to consume supply.
        """
        row = self._db.get_army(army_id)
        if row is None:
            return None
        if row["state"] == "destroyed":
            return None

        war_duration = current_day - war_start_day
        if war_duration <= MIN_WAR_DAYS_FOR_SUPPLY:
            return None

        last_supply = int(row.get("last_supply_day") or 0)
        if (current_day - last_supply) < SUPPLY_INTERVAL_DAYS:
            return None

        country_id = row["country_id"]

        # Consumption = ceil(country_total_population / 1000) per resource per army
        country_row  = self._db.get_country(server_id, scenario_id, country_id)
        country_pop  = int(country_row.get("total_population") or 0) if country_row else 0
        SUPPLY_DIV   = 1000
        food_need     = max(1, math.ceil(country_pop / SUPPLY_DIV))
        ammo_need     = max(1, math.ceil(country_pop / SUPPLY_DIV))
        medicine_need = max(1, math.ceil(country_pop / SUPPLY_DIV))

        # Consume food: meat first, then grain
        food_met = self._consume_food(server_id, scenario_id, country_id, food_need)
        ammo_met = self._consume_resource(
            server_id, scenario_id, country_id, "ammunition", ammo_need
        )
        medicine_met = self._consume_resource(
            server_id, scenario_id, country_id, "medicines", medicine_need
        )

        # Country opinion for strength bonus
        country_row = self._db.get_country(server_id, scenario_id, country_id)
        opinion = int(country_row.get("population_opinion") or 0) if country_row else 0

        # Compute strength changes
        strength_before = float(row["strength_pct"])
        penalty = 0.0
        if not ammo_met:
            penalty += PENALTY_NO_AMMO
        if not food_met:
            penalty += PENALTY_NO_FOOD
        if not medicine_met:
            penalty += PENALTY_NO_MEDICINE

        bonus = BONUS_HIGH_OPINION if opinion > OPINION_BONUS_THRESHOLD else 0.0

        new_strength = min(
            STRENGTH_MAX,
            max(STRENGTH_MIN, strength_before + penalty + bonus),
        )
        self._db.update_army_fields(
            army_id,
            strength_pct=new_strength,
            last_supply_day=current_day,
        )

        return SupplyResult(
            army_id          = army_id,
            country_id       = country_id,
            army_pop         = country_pop,
            food_needed      = food_need,
            ammo_needed      = ammo_need,
            medicine_needed  = medicine_need,
            food_met         = food_met,
            ammo_met         = ammo_met,
            medicine_met     = medicine_met,
            strength_before  = strength_before,
            strength_after   = new_strength,
            penalty_applied  = penalty,
            bonus_applied    = bonus,
            message          = (
                f"Supply tick for army '{army_id}': "
                f"food={'ok' if food_met else 'SHORTAGE'}, "
                f"ammo={'ok' if ammo_met else 'SHORTAGE'}, "
                f"medicine={'ok' if medicine_met else 'SHORTAGE'}. "
                f"Strength: {strength_before:.1f}% → {new_strength:.1f}%."
            ),
        )

    def process_all_supply(
        self,
        server_id:    str,
        scenario_id:  str,
        current_day:  int,
        war_start_day: int,
    ) -> list[SupplyResult]:
        """Process supply for all non-destroyed armies in the scenario."""
        results = []
        armies = self._db.get_all_armies(server_id, scenario_id)
        for row in armies:
            if row["state"] == "destroyed":
                continue
            result = self.process_supply(
                row["army_id"], server_id, scenario_id,
                current_day, war_start_day,
            )
            if result is not None:
                results.append(result)
        return results

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_armies_in_province(
        self, server_id: str, scenario_id: str, province_id: str
    ) -> list[dict]:
        return self._db.get_armies_in_province(server_id, scenario_id, province_id)

    def get_country_armies(
        self, server_id: str, scenario_id: str, country_id: str
    ) -> list[dict]:
        return self._db.get_country_armies(server_id, scenario_id, country_id)

    def get_army_battle_power(
        self,
        army_id:     str,
        server_id:   str,
        scenario_id: str,
    ) -> float:
        row = self._db.get_army(army_id)
        if row is None:
            return 0.0
        return self._compute_battle_power(army_id, server_id, scenario_id, row)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_speed(
        self, army_id: str, server_id: str, scenario_id: str
    ) -> float:
        """Weighted average speed_modifier across all units."""
        units = self._db.get_army_units(army_id)
        if not units:
            return 1.0
        total_qty   = 0
        total_speed = 0.0
        for u in units:
            udef = self._db.get_troop_definition(server_id, scenario_id, u["unit_name"])
            speed = float(udef["speed_modifier"]) if udef else 1.0
            qty   = int(u["quantity"])
            total_speed += speed * qty
            total_qty   += qty
        return total_speed / total_qty if total_qty else 1.0

    def _compute_battle_power(
        self,
        army_id:     str,
        server_id:   str,
        scenario_id: str,
        army_row:    dict,
    ) -> float:
        """
        Total battle power = sum(quantity × battle_points) × (strength_pct / 100).
        """
        units   = self._db.get_army_units(army_id)
        strength = float(army_row.get("strength_pct", 100.0)) / 100.0
        total   = 0.0
        for u in units:
            udef = self._db.get_troop_definition(server_id, scenario_id, u["unit_name"])
            if udef is None:
                continue
            total += int(u["quantity"]) * int(udef["battle_points"])
        return total * strength

    def _compute_army_pop(
        self,
        army_id:     str,
        server_id:   str,
        scenario_id: str,
        units:       list[dict],
    ) -> int:
        total = 0
        for u in units:
            udef = self._db.get_troop_definition(server_id, scenario_id, u["unit_name"])
            if udef is None:
                continue
            total += int(u["quantity"]) * int(udef["population_required"])
        return total

    def _consume_food(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        amount:      int,
    ) -> bool:
        """Consume food (meat first, then grain). Returns True if fully met."""
        row = self._db.get_or_create_storage(server_id, scenario_id, country_id)
        meat  = int(row.get("meat",  0))
        grain = int(row.get("grain", 0))

        remaining = amount
        meat_used = min(meat, remaining)
        remaining -= meat_used
        grain_used = min(grain, remaining)
        remaining -= grain_used

        updates: dict = {}
        if meat_used:
            updates["meat"]  = meat  - meat_used
        if grain_used:
            updates["grain"] = grain - grain_used

        if updates:
            self._db.update_storage_fields(server_id, scenario_id, country_id, **updates)

        return remaining == 0  # True if fully met

    def _consume_resource(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        resource:    str,
        amount:      int,
    ) -> bool:
        """Consume a storable resource. Returns True if fully met."""
        row     = self._db.get_or_create_storage(server_id, scenario_id, country_id)
        current = int(row.get(resource, 0))
        used    = min(current, amount)
        if used:
            self._db.update_storage_fields(
                server_id, scenario_id, country_id,
                **{resource: current - used},
            )
        return used >= amount
