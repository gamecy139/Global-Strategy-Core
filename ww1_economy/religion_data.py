"""
WW1 RELIGION — STATIC DATA
----------------------------
Pure data module.  No I/O, no database access.

Defines the Religion enum and the passive diplomacy modifier matrix used by
ReligionSystem.get_relation_modifier().

Modifier rules (spec order, first match wins):
  1. Same religion         →  0
  2. Atheism vs any        → -2
  3. Catholic  ↔ Protestant → -2
  4. Catholic  ↔ Orthodox   → -3
  5. Protestant ↔ Orthodox  → -3
  6. Any other pairing      → -5   (different religion)

Persecution:
  If country A is actively persecuting religion R, every country B whose
  official religion is R receives an additional -10 to the relation.
"""

from __future__ import annotations

from enum import Enum


# ---------------------------------------------------------------------------
# Religion enum
# ---------------------------------------------------------------------------

class Religion(str, Enum):
    """Official religions recognised by the WW1 scenario."""
    CATHOLIC   = "Catholic Christian"
    PROTESTANT = "Protestant Christian"
    ORTHODOX   = "Orthodox Christian"
    SUNNI      = "Sunni Islam"
    JUDAISM    = "Judaism"
    ATHEISM    = "Atheism"


# Convenience collections
_CHRISTIAN: frozenset[str] = frozenset({
    Religion.CATHOLIC, Religion.PROTESTANT, Religion.ORTHODOX,
})

# Intra-Christian pair modifiers (pairs stored as frozensets → modifier)
_CHRISTIAN_PAIR: dict[frozenset, int] = {
    frozenset({Religion.CATHOLIC,   Religion.PROTESTANT}): -2,
    frozenset({Religion.CATHOLIC,   Religion.ORTHODOX}):   -3,
    frozenset({Religion.PROTESTANT, Religion.ORTHODOX}):   -3,
}

# Persecution penalty applied to a target country
PERSECUTION_PENALTY: int = -10

# All valid religion string values (for validation)
ALL_RELIGIONS: frozenset[str] = frozenset(r.value for r in Religion)


# ---------------------------------------------------------------------------
# Pure modifier function
# ---------------------------------------------------------------------------

def get_religion_modifier(rel_a: str, rel_b: str) -> int:
    """
    Return the passive diplomacy modifier between two country religions.

    Parameters
    ----------
    rel_a, rel_b : str
        Religion values (use Religion enum values, e.g. ``Religion.CATHOLIC``).

    Returns
    -------
    int  — A non-positive modifier in the range [-5, 0].
    """
    if rel_a == rel_b:
        return 0

    if rel_a == Religion.ATHEISM or rel_b == Religion.ATHEISM:
        return -2

    pair = frozenset({rel_a, rel_b})
    if pair in _CHRISTIAN_PAIR:
        return _CHRISTIAN_PAIR[pair]

    return -5
