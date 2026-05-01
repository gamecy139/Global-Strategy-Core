"""
WW1 OCCUPATION SYSTEM
----------------------
Tracks province occupation during wars.

Lifecycle
---------
1. start_occupation()     — army enters enemy province; starts 15-day timer.
2. process_occupations()  — daily tick; marks province as 'fully occupied'
                            after 15 days and awards +2 war score (once).
3. de_occupy()            — defender re-enters an occupied province with no
                            opposing army; starts 15-day de-occupation.
4. cancel_occupation()    — attacker army is destroyed / retreats from province.

Rules
-----
- Occupation only progresses while the occupying army is in the province.
  (Caller must verify army presence before calling process_occupations.)
- War score is awarded exactly once per province per war.
- Multiple wars are supported: each province tracks the latest war_id.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ww1_economy.db        import EconomyDB
from ww1_economy.war_system import WarSystem


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OCCUPATION_TIME_DAYS: int = 15   # days to fully occupy a province


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class OccupationEvent:
    province_id:      str
    occupying_country: str
    event:            str   # "started" | "completed" | "de_occupied" | "cancelled"
    war_score_event:  str | None = None


@dataclass
class OccupationTickResult:
    completed:   list[OccupationEvent] = field(default_factory=list)
    in_progress: list[str]             = field(default_factory=list)


# ---------------------------------------------------------------------------
# OccupationSystem
# ---------------------------------------------------------------------------

class OccupationSystem:
    """
    Manages province occupation state during active wars.

    Parameters
    ----------
    db  : EconomyDB
    war : WarSystem  (used to award war score on full occupation)
    """

    def __init__(self, db: EconomyDB, war: WarSystem) -> None:
        self._db  = db
        self._war = war

    # ------------------------------------------------------------------
    # Start occupation
    # ------------------------------------------------------------------

    def start_occupation(
        self,
        server_id:         str,
        scenario_id:       str,
        province_id:       str,
        war_id:            str,
        occupying_country: str,
        current_day:       int,
    ) -> OccupationEvent:
        """
        Begin occupying a province.  Resets the timer if already being occupied
        by a different country (e.g. after de-occupation).

        Returns
        -------
        OccupationEvent
        """
        self._db.upsert_province_occupation(
            server_id, scenario_id, province_id,
            war_id            = war_id,
            occupying_country = occupying_country,
            occupation_start_day = current_day,
            is_occupied       = 0,
            war_score_awarded = 0,
        )
        return OccupationEvent(
            province_id       = province_id,
            occupying_country = occupying_country,
            event             = "started",
        )

    # ------------------------------------------------------------------
    # Daily tick
    # ------------------------------------------------------------------

    def process_occupations(
        self,
        server_id:   str,
        scenario_id: str,
        war_id:      str,
        current_day: int,
    ) -> OccupationTickResult:
        """
        Advance all in-progress occupations for this war.

        Call once per game day for each active war.  Only occupations that
        have not yet completed (is_occupied=0) are processed.

        Returns
        -------
        OccupationTickResult — newly completed occupations and in-progress list.
        """
        result = OccupationTickResult()
        occ_rows = self._db.get_war_occupations(war_id)

        for row in occ_rows:
            if row.get("is_occupied"):
                continue  # already fully occupied

            province_id  = row["province_id"]
            occupier     = row["occupying_country"]
            start_day    = int(row["occupation_start_day"])
            score_given  = int(row.get("war_score_awarded") or 0)

            if current_day - start_day < OCCUPATION_TIME_DAYS:
                result.in_progress.append(province_id)
                continue

            # Fully occupied
            self._db.update_province_occupation_fields(
                server_id, scenario_id, province_id,
                is_occupied=1,
            )

            ws_event = None
            if not score_given:
                # Award +2 war score (once)
                war = self._db.get_war(war_id)
                if war:
                    beneficiary = (
                        "attacker"
                        if occupier == war["attacker"]
                        else "defender"
                    )
                    self._war.add_war_score(war_id, "province_occupied", beneficiary)
                    self._db.update_province_occupation_fields(
                        server_id, scenario_id, province_id,
                        war_score_awarded=1,
                    )
                    ws_event = f"+{2} war score to {beneficiary}."

            result.completed.append(OccupationEvent(
                province_id       = province_id,
                occupying_country = occupier,
                event             = "completed",
                war_score_event   = ws_event,
            ))

        return result

    # ------------------------------------------------------------------
    # De-occupy
    # ------------------------------------------------------------------

    def de_occupy(
        self,
        server_id:        str,
        scenario_id:      str,
        province_id:      str,
        war_id:           str,
        restoring_country: str,
        current_day:      int,
    ) -> OccupationEvent:
        """
        The original province owner re-enters an occupied province with no
        enemy army present.  Clears the occupation state.

        Returns
        -------
        OccupationEvent
        """
        self._db.delete_province_occupation(server_id, scenario_id, province_id)
        return OccupationEvent(
            province_id       = province_id,
            occupying_country = restoring_country,
            event             = "de_occupied",
        )

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    def cancel_occupation(
        self,
        server_id:   str,
        scenario_id: str,
        province_id: str,
    ) -> OccupationEvent | None:
        """
        Cancel an in-progress occupation (e.g. occupying army destroyed).
        Does nothing if the province is already fully occupied.
        """
        row = self._db.get_province_occupation(server_id, scenario_id, province_id)
        if row is None:
            return None
        if row.get("is_occupied"):
            return None  # fully occupied provinces are not cancelled

        occupier = row["occupying_country"]
        self._db.delete_province_occupation(server_id, scenario_id, province_id)
        return OccupationEvent(
            province_id       = province_id,
            occupying_country = occupier,
            event             = "cancelled",
        )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def is_occupied(
        self,
        server_id:   str,
        scenario_id: str,
        province_id: str,
    ) -> bool:
        """Return True if the province is fully occupied."""
        row = self._db.get_province_occupation(server_id, scenario_id, province_id)
        return bool(row and row.get("is_occupied"))

    def get_occupation(
        self,
        server_id:   str,
        scenario_id: str,
        province_id: str,
    ) -> dict | None:
        return self._db.get_province_occupation(server_id, scenario_id, province_id)

    def get_war_occupations(self, war_id: str) -> list[dict]:
        return self._db.get_war_occupations(war_id)
