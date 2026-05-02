"""
WW1 ECONOMY — ECONOMY EFFICIENCY SYSTEM
----------------------------------------
Computes the per-country economy_efficiency multiplier and applies the
canonical income formula:

    taxed_income = base_income      * tax_multiplier
    final_income = taxed_income     * economy_efficiency

The efficiency value is bounded to ``[0.5, 1.3]`` and is derived from:

  POSITIVE factors
  ─────────────────
  Tax Exemption adopted          → +10%
  Light Contribution adopted     → +5%
  Banking System reform          → +2%
  Central Banking System reform  → +5%
  Opinion > 90                   → +10%
  Opinion > 80                   → +5%
  Opinion > 70                   → +2%

  NEGATIVE factors
  ─────────────────
  Elevated tax policy            → −5%
  War Levy tax policy            → −10%
  Active war (≤ 6 months)        → −20%
  Active war (> 6 months)        → −40%  (replaces the −20% above)
  Civil Rights Framework adopted → −2%
  Each province religion mismatch→ −2%
  Each non-core province         → −2%
  Opinion < 40                   → −5%
  Opinion < 30                   → −10%

All inputs are pulled from the ``countries`` table plus related tables.
This module never reads or writes the legacy ``game_backend`` tables.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ww1_economy.db import EconomyDB


# ---------------------------------------------------------------------------
# Bounds & constants
# ---------------------------------------------------------------------------

EFFICIENCY_MIN:  float = 0.5
EFFICIENCY_MAX:  float = 1.3
EFFICIENCY_BASE: float = 1.0


# ---------------------------------------------------------------------------
# Canonical WW1 tax-tier definitions
# (used by the bot UI and efficiency engine — single source of truth)
# ---------------------------------------------------------------------------

WW1_TAX_TIERS: list[dict] = [
    {
        "key":        "tax_exemption",
        "label":      "Tax Exemption",
        "multiplier": 0.80,
        "opinion":    +10,
        "efficiency": +0.10,
    },
    {
        "key":        "light_contribution",
        "label":      "Light Contribution",
        "multiplier": 0.90,
        "opinion":    +5,
        "efficiency": +0.05,
    },
    {
        "key":        "standard",
        "label":      "Standard",
        "multiplier": 1.00,
        "opinion":    0,
        "efficiency":  0.00,
    },
    {
        "key":        "elevated",
        "label":      "Elevated",
        "multiplier": 1.05,
        "opinion":    -10,
        "efficiency": -0.05,
    },
    {
        "key":        "war_levy",
        "label":      "War Levy",
        "multiplier": 1.15,
        "opinion":    -25,
        "efficiency": -0.10,
    },
]

WW1_TAX_MAP: dict[str, dict] = {t["key"]: t for t in WW1_TAX_TIERS}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class EfficiencyResult:
    """Detailed breakdown of one efficiency calculation."""
    raw:        float
    value:      float
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
    opinion:                      int,
    in_active_war:                bool,
    war_start_month:              int,
    current_month:                int,
    tax_level:                    str,
    adopted_reform_ids:           set[str],
    province_religion_mismatches: int,
    non_core_provinces:           int,
) -> EfficiencyResult:
    """
    Apply every modifier rule and return the bounded result.

    Modifier order
    ──────────────
    POSITIVE:
      - Tax Exemption               → +0.10
      - Light Contribution          → +0.05
      - Banking System adopted      → +0.02
      - Central Banking adopted     → +0.05
      - opinion > 90                → +0.10  (only highest tier fires)
      - else if opinion > 80        → +0.05
      - else if opinion > 70        → +0.02

    NEGATIVE:
      - Elevated tax                → −0.05
      - War Levy tax                → −0.10
      - Active war > 6 months       → −0.40  (replaces the war penalty below)
      - Active war ≤ 6 months       → −0.20
      - Civil Rights Framework      → −0.02
      - Each religion mismatch      → −0.02
      - Each non-core province      → −0.02
      - opinion < 30                → −0.10  (only lowest tier fires)
      - else if opinion < 40        → −0.05

    Final clamp: ``max(0.5, min(1.3, value))``.
    """
    eff: float = EFFICIENCY_BASE
    mods: list[tuple[str, float]] = []

    # ── Tax tier modifiers ────────────────────────────────────────────────────
    if tax_level == "tax_exemption":
        eff += 0.10;  mods.append(("Tax Exemption",       +0.10))
    elif tax_level == "light_contribution":
        eff += 0.05;  mods.append(("Light Contribution",  +0.05))
    elif tax_level == "elevated":
        eff -= 0.05;  mods.append(("Elevated Tax",        -0.05))
    elif tax_level == "war_levy":
        eff -= 0.10;  mods.append(("War Levy",            -0.10))
    # "standard" has no efficiency modifier

    # ── Reform modifiers ──────────────────────────────────────────────────────
    if "banking_system" in adopted_reform_ids:
        eff += 0.02;  mods.append(("Banking System",          +0.02))
    if "central_banking_system" in adopted_reform_ids:
        eff += 0.05;  mods.append(("Central Banking System",  +0.05))
    if "civil_rights_framework" in adopted_reform_ids:
        eff -= 0.02;  mods.append(("Civil Rights Framework",  -0.02))

    # ── War penalty ───────────────────────────────────────────────────────────
    if in_active_war:
        war_months = max(0, current_month - war_start_month)
        if war_months > 6:
            eff -= 0.40;  mods.append(("War >6 months",  -0.40))
        else:
            eff -= 0.20;  mods.append(("Active War",      -0.20))

    # ── Province religion mismatches ──────────────────────────────────────────
    if province_religion_mismatches > 0:
        delta = round(-0.02 * province_religion_mismatches, 6)
        eff  += delta
        mods.append((
            f"{province_religion_mismatches} religion mismatch(es)",
            delta,
        ))

    # ── Non-core provinces ────────────────────────────────────────────────────
    if non_core_provinces > 0:
        delta = round(-0.02 * non_core_provinces, 6)
        eff  += delta
        mods.append((
            f"{non_core_provinces} non-core province(s)",
            delta,
        ))

    # ── Opinion — positive (highest threshold fires) ──────────────────────────
    if opinion > 90:
        eff += 0.10;  mods.append(("Opinion >90", +0.10))
    elif opinion > 80:
        eff += 0.05;  mods.append(("Opinion >80", +0.05))
    elif opinion > 70:
        eff += 0.02;  mods.append(("Opinion >70", +0.02))

    # ── Opinion — negative (lowest threshold fires) ───────────────────────────
    if opinion < 30:
        eff -= 0.10;  mods.append(("Opinion <30", -0.10))
    elif opinion < 40:
        eff -= 0.05;  mods.append(("Opinion <40", -0.05))

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
    Reads inputs from ``ww1_economy.countries`` (and related tables) then
    writes the resulting efficiency value back.  Always isolates by
    ``(server_id, scenario_id)``.
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

        Reads: opinion, in_active_war, war_start_month, tax_level,
               adopted reforms, province religion mismatches,
               non-core province count.
        Writes: economy_efficiency on the countries row.
        """
        row = self._db.get_country(server_id, scenario_id, country_id)
        if row is None:
            raise ValueError(
                f"Country '{country_id}' not found in scenario "
                f"'{scenario_id}' on server '{server_id}'."
            )

        opinion         = int(row.get("population_opinion") or 50)
        in_active_war   = bool(row.get("in_active_war") or 0)
        war_start_month = int(row.get("war_start_month")  or 0)
        tax_level       = str(row.get("tax_level")        or "standard")

        adopted_reforms    = self._db.get_adopted_reforms(server_id, scenario_id, country_id)
        adopted_reform_ids = {r["reform_id"] for r in adopted_reforms}

        religion_mismatches = self._db.count_province_religion_mismatches(
            server_id, scenario_id, country_id
        )
        non_core = self._db.count_non_core_provinces(
            server_id, scenario_id, country_id
        )

        result = compute_efficiency(
            opinion                      = opinion,
            in_active_war                = in_active_war,
            war_start_month              = war_start_month,
            current_month                = current_month,
            tax_level                    = tax_level,
            adopted_reform_ids           = adopted_reform_ids,
            province_religion_mismatches = religion_mismatches,
            non_core_provinces           = non_core,
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
        self, server_id: str, scenario_id: str, country_id: str,
        active: bool, war_start_month: int = 0,
    ) -> None:
        self._db.update_country_fields(
            server_id, scenario_id, country_id,
            in_active_war=int(bool(active)),
            war_start_month=int(war_start_month),
        )

    def set_tax_multiplier(
        self, server_id: str, scenario_id: str, country_id: str, multiplier: float
    ) -> None:
        if multiplier < 0:
            raise ValueError("tax_multiplier must be non-negative.")
        self._db.update_country_fields(
            server_id, scenario_id, country_id, tax_multiplier=float(multiplier)
        )

    def set_tax_level_and_multiplier(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        tax_key:     str,
        multiplier:  float,
    ) -> None:
        """Set both tax_level (key string) and tax_multiplier together."""
        if multiplier < 0:
            raise ValueError("tax_multiplier must be non-negative.")
        self._db.update_country_fields(
            server_id, scenario_id, country_id,
            tax_level=tax_key,
            tax_multiplier=float(multiplier),
        )

    def grant_war_victory_bonus(
        self,
        server_id:    str,
        scenario_id:  str,
        country_id:   str,
        current_month: int,
    ) -> None:
        """Grant the post-war-victory bonus for ONE in-game month."""
        self._db.update_country_fields(
            server_id, scenario_id, country_id,
            war_victory_end_month=int(current_month) + 1,
        )
