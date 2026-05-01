"""
WW1 DIPLOMACY SYSTEM
----------------------
Manages bilateral relations and alliances.

final_relation = base_relation + religion_modifier + persecution_modifiers

Rules enforced:
  - Cannot declare war on an ally.
  - Relations clamped to [0, 100].
  - Alliances are per (server_id, scenario_id).

All data is DB-backed.  No in-memory state.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from ww1_economy.db             import EconomyDB
from ww1_economy.religion_system import ReligionSystem, ReligionModifierResult


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class FinalRelationResult:
    country_a:        str
    country_b:        str
    base_relation:    float
    religion_total:   int
    final_relation:   float
    religion_detail:  ReligionModifierResult | None = None
    is_allied:        bool = False
    at_war:           bool = False


@dataclass
class AllianceInfo:
    alliance_id:   str
    alliance_name: str
    members:       list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# DiplomacySystem
# ---------------------------------------------------------------------------

class DiplomacySystem:
    """
    Manages bilateral relations, alliances, and the war-declaration gate.

    Parameters
    ----------
    db       : EconomyDB
    religion : ReligionSystem  (used to compute religion modifiers)
    """

    def __init__(self, db: EconomyDB, religion: ReligionSystem) -> None:
        self._db  = db
        self._rel = religion

    # ------------------------------------------------------------------
    # Relations
    # ------------------------------------------------------------------

    def set_base_relation(
        self,
        server_id:    str,
        scenario_id:  str,
        country_a:    str,
        country_b:    str,
        value:        float,
    ) -> str:
        """Set the base (non-religion) relation between two countries."""
        value = max(0.0, min(100.0, float(value)))
        self._db.upsert_relation(server_id, scenario_id, country_a, country_b, value)
        return (
            f"Base relation {country_a}↔{country_b} set to {value:.0f}."
        )

    def adjust_base_relation(
        self,
        server_id:   str,
        scenario_id: str,
        country_a:   str,
        country_b:   str,
        delta:       float,
    ) -> float:
        """Add delta to base_relation (clamped [0, 100]).  Returns new value."""
        return self._db.adjust_base_relation(
            server_id, scenario_id, country_a, country_b, delta
        )

    def get_base_relation(
        self,
        server_id:   str,
        scenario_id: str,
        country_a:   str,
        country_b:   str,
    ) -> float:
        row = self._db.get_relation(server_id, scenario_id, country_a, country_b)
        return float(row["base_relation"]) if row else 50.0

    def get_final_relation(
        self,
        server_id:   str,
        scenario_id: str,
        country_a:   str,
        country_b:   str,
    ) -> FinalRelationResult:
        """
        Compute the full relation including religion modifiers.

        final_relation = base_relation + religion_modifier + persecution
        Clamped to [0, 100].
        """
        base = self.get_base_relation(server_id, scenario_id, country_a, country_b)
        rel_mod = self._rel.get_relation_modifier(
            server_id, scenario_id, country_a, country_b
        )
        final = max(0.0, min(100.0, base + rel_mod.total))

        allied   = self.is_allied(server_id, scenario_id, country_a, country_b)
        at_war   = self._are_at_war(server_id, scenario_id, country_a, country_b)

        return FinalRelationResult(
            country_a      = country_a,
            country_b      = country_b,
            base_relation  = base,
            religion_total = rel_mod.total,
            final_relation = final,
            religion_detail = rel_mod,
            is_allied      = allied,
            at_war         = at_war,
        )

    def get_all_relations(
        self, server_id: str, scenario_id: str
    ) -> list[dict]:
        return self._db.get_all_relations(server_id, scenario_id)

    # ------------------------------------------------------------------
    # Alliances
    # ------------------------------------------------------------------

    def create_alliance(
        self,
        server_id:     str,
        scenario_id:   str,
        founding_members: list[str],
        alliance_name: str = "",
    ) -> AllianceInfo:
        """
        Create a new alliance and add founding members.

        Returns
        -------
        AllianceInfo
        """
        alliance_id = str(uuid.uuid4())
        self._db.insert_alliance(alliance_id, server_id, scenario_id, alliance_name)
        for country_id in founding_members:
            self._db.add_alliance_member(
                alliance_id, country_id, server_id, scenario_id
            )
        return AllianceInfo(
            alliance_id=alliance_id,
            alliance_name=alliance_name,
            members=list(founding_members),
        )

    def join_alliance(
        self,
        server_id:   str,
        scenario_id: str,
        alliance_id: str,
        country_id:  str,
    ) -> str:
        alliance = self._db.get_alliance(alliance_id)
        if alliance is None:
            return f"Alliance '{alliance_id}' not found."
        if (alliance["server_id"] != server_id
                or alliance["scenario_id"] != scenario_id):
            return "Alliance does not belong to this server/scenario."
        self._db.add_alliance_member(
            alliance_id, country_id, server_id, scenario_id
        )
        return f"Country '{country_id}' joined alliance '{alliance_id}'."

    def leave_alliance(
        self,
        alliance_id: str,
        country_id:  str,
    ) -> str:
        self._db.remove_alliance_member(alliance_id, country_id)
        members = self._db.get_alliance_members(alliance_id)
        if not members:
            self._db.delete_alliance(alliance_id)
            return (
                f"Country '{country_id}' left alliance '{alliance_id}'. "
                "Alliance disbanded (no members remaining)."
            )
        return f"Country '{country_id}' left alliance '{alliance_id}'."

    def disband_alliance(self, alliance_id: str) -> str:
        alliance = self._db.get_alliance(alliance_id)
        if alliance is None:
            return f"Alliance '{alliance_id}' not found."
        self._db.delete_alliance(alliance_id)
        return f"Alliance '{alliance_id}' disbanded."

    def get_alliance_info(self, alliance_id: str) -> AllianceInfo | None:
        alliance = self._db.get_alliance(alliance_id)
        if alliance is None:
            return None
        members = self._db.get_alliance_members(alliance_id)
        return AllianceInfo(
            alliance_id=alliance_id,
            alliance_name=alliance.get("alliance_name", ""),
            members=members,
        )

    def get_country_alliances(
        self, server_id: str, scenario_id: str, country_id: str
    ) -> list[AllianceInfo]:
        rows = self._db.get_country_alliances(server_id, scenario_id, country_id)
        result = []
        for row in rows:
            members = self._db.get_alliance_members(row["alliance_id"])
            result.append(AllianceInfo(
                alliance_id=row["alliance_id"],
                alliance_name=row.get("alliance_name", ""),
                members=members,
            ))
        return result

    def get_allies(
        self,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
    ) -> list[str]:
        """Return all countries in the same alliance(s) as country_id."""
        alliances = self._db.get_country_alliances(server_id, scenario_id, country_id)
        allies: set[str] = set()
        for a in alliances:
            members = self._db.get_alliance_members(a["alliance_id"])
            allies.update(members)
        allies.discard(country_id)
        return sorted(allies)

    def is_allied(
        self,
        server_id:   str,
        scenario_id: str,
        country_a:   str,
        country_b:   str,
    ) -> bool:
        """Return True if country_a and country_b share any alliance."""
        allies = self.get_allies(server_id, scenario_id, country_a)
        return country_b in allies

    def get_scenario_alliances(
        self, server_id: str, scenario_id: str
    ) -> list[AllianceInfo]:
        rows = self._db.get_scenario_alliances(server_id, scenario_id)
        result = []
        for row in rows:
            members = self._db.get_alliance_members(row["alliance_id"])
            result.append(AllianceInfo(
                alliance_id=row["alliance_id"],
                alliance_name=row.get("alliance_name", ""),
                members=members,
            ))
        return result

    # ------------------------------------------------------------------
    # War declaration gate
    # ------------------------------------------------------------------

    def can_declare_war(
        self,
        server_id:   str,
        scenario_id: str,
        attacker:    str,
        defender:    str,
    ) -> tuple[bool, str]:
        """
        Check whether attacker can declare war on defender.

        Returns
        -------
        (allowed: bool, reason: str)
        """
        if attacker == defender:
            return False, "A country cannot declare war on itself."
        if self.is_allied(server_id, scenario_id, attacker, defender):
            return False, (
                f"'{attacker}' and '{defender}' are in the same alliance. "
                "Break the alliance first."
            )
        if self._are_at_war(server_id, scenario_id, attacker, defender):
            return False, "These countries are already at war."
        return True, "War declaration permitted."

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _are_at_war(
        self,
        server_id:   str,
        scenario_id: str,
        country_a:   str,
        country_b:   str,
    ) -> bool:
        """Check if two countries are in an active war against each other."""
        active_wars = self._db.get_active_wars(server_id, scenario_id)
        for war in active_wars:
            sides = {war["attacker"], war["defender"]}
            # Also check participants
            participants = self._db.get_war_participants(war["war_id"])
            sides.update(p["country_id"] for p in participants)
            if country_a in sides and country_b in sides:
                return True
        return False
