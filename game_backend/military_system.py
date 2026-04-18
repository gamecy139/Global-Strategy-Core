"""
MILITARY SYSTEM + RECRUITMENT SYSTEM
-------------------------------------
Manages army units and recruitment for all countries.

Army units
----------
Each unit has:
  unit_id         — UUID
  country_id      — owning country
  type            — infantry | cavalry | ranged | support | maritime
  size            — head count
  location        — current province / region name
  status          — idle | moving | combat
  target_location — destination province (while moving)
  arrival_day     — absolute in-game day when the unit arrives

Features:
  • create_unit  — spawn a new unit
  • merge_units  — combine two units of the same type and country
  • split_unit   — divide a unit into two
  • move_unit    — dispatch a unit toward a new location
  • process_movements — resolve arrivals for the current day
  • disband_unit — remove a unit and return its size to country tracking

Recruitment system (RecruitmentSystem)
---------------------------------------
Rules:
  Base max recruitable = 30% of base_population
  During war          = 40%
  Minimum             = 5%
  Formula:
    allowed_percent = max(5%, base% × (current_pop / base_pop))

Mass recruitment penalty:
  Triggered when >30% of base_population recruited within 2 recruitments
  or a rolling 90-day window.
  Effect:  recruitment cost ×3
  Duration: 720 in-game days (2 in-game years)

Recruitment effects:
  • current_population reduced by recruited amount
  • total_army_size increased
  • New army unit created
"""

from __future__ import annotations

import uuid
from typing import Optional

from game_backend.db import Database

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_UNIT_TYPES: frozenset[str] = frozenset({
    "infantry", "cavalry", "ranged", "support", "maritime"
})

VALID_UNIT_STATUSES: frozenset[str] = frozenset({"idle", "moving", "combat"})

# Recruitment percentage limits
BASE_RECRUIT_PERCENT:    float = 0.30   # 30%
WAR_RECRUIT_PERCENT:     float = 0.40   # 40%
MIN_RECRUIT_PERCENT:     float = 0.05   # 5%

# Mass recruitment penalty
MASS_RECRUIT_THRESHOLD:  float = 0.30   # >30% of base_pop
MASS_RECRUIT_MAX_COUNT:  int   = 2      # within this many recruitments
MASS_RECRUIT_WINDOW:     int   = 90     # or within 90 days
PENALTY_COST_MULTIPLIER: float = 3.0
PENALTY_DURATION_DAYS:   int   = 720    # 2 in-game years


# ---------------------------------------------------------------------------
# MilitarySystem
# ---------------------------------------------------------------------------

class MilitarySystem:
    """
    Manages army units for all countries on all servers.

    Parameters
    ----------
    db : Database
        Shared database instance.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Unit creation / deletion
    # ------------------------------------------------------------------

    def create_unit(
        self,
        server_id:  str,
        country_id: str,
        unit_type:  str,
        size:       int,
        location:   str,
    ) -> str:
        """
        Spawn a new army unit and return its unit_id.
        Does NOT deduct population — use RecruitmentSystem.recruit() for that.
        """
        if unit_type not in VALID_UNIT_TYPES:
            raise ValueError(
                f"Invalid unit type '{unit_type}'. "
                f"Valid types: {sorted(VALID_UNIT_TYPES)}"
            )
        if size <= 0:
            raise ValueError("Unit size must be positive.")

        unit_id = str(uuid.uuid4())
        self._db.upsert_army_unit(
            server_id  = server_id,
            unit_id    = unit_id,
            country_id = country_id,
            unit_type  = unit_type,
            size       = size,
            location   = location,
            status     = "idle",
        )
        self._refresh_army_size(server_id, country_id)
        return unit_id

    def disband_unit(self, server_id: str, unit_id: str) -> int:
        """
        Disband (delete) a unit.  Returns the disbanded size.
        The caller is responsible for deciding what happens to the manpower.
        """
        unit = self._require_unit(server_id, unit_id)
        self._db.delete_army_unit(server_id, unit_id)
        self._refresh_army_size(server_id, unit["country_id"])
        return int(unit["size"])

    # ------------------------------------------------------------------
    # Merge & split
    # ------------------------------------------------------------------

    def merge_units(
        self,
        server_id:  str,
        unit_id_a:  str,
        unit_id_b:  str,
    ) -> str:
        """
        Merge two units into one (same country, same type required).
        The first unit absorbs the second.  Returns the surviving unit_id.
        """
        a = self._require_unit(server_id, unit_id_a)
        b = self._require_unit(server_id, unit_id_b)

        if a["country_id"] != b["country_id"]:
            raise ValueError("Cannot merge units from different countries.")
        if a["type"] != b["type"]:
            raise ValueError(
                f"Cannot merge units of different types "
                f"('{a['type']}' vs '{b['type']}')."
            )

        new_size = int(a["size"]) + int(b["size"])
        self._db.update_army_unit_fields(server_id, unit_id_a, size=new_size)
        self._db.delete_army_unit(server_id, unit_id_b)
        self._refresh_army_size(server_id, a["country_id"])
        return unit_id_a

    def split_unit(
        self,
        server_id:   str,
        unit_id:     str,
        split_size:  int,
    ) -> tuple[str, str]:
        """
        Split a unit into two.  The original unit keeps (size - split_size),
        a new unit is created with split_size.

        Returns (original_unit_id, new_unit_id).
        """
        unit = self._require_unit(server_id, unit_id)
        total_size = int(unit["size"])

        if split_size <= 0 or split_size >= total_size:
            raise ValueError(
                f"split_size must be between 1 and {total_size - 1}."
            )

        remaining = total_size - split_size
        self._db.update_army_unit_fields(server_id, unit_id, size=remaining)

        new_unit_id = str(uuid.uuid4())
        self._db.upsert_army_unit(
            server_id  = server_id,
            unit_id    = new_unit_id,
            country_id = unit["country_id"],
            unit_type  = unit["type"],
            size       = split_size,
            location   = unit["location"],
            status     = "idle",
        )
        # Total army size stays the same after a split
        return unit_id, new_unit_id

    # ------------------------------------------------------------------
    # Movement
    # ------------------------------------------------------------------

    def move_unit(
        self,
        server_id:       str,
        unit_id:         str,
        target_location: str,
        arrival_day:     int,
    ) -> None:
        """
        Dispatch a unit toward ``target_location``.
        Status is set to 'moving'; it becomes 'idle' on arrival.
        """
        self._require_unit(server_id, unit_id)
        self._db.update_army_unit_fields(
            server_id, unit_id,
            status          = "moving",
            target_location = target_location,
            arrival_day     = arrival_day,
        )

    def process_movements(
        self,
        server_id:   str,
        current_day: int,
    ) -> list[dict]:
        """
        Resolve all units that have reached their destination.
        Call this every tick (or every day).

        Returns a list of arrival event dicts.
        """
        arrivals: list[dict] = []

        for unit in self._db.get_moving_units(server_id):
            if int(unit.get("arrival_day", 0)) <= current_day:
                destination = unit.get("target_location", unit["location"])
                self._db.update_army_unit_fields(
                    server_id, unit["unit_id"],
                    location        = destination,
                    target_location = None,
                    arrival_day     = 0,
                    status          = "idle",
                )
                arrivals.append({
                    "unit_id":    unit["unit_id"],
                    "country_id": unit["country_id"],
                    "arrived_at": destination,
                })

        return arrivals

    # ------------------------------------------------------------------
    # Status management
    # ------------------------------------------------------------------

    def set_unit_status(
        self,
        server_id: str,
        unit_id:   str,
        status:    str,
    ) -> None:
        if status not in VALID_UNIT_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Valid: {sorted(VALID_UNIT_STATUSES)}"
            )
        self._require_unit(server_id, unit_id)
        self._db.update_army_unit_fields(server_id, unit_id, status=status)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_unit(self, server_id: str, unit_id: str) -> dict | None:
        return self._db.get_army_unit(server_id, unit_id)

    def get_country_units(
        self, server_id: str, country_id: str
    ) -> list[dict]:
        return self._db.get_army_units_by_country(server_id, country_id)

    def get_total_army_size(self, server_id: str, country_id: str) -> int:
        row = self._db.get_country(server_id, country_id)
        if row is None:
            return 0
        return int(row.get("total_army_size", 0))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_unit(self, server_id: str, unit_id: str) -> dict:
        unit = self._db.get_army_unit(server_id, unit_id)
        if unit is None:
            raise KeyError(f"No unit with id '{unit_id}' on server '{server_id}'.")
        return unit

    def _refresh_army_size(self, server_id: str, country_id: str) -> int:
        """Recalculate total_army_size from all units for this country."""
        units    = self._db.get_army_units_by_country(server_id, country_id)
        total    = sum(int(u["size"]) for u in units)
        row = self._db.get_country(server_id, country_id)
        if row is not None:
            self._db.update_fields(server_id, country_id, total_army_size=total)
        return total


# ---------------------------------------------------------------------------
# RecruitmentSystem
# ---------------------------------------------------------------------------

class RecruitmentSystem:
    """
    Handles recruitment logic, percentage caps, and mass-recruitment penalties.

    Parameters
    ----------
    db       : Database         — shared database instance.
    military : MilitarySystem   — used to create units and refresh army size.
    """

    def __init__(self, db: Database, military: MilitarySystem) -> None:
        self._db       = db
        self._military = military

    # ------------------------------------------------------------------
    # Percentage calculations
    # ------------------------------------------------------------------

    def get_allowed_percentage(
        self,
        server_id:  str,
        country_id: str,
        at_war:     bool = False,
    ) -> float:
        """
        Calculate the maximum fraction of base_population that may be recruited.

        Formula:
          base% = 40% if at war, else 30%
          allowed% = max(5%, base% × (current_pop / base_pop))
        """
        row          = self._db.get_or_create_country(server_id, country_id)
        base_pop     = int(row.get("base_population") or row.get("population", 1_000_000))
        current_pop  = int(row.get("current_population") or row.get("population", 1_000_000))
        base_percent = WAR_RECRUIT_PERCENT if at_war else BASE_RECRUIT_PERCENT

        if base_pop == 0:
            return MIN_RECRUIT_PERCENT

        allowed = max(MIN_RECRUIT_PERCENT, base_percent * (current_pop / base_pop))
        return round(allowed, 4)

    def calculate_max_recruitable(
        self,
        server_id:  str,
        country_id: str,
        at_war:     bool = False,
    ) -> int:
        """Return the absolute maximum number of recruits allowed right now."""
        row      = self._db.get_or_create_country(server_id, country_id)
        base_pop = int(row.get("base_population") or row.get("population", 1_000_000))
        pct      = self.get_allowed_percentage(server_id, country_id, at_war)
        return int(base_pop * pct)

    # ------------------------------------------------------------------
    # Cost calculation
    # ------------------------------------------------------------------

    def get_recruitment_cost(
        self,
        server_id:           str,
        country_id:          str,
        amount:              int,
        base_cost_per_unit:  float = 1.0,
        current_day:         int   = 0,
        opinion_system       = None,   # OpinionSystem — optional
    ) -> float:
        """
        Calculate the total gold cost to recruit ``amount`` soldiers.

        Modifiers applied (multiplicative):
          • Mass recruitment penalty → ×3
          • High opinion (>80) → ×0.70 (30% discount)
        """
        self.check_and_expire_penalty(server_id, country_id, current_day)
        tracking = self._db.get_recruitment_tracking(server_id, country_id)

        cost = base_cost_per_unit * amount

        # Mass penalty
        if tracking.get("penalty_active"):
            cost *= PENALTY_COST_MULTIPLIER

        # Opinion discount
        if opinion_system is not None:
            modifier = opinion_system.get_recruitment_cost_modifier(server_id, country_id)
            cost *= modifier

        return round(cost, 2)

    # ------------------------------------------------------------------
    # Recruitment action
    # ------------------------------------------------------------------

    def recruit(
        self,
        server_id:          str,
        country_id:         str,
        amount:             int,
        unit_type:          str,
        location:           str,
        current_day:        int,
        at_war:             bool  = False,
        base_cost_per_unit: float = 1.0,
        opinion_system      = None,
    ) -> dict:
        """
        Recruit ``amount`` soldiers into a new army unit.

        Steps:
          1. Validate amount ≤ current_population and ≤ max_recruitable.
          2. Calculate cost (including penalties and opinion modifiers).
          3. Deduct population, create army unit.
          4. Update mass-recruitment tracking.

        Returns a result dict:
          unit_id           : str   — the new unit
          recruited_amount  : int
          cost              : float — caller must deduct from treasury
          new_population    : int
          penalty_triggered : bool  — True if this recruitment triggered the penalty
          allowed           : bool
          reason            : str
        """
        self.check_and_expire_penalty(server_id, country_id, current_day)

        row          = self._db.get_or_create_country(server_id, country_id)
        current_pop  = int(row.get("current_population") or row.get("population", 1_000_000))
        max_recruitble = self.calculate_max_recruitable(server_id, country_id, at_war)
        existing_army  = int(row.get("total_army_size", 0))

        # Validate amount
        if amount <= 0:
            return {"allowed": False, "reason": "Amount must be positive."}
        if amount > current_pop:
            return {
                "allowed": False,
                "reason": f"Not enough population. Have {current_pop:,}, need {amount:,}.",
            }
        if existing_army + amount > max_recruitble:
            remaining = max(0, max_recruitble - existing_army)
            return {
                "allowed": False,
                "reason": (
                    f"Recruitment cap exceeded. "
                    f"Max recruitble now: {remaining:,} "
                    f"({self.get_allowed_percentage(server_id, country_id, at_war)*100:.1f}% cap)."
                ),
            }

        # Cost
        cost = self.get_recruitment_cost(
            server_id, country_id, amount,
            base_cost_per_unit, current_day, opinion_system
        )

        # Deduct population
        new_pop = max(1, current_pop - amount)
        self._db.update_fields(
            server_id, country_id,
            current_population = new_pop,
            population         = new_pop,
        )

        # Create unit
        unit_id = self._military.create_unit(
            server_id  = server_id,
            country_id = country_id,
            unit_type  = unit_type,
            size       = amount,
            location   = location,
        )

        # Update mass-recruitment tracking
        penalty_triggered = self._update_tracking(
            server_id, country_id, amount, current_day, row
        )

        return {
            "allowed":           True,
            "reason":            "Recruitment successful.",
            "unit_id":           unit_id,
            "recruited_amount":  amount,
            "cost":              cost,
            "new_population":    new_pop,
            "penalty_triggered": penalty_triggered,
        }

    # ------------------------------------------------------------------
    # Mass recruitment penalty management
    # ------------------------------------------------------------------

    def check_and_expire_penalty(
        self,
        server_id:   str,
        country_id:  str,
        current_day: int,
    ) -> bool:
        """
        Check if the active penalty has expired and clear it if so.
        Returns True if a penalty is (still) active after the check.
        """
        tracking = self._db.get_recruitment_tracking(server_id, country_id)
        if not tracking.get("penalty_active"):
            return False
        if current_day >= int(tracking.get("penalty_end_time", 0)):
            self._db.update_recruitment_tracking(
                server_id, country_id,
                recent_recruitment_amount = 0,
                recent_recruitment_count  = 0,
                recruitment_window_start  = 0,
                penalty_active            = False,
                penalty_end_time          = 0,
            )
            return False
        return True

    def get_tracking(self, server_id: str, country_id: str) -> dict:
        return self._db.get_recruitment_tracking(server_id, country_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_tracking(
        self,
        server_id:   str,
        country_id:  str,
        amount:      int,
        current_day: int,
        country_row: dict,
    ) -> bool:
        """
        Update rolling recruitment tracking and trigger penalty if warranted.
        Returns True if the penalty was just triggered.
        """
        base_pop  = int(country_row.get("base_population") or
                        country_row.get("population", 1_000_000))
        tracking  = self._db.get_recruitment_tracking(server_id, country_id)

        window_start = int(tracking.get("recruitment_window_start", 0))
        in_window    = (current_day - window_start) <= MASS_RECRUIT_WINDOW

        if in_window and window_start > 0:
            new_amount = int(tracking.get("recent_recruitment_amount", 0)) + amount
            new_count  = int(tracking.get("recent_recruitment_count", 0)) + 1
        else:
            # New window
            new_amount = amount
            new_count  = 1
            window_start = current_day

        penalty_triggered = False
        penalty_active    = bool(tracking.get("penalty_active"))
        penalty_end_time  = int(tracking.get("penalty_end_time", 0))

        if (not penalty_active and
                new_count >= MASS_RECRUIT_MAX_COUNT and
                new_amount > base_pop * MASS_RECRUIT_THRESHOLD):
            penalty_triggered = True
            penalty_active    = True
            penalty_end_time  = current_day + PENALTY_DURATION_DAYS

        self._db.update_recruitment_tracking(
            server_id, country_id,
            recent_recruitment_amount = new_amount,
            recent_recruitment_count  = new_count,
            recruitment_window_start  = window_start,
            penalty_active            = penalty_active,
            penalty_end_time          = penalty_end_time,
        )
        return penalty_triggered
