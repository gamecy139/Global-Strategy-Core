"""
WW1 RELIGION SYSTEM
--------------------
Manages country and province religions, religious persecution, and the
passive diplomacy modifier that religion contributes to final relations.

All operations are keyed by (server_id, scenario_id).
No in-memory state — every read and write goes through EconomyDB.
"""

from __future__ import annotations

from dataclasses import dataclass

from ww1_economy.db            import EconomyDB
from ww1_economy.religion_data import (
    Religion, ALL_RELIGIONS,
    get_religion_modifier, PERSECUTION_PENALTY,
)


def _rel_str(religion: str) -> str:
    """Return the plain string value of a religion, regardless of whether it
    is a Religion enum instance or a raw string.  Needed because Python 3.11
    changed str-enum f-string formatting to return 'Religion.MEMBER' instead
    of the enum's string value."""
    return religion.value if hasattr(religion, "value") else str.__str__(religion)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ReligionModifierResult:
    """Full breakdown of the religion-sourced diplomacy modifier."""
    country_a:        str
    country_b:        str
    religion_a:       str
    religion_b:       str
    base_modifier:    int   # from religion pairing
    persecution_ab:   int   # A persecutes B's religion
    persecution_ba:   int   # B persecutes A's religion
    total:            int   # sum of all three


# ---------------------------------------------------------------------------
# ReligionSystem
# ---------------------------------------------------------------------------

class ReligionSystem:
    """
    Manages official religions for countries and provinces, persecution
    flags, and the passive modifier each religion pair adds to relations.

    Parameters
    ----------
    db : EconomyDB
        Shared DB handle (``db.init()`` must have been called).
    """

    def __init__(self, db: EconomyDB) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Country religion
    # ------------------------------------------------------------------

    def set_country_religion(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        religion:    str,
    ) -> str:
        """
        Set (or change) a country's official religion.

        Returns
        -------
        str — confirmation message.
        """
        if religion not in ALL_RELIGIONS:
            valid = ", ".join(sorted(ALL_RELIGIONS))
            return f"Unknown religion '{_rel_str(religion)}'. Valid: {valid}"
        # Normalize to plain string before storing
        religion = _rel_str(religion)
        self._db.upsert_country_religion(server_id, scenario_id, country_id, religion)
        return f"Country '{country_id}' official religion set to '{religion}'."

    def get_country_religion(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> str | None:
        """Return the official religion string of a country, or None."""
        row = self._db.get_country_religion(server_id, scenario_id, country_id)
        return row["religion"] if row else None

    # ------------------------------------------------------------------
    # Province religion
    # ------------------------------------------------------------------

    def set_province_religion(
        self,
        server_id:   str,
        scenario_id: str,
        province_id: str,
        religion:    str,
    ) -> str:
        if religion not in ALL_RELIGIONS:
            valid = ", ".join(sorted(ALL_RELIGIONS))
            return f"Unknown religion '{_rel_str(religion)}'. Valid: {valid}"
        religion = _rel_str(religion)
        self._db.upsert_province_religion(server_id, scenario_id, province_id, religion)
        return f"Province '{province_id}' religion set to '{religion}'."

    def get_province_religion(
        self,
        server_id:   str,
        scenario_id: str,
        province_id: str,
    ) -> str | None:
        row = self._db.get_province_religion(server_id, scenario_id, province_id)
        return row["religion"] if row else None

    # ------------------------------------------------------------------
    # Persecution
    # ------------------------------------------------------------------

    def set_persecution(
        self,
        server_id:           str,
        scenario_id:         str,
        country_id:          str,
        persecuted_religion: str,
    ) -> str:
        """
        Activate religious persecution in a country.
        Every country whose official religion is ``persecuted_religion``
        receives a -10 modifier on the relation with this country.

        Returns
        -------
        str — confirmation message.
        """
        if persecuted_religion not in ALL_RELIGIONS:
            valid = ", ".join(sorted(ALL_RELIGIONS))
            return f"Unknown religion '{_rel_str(persecuted_religion)}'. Valid: {valid}"
        persecuted_religion = _rel_str(persecuted_religion)
        row = self._db.get_country_religion(server_id, scenario_id, country_id)
        if row is None:
            return f"Country '{country_id}' has no religion set. Set a religion first."
        self._db.update_country_religion_fields(
            server_id, scenario_id, country_id,
            persecution_active=1,
            persecuted_religion=persecuted_religion,
        )
        return (
            f"Country '{country_id}' is now persecuting '{persecuted_religion}'. "
            f"Affected countries receive {PERSECUTION_PENALTY} to relations."
        )

    def clear_persecution(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> str:
        self._db.update_country_religion_fields(
            server_id, scenario_id, country_id,
            persecution_active=0,
            persecuted_religion=None,
        )
        return f"Country '{country_id}' persecution cleared."

    def get_persecution(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> dict | None:
        """
        Return persecution info, or None if persecution is not active.

        Returns
        -------
        dict with keys: ``persecuted_religion``
        """
        row = self._db.get_country_religion(server_id, scenario_id, country_id)
        if row and row.get("persecution_active"):
            return {"persecuted_religion": row["persecuted_religion"]}
        return None

    # ------------------------------------------------------------------
    # Diplomacy modifier
    # ------------------------------------------------------------------

    def get_relation_modifier(
        self,
        server_id:   str,
        scenario_id: str,
        country_a:   str,
        country_b:   str,
    ) -> ReligionModifierResult:
        """
        Compute the total religion-sourced diplomacy modifier between two
        countries.  This includes the passive religion-pairing modifier and
        any active persecution bonuses from either side.

        Returns
        -------
        ReligionModifierResult
        """
        row_a = self._db.get_country_religion(server_id, scenario_id, country_a)
        row_b = self._db.get_country_religion(server_id, scenario_id, country_b)

        rel_a = row_a["religion"] if row_a else Religion.ATHEISM
        rel_b = row_b["religion"] if row_b else Religion.ATHEISM

        base = get_religion_modifier(rel_a, rel_b)

        # Persecution A→B: A persecutes B's religion
        perseq_ab = 0
        if row_a and row_a.get("persecution_active") and row_a.get("persecuted_religion"):
            if row_a["persecuted_religion"] == rel_b:
                perseq_ab = PERSECUTION_PENALTY

        # Persecution B→A: B persecutes A's religion
        perseq_ba = 0
        if row_b and row_b.get("persecution_active") and row_b.get("persecuted_religion"):
            if row_b["persecuted_religion"] == rel_a:
                perseq_ba = PERSECUTION_PENALTY

        return ReligionModifierResult(
            country_a      = country_a,
            country_b      = country_b,
            religion_a     = rel_a,
            religion_b     = rel_b,
            base_modifier  = base,
            persecution_ab = perseq_ab,
            persecution_ba = perseq_ba,
            total          = base + perseq_ab + perseq_ba,
        )

    # ------------------------------------------------------------------
    # Bulk
    # ------------------------------------------------------------------

    def get_all_country_religions(
        self, server_id: str, scenario_id: str
    ) -> list[dict]:
        return self._db.get_all_country_religions(server_id, scenario_id)

    def get_all_province_religions(
        self, server_id: str, scenario_id: str
    ) -> list[dict]:
        return self._db.get_all_province_religions(server_id, scenario_id)
