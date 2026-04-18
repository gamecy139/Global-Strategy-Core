"""
OPINION SYSTEM
--------------
Manages population_opinion (0–100) for each country.

Opinion represents how much the population supports the current government.
It is affected by:
  • Tax level (applied monthly via TaxationSystem)
  • War declarations (one-time -15 penalty)
  • Future: prosperity, events, propaganda, etc.

Effects of opinion level:
  > 80 → recruitment cost reduced by 30%
  < 30 → contributes +2 unrest per month (checked by UnrestSystem)
"""

from __future__ import annotations

from game_backend.db import Database
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game_backend.taxation_system import TaxationSystem


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OPINION_MIN: int = 0
OPINION_MAX: int = 100

WAR_OPINION_PENALTY:  int   = -15   # Applied once when a war is declared

# Effect thresholds
HIGH_OPINION_THRESHOLD:     int   = 80
LOW_OPINION_THRESHOLD:      int   = 30
HIGH_OPINION_RECRUIT_BONUS: float = 0.30   # 30% cost reduction
LOW_OPINION_UNREST_DELTA:   int   = 2      # +2 unrest/month contributed


class OpinionSystem:
    """
    Handles population_opinion for all countries on all servers.

    Parameters
    ----------
    db : Database
        Shared database instance.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_opinion(self, server_id: str, country_id: str) -> int:
        row = self._db.get_or_create_country(server_id, country_id)
        return int(row.get("population_opinion", 50))

    def get_snapshot(self, server_id: str, country_id: str) -> dict:
        opinion = self.get_opinion(server_id, country_id)
        return {
            "server_id":                  server_id,
            "country_id":                 country_id,
            "population_opinion":         opinion,
            "recruitment_cost_modifier":  self.get_recruitment_cost_modifier(server_id, country_id),
            "contributes_to_unrest":      self.contributes_to_unrest(server_id, country_id),
        }

    # ------------------------------------------------------------------
    # Effects
    # ------------------------------------------------------------------

    def get_recruitment_cost_modifier(self, server_id: str, country_id: str) -> float:
        """
        Return the recruitment cost multiplier based on opinion.

        > 80 → 0.70 (30% discount)
        ≤ 80 → 1.00 (no discount)
        """
        if self.get_opinion(server_id, country_id) > HIGH_OPINION_THRESHOLD:
            return 1.0 - HIGH_OPINION_RECRUIT_BONUS
        return 1.0

    def contributes_to_unrest(self, server_id: str, country_id: str) -> bool:
        """True if opinion is low enough to add to monthly unrest."""
        return self.get_opinion(server_id, country_id) < LOW_OPINION_THRESHOLD

    def get_unrest_contribution(self, server_id: str, country_id: str) -> int:
        """Return the monthly unrest contributed by low opinion (0 or +2)."""
        return LOW_OPINION_UNREST_DELTA if self.contributes_to_unrest(server_id, country_id) else 0

    def get_unrest_reduction(self, server_id: str, country_id: str) -> int:
        """
        Return the monthly unrest reduction driven by opinion.

        > 70 → -3 per month
        > 50 → -2 per month
        ≤ 50 → 0
        """
        opinion = self.get_opinion(server_id, country_id)
        if opinion > 70:
            return 3
        if opinion > 50:
            return 2
        return 0

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def set_opinion(self, server_id: str, country_id: str, value: int) -> int:
        """Directly set opinion (admin / event use). Clamped to [0, 100]."""
        clamped = max(OPINION_MIN, min(OPINION_MAX, value))
        self._db.get_or_create_country(server_id, country_id)
        self._db.update_fields(server_id, country_id, population_opinion=clamped)
        return clamped

    def adjust_opinion(self, server_id: str, country_id: str, delta: int) -> int:
        """Apply a signed delta to opinion. Returns the new value."""
        current = self.get_opinion(server_id, country_id)
        return self.set_opinion(server_id, country_id, current + delta)

    def apply_war_penalty(self, server_id: str, country_id: str) -> int:
        """
        Apply the one-time war declaration penalty (-15 opinion).
        Call this once when war is declared.
        Returns the new opinion.
        """
        return self.adjust_opinion(server_id, country_id, WAR_OPINION_PENALTY)

    # ------------------------------------------------------------------
    # Monthly update
    # ------------------------------------------------------------------

    def update_monthly(
        self,
        server_id:   str,
        country_id:  str,
        tax_system:  "TaxationSystem",
    ) -> dict:
        """
        Apply all monthly opinion modifiers.

        Currently applies:
          • Tax level modifier (from TaxationSystem)

        Returns a dict describing what changed.
        """
        tax_modifier = tax_system.get_monthly_opinion_modifier(server_id, country_id)
        old_opinion  = self.get_opinion(server_id, country_id)
        new_opinion  = self.adjust_opinion(server_id, country_id, tax_modifier)

        return {
            "server_id":     server_id,
            "country_id":    country_id,
            "old_opinion":   old_opinion,
            "tax_modifier":  tax_modifier,
            "new_opinion":   new_opinion,
        }
