"""
WW1 ECONOMY — ECONOMY EFFICIENCY SYSTEM
----------------------------------------
Computes the per-country economy_efficiency multiplier and applies the
canonical income formula:

    taxed_income = base_income      * tax_multiplier
    final_income = taxed_income     * economy_efficiency

The efficiency value is bounded to ``[0.5, 1.3]`` and is derived from the
country's current opinion, unrest, war state, and any temporary post-war
victory bonus.  All inputs are pulled from the ``countries`` table — this
module is a pure mathematics layer plus a thin DB write to cache the result.

This module never reads or writes the legacy ``game_backend`` tables; it
operates exclusively against ``ww1_economy.countries`` so every value stays
strictly partitioned by ``(server_id, scenario_id)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ww1_economy.db import EconomyDB


# ---------------------------------------------------------------------------
# Bounds & constants
# ---------------------------------------------------------------------------

EFFICIENCY_MIN: float = 0.5
EFFICIENCY_MAX: float = 1.3
EFFICIENCY_BASE: float = 1.0


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class EfficiencyResult:
    """Detailed breakdown of one efficiency calculation."""
    raw:        float                       # before clamp
    value:      float                       # after clamp (the final multiplier)
    modifiers:  list[tuple[str, float]] = field(default_factory=list)
    clamped:    bool                    = False

    def to_dict(self) -> dict:
        return {
            "raw":       round(self.raw,   4),
            "value":     round(self.value, 4),
            "modifiers": [{"reason": r, "delta": round(d, 4)} for r, d in self.modifiers],
            "clamped":   self.clamped,
        }


# ---------------------------------------------------------------------------
# Pure efficiency computation
# ---------------------------------------------------------------------------

def compute_efficiency(
    opinion:                  int,
    unrest:                   float,
    in_active_war:            bool,
    war_victory_bonus_active: bool,
) -> EfficiencyResult:
    """
    Apply every modifier rule from the spec and return the bounded result.

    Modifier order (matches the spec exactly — only the highest-priority
    branch in each ``if/elif`` chain ever fires):

    POSITIVE:
      - opinion > 80                 → +0.15
      - else if opinion > 70         → +0.10
      - unrest == 0                  → +0.15
      - else if unrest < 10          → +0.10
      - else if unrest < 20          → +0.05
      - war_victory_bonus_active     → +0.02

    NEGATIVE:
      - opinion < 20                 → -0.25
      - else if opinion < 40         → -0.10
      - unrest > 80                  → -0.50
      - else if unrest > 50          → -0.25
      - else if unrest > 30          → -0.10
      - in_active_war                → -0.20

    Final clamp: ``max(0.5, min(1.3, value))``.
    """
    eff: float = EFFICIENCY_BASE
    mods: list[tuple[str, float]] = []

    # ---- positive opinion -----------------------------------------------
    if opinion > 80:
        eff += 0.15;  mods.append(("opinion>80",   +0.15))
    elif opinion > 70:
        eff += 0.10;  mods.append(("opinion>70",   +0.10))

    # ---- positive unrest ------------------------------------------------
    if unrest == 0:
        eff += 0.15;  mods.append(("unrest==0",    +0.15))
    elif unrest < 10:
        eff += 0.10;  mods.append(("unrest<10",    +0.10))
    elif unrest < 20:
        eff += 0.05;  mods.append(("unrest<20",    +0.05))

    # ---- war victory bonus (lasts 1 month after a victory) --------------
    if war_victory_bonus_active:
        eff += 0.02;  mods.append(("war_victory",  +0.02))

    # ---- negative opinion -----------------------------------------------
    if opinion < 20:
        eff -= 0.25;  mods.append(("opinion<20",   -0.25))
    elif opinion < 40:
        eff -= 0.10;  mods.append(("opinion<40",   -0.10))

    # ---- negative unrest ------------------------------------------------
    if unrest > 80:
        eff -= 0.50;  mods.append(("unrest>80",    -0.50))
    elif unrest > 50:
        eff -= 0.25;  mods.append(("unrest>50",    -0.25))
    elif unrest > 30:
        eff -= 0.10;  mods.append(("unrest>30",    -0.10))

    # ---- in active war --------------------------------------------------
    if in_active_war:
        eff -= 0.20;  mods.append(("in_active_war", -0.20))

    raw     = eff
    clamped = max(EFFICIENCY_MIN, min(EFFICIENCY_MAX, eff))
    return EfficiencyResult(
        raw       = raw,
        value     = clamped,
        modifiers = mods,
        clamped   = (clamped != raw),
    )


def apply_income_formula(
    base_income:        float,
    tax_multiplier:     float,
    economy_efficiency: float,
) -> dict:
    """
    Canonical income formula — taxation MUST be applied before efficiency.

        taxed_income = base_income  * tax_multiplier
        final_income = taxed_income * economy_efficiency
    """
    if base_income < 0:
        raise ValueError("base_income must be non-negative.")
    if tax_multiplier < 0:
        raise ValueError("tax_multiplier must be non-negative.")
    if economy_efficiency < 0:
        raise ValueError("economy_efficiency must be non-negative.")

    taxed = base_income * tax_multiplier
    final = taxed * economy_efficiency
    return {
        "base_income":        round(base_income,        6),
        "tax_multiplier":     round(tax_multiplier,     6),
        "taxed_income":       round(taxed,              6),
        "economy_efficiency": round(economy_efficiency, 6),
        "final_income":       round(final,              6),
    }


# ---------------------------------------------------------------------------
# DB-backed system
# ---------------------------------------------------------------------------

class EconomyEfficiencySystem:
    """
    Reads inputs from ``ww1_economy.countries`` and writes the resulting
    efficiency value back to that same row.  Always isolates by
    ``(server_id, scenario_id)``.

    Parameters
    ----------
    db : EconomyDB
        Shared database instance (must be initialised via ``db.init()``).
    """

    def __init__(self, db: EconomyDB) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Compute + persist
    # ------------------------------------------------------------------

    def recompute(
        self,
        server_id:     str,
        scenario_id:   str,
        country_id:    str,
        current_month: int,
    ) -> EfficiencyResult:
        """
        Recompute economy efficiency for one country and persist it.

        ``war_victory_end_month`` is interpreted as "the bonus is active for
        every month strictly less than this value", so a victory in month N
        sets it to ``N + 1`` and the bonus only fires once.
        """
        row = self._db.get_country(server_id, scenario_id, country_id)
        if row is None:
            raise ValueError(
                f"Country '{country_id}' not found in scenario "
                f"'{scenario_id}' on server '{server_id}'."
            )

        opinion       = int(row.get("population_opinion") or 0)
        unrest        = float(row.get("unrest") or 0.0)
        in_active_war = bool(row.get("in_active_war") or 0)
        win_until     = int(row.get("war_victory_end_month") or 0)

        result = compute_efficiency(
            opinion                  = opinion,
            unrest                   = unrest,
            in_active_war            = in_active_war,
            war_victory_bonus_active = current_month < win_until,
        )

        self._db.update_country_fields(
            server_id, scenario_id, country_id,
            economy_efficiency=result.value,
        )
        return result

    def recompute_all(
        self,
        server_id:     str,
        scenario_id:   str,
        current_month: int,
    ) -> dict[str, EfficiencyResult]:
        """Recompute efficiency for every country in the scenario."""
        out: dict[str, EfficiencyResult] = {}
        for c in self._db.get_all_countries(server_id, scenario_id):
            cid = c["country_id"]
            out[cid] = self.recompute(server_id, scenario_id, cid, current_month)
        return out

    # ------------------------------------------------------------------
    # Income calculation (taxation BEFORE efficiency)
    # ------------------------------------------------------------------

    def calculate_final_daily_income(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> dict:
        """
        Apply the income formula using the country's currently cached
        ``daily_base_income``, ``tax_multiplier`` and ``economy_efficiency``.

        Returns a dict with each stage of the calculation visible.
        """
        row = self._db.get_country(server_id, scenario_id, country_id)
        if row is None:
            raise ValueError(
                f"Country '{country_id}' not found in scenario "
                f"'{scenario_id}' on server '{server_id}'."
            )
        base = float(row.get("daily_base_income") or 0.0)
        tax  = float(row.get("tax_multiplier")    or 1.0)
        eff  = float(row.get("economy_efficiency") or 1.0)
        return apply_income_formula(base, tax, eff)

    # ------------------------------------------------------------------
    # Setters for the inputs that drive efficiency
    # ------------------------------------------------------------------

    def set_opinion(
        self, server_id: str, scenario_id: str, country_id: str, opinion: int
    ) -> None:
        opinion = max(0, min(100, int(opinion)))
        self._db.update_country_fields(
            server_id, scenario_id, country_id, population_opinion=opinion
        )

    def set_unrest(
        self, server_id: str, scenario_id: str, country_id: str, unrest: float
    ) -> None:
        unrest = max(0.0, min(100.0, float(unrest)))
        self._db.update_country_fields(
            server_id, scenario_id, country_id, unrest=unrest
        )

    def set_in_active_war(
        self, server_id: str, scenario_id: str, country_id: str, active: bool
    ) -> None:
        self._db.update_country_fields(
            server_id, scenario_id, country_id, in_active_war=int(bool(active))
        )

    def set_tax_multiplier(
        self, server_id: str, scenario_id: str, country_id: str, multiplier: float
    ) -> None:
        if multiplier < 0:
            raise ValueError("tax_multiplier must be non-negative.")
        self._db.update_country_fields(
            server_id, scenario_id, country_id, tax_multiplier=float(multiplier)
        )

    def grant_war_victory_bonus(
        self,
        server_id:    str,
        scenario_id:  str,
        country_id:   str,
        current_month: int,
    ) -> None:
        """Grant the ``+0.02`` post-war-victory bonus for ONE in-game month."""
        self._db.update_country_fields(
            server_id, scenario_id, country_id,
            war_victory_end_month=int(current_month) + 1,
        )
