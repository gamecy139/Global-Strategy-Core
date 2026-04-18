"""
TAXATION SYSTEM
---------------
Defines tax levels for each country and their effects on income and
population opinion.

Tax levels (canonical names):
  Tax Exemption        — very low income, positive opinion
  Light Contribution   — reduced income, slight positive opinion
  Standard Contribution — normal income, neutral opinion
  Elevated Contribution — increased income, negative opinion
  War Levy             — maximum income, significant opinion penalty

Income multipliers scale the country's base daily_income.
Opinion modifiers are applied once per in-game month by the opinion system.
"""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass

from game_backend.db import Database


# ---------------------------------------------------------------------------
# Tax level definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TaxLevelConfig:
    """Configuration for one tax level."""
    name:              str
    income_multiplier: float  # Applied to base daily_income
    opinion_modifier:  int    # Applied to population_opinion per month


class TaxLevel(Enum):
    """
    All recognised tax levels in canonical name order (lightest → heaviest).

    Each member carries a TaxLevelConfig with income and opinion effects.
    The string value matches the canonical name stored in the database.
    """
    TAX_EXEMPTION        = TaxLevelConfig("Tax Exemption",         0.50,  +2)
    LIGHT_CONTRIBUTION   = TaxLevelConfig("Light Contribution",    0.75,  +1)
    STANDARD_CONTRIBUTION = TaxLevelConfig("Standard Contribution", 1.00,   0)
    ELEVATED_CONTRIBUTION = TaxLevelConfig("Elevated Contribution", 1.50,  -2)
    WAR_LEVY             = TaxLevelConfig("War Levy",               2.00,  -4)

    @property
    def config(self) -> TaxLevelConfig:
        return self.value

    @property
    def label(self) -> str:
        return self.value.name

    @property
    def income_multiplier(self) -> float:
        return self.value.income_multiplier

    @property
    def opinion_modifier(self) -> int:
        return self.value.opinion_modifier

    @classmethod
    def from_label(cls, label: str) -> "TaxLevel":
        """
        Look up a TaxLevel by its human-readable label (e.g. 'War Levy').
        Raises ValueError for unrecognised labels.
        """
        for member in cls:
            if member.label == label:
                return member
        valid = ", ".join(f"'{m.label}'" for m in cls)
        raise ValueError(f"Unknown tax level '{label}'. Valid options: {valid}")

    @classmethod
    def labels(cls) -> list[str]:
        """Return all canonical label strings."""
        return [m.label for m in cls]


# Income multiplier lookup (label → multiplier) for quick access
INCOME_MULTIPLIERS: dict[str, float] = {
    m.label: m.income_multiplier for m in TaxLevel
}

# Monthly opinion modifier lookup (label → modifier)
OPINION_MODIFIERS: dict[str, int] = {
    m.label: m.opinion_modifier for m in TaxLevel
}


# ---------------------------------------------------------------------------
# TaxationSystem
# ---------------------------------------------------------------------------

class TaxationSystem:
    """
    Manages tax level reads and writes for all countries on all servers.

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

    def get_tax_level(self, server_id: str, country_id: str) -> TaxLevel:
        """Return the current TaxLevel for a country."""
        row   = self._db.get_or_create_country(server_id, country_id)
        label = str(row.get("tax_level", "Standard Contribution"))
        return TaxLevel.from_label(label)

    def get_tax_label(self, server_id: str, country_id: str) -> str:
        """Return the tax level as a plain string label."""
        return self.get_tax_level(server_id, country_id).label

    def get_income_multiplier(self, server_id: str, country_id: str) -> float:
        """Return the income multiplier for the current tax level."""
        return self.get_tax_level(server_id, country_id).income_multiplier

    def get_monthly_opinion_modifier(self, server_id: str, country_id: str) -> int:
        """
        Return the monthly opinion change caused by the current tax level.
        Positive → improves opinion, negative → damages opinion.
        """
        return self.get_tax_level(server_id, country_id).opinion_modifier

    def get_snapshot(self, server_id: str, country_id: str) -> dict:
        level = self.get_tax_level(server_id, country_id)
        return {
            "server_id":              server_id,
            "country_id":             country_id,
            "tax_level":              level.label,
            "income_multiplier":      level.income_multiplier,
            "monthly_opinion_change": level.opinion_modifier,
        }

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def set_tax_level(
        self,
        server_id:   str,
        country_id:  str,
        level:       str | TaxLevel,
    ) -> TaxLevel:
        """
        Set the tax level for a country.

        Parameters
        ----------
        level : str | TaxLevel
            Either a canonical label string (e.g. 'War Levy') or a TaxLevel enum.

        Returns the resolved TaxLevel.
        """
        if isinstance(level, str):
            tax = TaxLevel.from_label(level)
        else:
            tax = level

        self._db.get_or_create_country(server_id, country_id)
        self._db.update_fields(server_id, country_id, tax_level=tax.label)
        return tax

    # ------------------------------------------------------------------
    # Income calculation
    # ------------------------------------------------------------------

    def calculate_effective_income(
        self,
        server_id:       str,
        country_id:      str,
        base_income:     float,
    ) -> float:
        """
        Apply the current tax multiplier to a base income value.

        Parameters
        ----------
        base_income : float
            The country's raw daily_income before tax adjustments.

        Returns the effective taxed income.
        """
        multiplier = self.get_income_multiplier(server_id, country_id)
        return base_income * multiplier
