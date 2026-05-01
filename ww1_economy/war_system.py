"""
WW1 WAR SYSTEM
---------------
Manages the complete war lifecycle:

  declare_war      → creates war record, sets in_active_war on both sides.
  add_war_score    → records a war event and adjusts scores (always sum 100).
  request_ceasefire / accept_ceasefire → ceasefire flow.
  surrender        → loser hands full victory rights (score ≤ 15%).
  proclaim_victory → winner claims victory (score ≥ 80%).
  spend_victory_score → winner spends points on post-war actions.
  process_war_tick → daily: province captures, reparation income, core/religion
                     conversion completions.

War score invariant: attacker_score + defender_score == 100 at all times.
                     Each side is clamped to [0, 100].

Post-war actions and costs (victory_score = winner's current score %):
  take_province    — 10–20 each   (must be occupied)
  puppet_state     — 80–100 total (exclusive; cannot combine with others)
  reparations      — 30–40        (2-year effect; stacks with provinces)
  insult           — 20–30        (relation hit + +5 opinion for winner)

Alliance rule: only the war LEADER receives rewards / penalties.
               Allies assist only.

All data is DB-backed.  No in-memory state.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field

from ww1_economy.db             import EconomyDB
from ww1_economy.diplomacy_system import DiplomacySystem


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WAR_SCORE_BATTLE_WIN:      float = 5.0
WAR_SCORE_PROVINCE_OCC:    float = 2.0
WAR_SCORE_ARMY_DESTROYED:  float = 10.0

REPARATION_DURATION_DAYS:  int   = 720   # 2 in-game years (360d/yr)
REPARATION_EFF_PENALTY:    float = -0.20 # loser economy_efficiency
REPARATION_DAILY_INCOME:   float = 1.5  # winner daily income bonus

CORE_CONVERSION_MIN:       int   = 60
CORE_CONVERSION_MAX:       int   = 120
RELIGION_CONV_MIN:         int   = 90
RELIGION_CONV_MAX:         int   = 150

NON_CORE_EFF_PENALTY:      float = -0.02  # per non-core province
RELIGION_CONV_EFF_PENALTY: float = -0.02  # per converting province
RELIGION_CONV_UNREST:      float = 5.0    # per converting province

# Post-war action cost bounds (inclusive)
COST_TAKE_PROVINCE     = (10, 20)
COST_PUPPET            = (80, 100)
COST_REPARATIONS       = (30, 40)
COST_INSULT            = (20, 30)

INSULT_RELATION_DELTA: float = -15.0
INSULT_OPINION_BONUS:  int   = 5


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class DeclareWarResult:
    ok:      bool
    war_id:  str | None
    message: str


@dataclass
class WarScoreEvent:
    event_type: str   # "battle_win" | "province_occupied" | "army_destroyed"
    beneficiary: str  # "attacker" | "defender"
    delta:        float
    attacker_score_after: float
    defender_score_after: float
    message:      str


@dataclass
class CeasefireResult:
    ok:      bool
    message: str


@dataclass
class VictoryResult:
    ok:           bool
    victory_score: float
    message:      str


@dataclass
class SpendResult:
    ok:            bool
    action:        str
    cost:          float
    score_before:  float
    score_after:   float
    message:       str
    effects:       list[str] = field(default_factory=list)


@dataclass
class WarTickResult:
    war_id:              str
    core_conversions:    list[str] = field(default_factory=list)
    religion_conversions: list[str] = field(default_factory=list)
    reparation_notes:    list[str] = field(default_factory=list)
    occupation_notes:    list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# WarSystem
# ---------------------------------------------------------------------------

class WarSystem:
    """
    Full war lifecycle manager.

    Parameters
    ----------
    db         : EconomyDB
    diplomacy  : DiplomacySystem  (used for alliance/war-declaration checks)
    """

    def __init__(self, db: EconomyDB, diplomacy: DiplomacySystem) -> None:
        self._db  = db
        self._dip = diplomacy

    # ==================================================================
    # DECLARE WAR
    # ==================================================================

    def declare_war(
        self,
        server_id:   str,
        scenario_id: str,
        attacker:    str,
        defender:    str,
        start_day:   int,
        attacker_allies: list[str] | None = None,
        defender_allies: list[str] | None = None,
    ) -> DeclareWarResult:
        """
        Declare war between attacker and defender.

        - Checks can_declare_war (no ally war).
        - Sets in_active_war=1 on all involved countries.
        - Creates war record + participant rows.
        - War leaders are the declared attacker / defender.
        """
        allowed, reason = self._dip.can_declare_war(
            server_id, scenario_id, attacker, defender
        )
        if not allowed:
            return DeclareWarResult(ok=False, war_id=None, message=reason)

        war_id = str(uuid.uuid4())
        self._db.insert_war(war_id, server_id, scenario_id, attacker, defender, start_day)

        # Leaders
        self._db.insert_war_participant(war_id, attacker, "attacker", is_leader=True)
        self._db.insert_war_participant(war_id, defender, "defender", is_leader=True)

        # Allies
        for ally in (attacker_allies or []):
            self._db.insert_war_participant(war_id, ally, "attacker", is_leader=False)
        for ally in (defender_allies or []):
            self._db.insert_war_participant(war_id, ally, "defender", is_leader=False)

        # Mark in_active_war on all participants
        all_countries = (
            [attacker, defender]
            + list(attacker_allies or [])
            + list(defender_allies or [])
        )
        for cid in set(all_countries):
            self._db.update_country_fields(
                server_id, scenario_id, cid, in_active_war=1
            )

        return DeclareWarResult(
            ok=True,
            war_id=war_id,
            message=(
                f"War declared: '{attacker}' attacks '{defender}' "
                f"(war_id={war_id}). "
                f"Scores: attacker=50, defender=50."
            ),
        )

    def add_ally_to_war(
        self,
        war_id:      str,
        server_id:   str,
        scenario_id: str,
        country_id:  str,
        side:        str,
    ) -> str:
        """Add an ally to an existing active war (side='attacker'|'defender')."""
        war = self._db.get_war(war_id)
        if war is None:
            return f"War '{war_id}' not found."
        if war["status"] != "active":
            return f"War '{war_id}' is not active (status={war['status']})."
        if side not in ("attacker", "defender"):
            return "side must be 'attacker' or 'defender'."
        self._db.insert_war_participant(war_id, country_id, side, is_leader=False)
        self._db.update_country_fields(
            server_id, scenario_id, country_id, in_active_war=1
        )
        return f"'{country_id}' joined war '{war_id}' on side '{side}'."

    # ==================================================================
    # WAR SCORE
    # ==================================================================

    def add_war_score(
        self,
        war_id:      str,
        event_type:  str,
        beneficiary: str,
    ) -> WarScoreEvent:
        """
        Record a war score event.

        Parameters
        ----------
        war_id       : str
        event_type   : "battle_win" | "province_occupied" | "army_destroyed"
        beneficiary  : "attacker" | "defender"  (the side that gains points)

        Returns
        -------
        WarScoreEvent
        """
        war = self._db.get_war(war_id)
        if war is None:
            return WarScoreEvent(
                event_type=event_type,
                beneficiary=beneficiary,
                delta=0,
                attacker_score_after=50,
                defender_score_after=50,
                message=f"War '{war_id}' not found.",
            )

        delta_map = {
            "battle_win":       WAR_SCORE_BATTLE_WIN,
            "province_occupied": WAR_SCORE_PROVINCE_OCC,
            "army_destroyed":   WAR_SCORE_ARMY_DESTROYED,
        }
        delta = delta_map.get(event_type, 0.0)

        att = float(war["war_score_attacker"])
        dfn = float(war["war_score_defender"])

        if beneficiary == "attacker":
            att = min(100.0, att + delta)
            dfn = 100.0 - att
        else:
            dfn = min(100.0, dfn + delta)
            att = 100.0 - dfn

        # Clamp both sides
        att = max(0.0, min(100.0, att))
        dfn = max(0.0, min(100.0, dfn))
        # Ensure sum == 100
        dfn = 100.0 - att

        self._db.update_war_fields(
            war_id,
            war_score_attacker=att,
            war_score_defender=dfn,
        )

        return WarScoreEvent(
            event_type=event_type,
            beneficiary=beneficiary,
            delta=delta,
            attacker_score_after=att,
            defender_score_after=dfn,
            message=(
                f"War score updated: attacker={att:.1f}, defender={dfn:.1f} "
                f"(+{delta:.1f} for {beneficiary} from {event_type})."
            ),
        )

    def get_war(self, war_id: str) -> dict | None:
        return self._db.get_war(war_id)

    def get_active_wars(self, server_id: str, scenario_id: str) -> list[dict]:
        return self._db.get_active_wars(server_id, scenario_id)

    def get_war_participants(self, war_id: str) -> list[dict]:
        return self._db.get_war_participants(war_id)

    # ==================================================================
    # WAR ACTIONS — Ceasefire / Surrender / Victory
    # ==================================================================

    def request_ceasefire(
        self,
        war_id:      str,
        requester:   str,
    ) -> CeasefireResult:
        """
        Request a ceasefire.  Valid when the requester's war score is in (15, 80).

        The opponent must call accept_ceasefire() to finalise.
        """
        war = self._db.get_war(war_id)
        if war is None:
            return CeasefireResult(ok=False, message=f"War '{war_id}' not found.")
        if war["status"] != "active":
            return CeasefireResult(ok=False, message="War is not active.")

        score = self._requester_score(war, requester)
        if score <= 15:
            return CeasefireResult(
                ok=False,
                message=(
                    f"Score {score:.1f}% is ≤15. You must surrender. "
                    "Use surrender() instead."
                ),
            )
        if score >= 80:
            return CeasefireResult(
                ok=False,
                message=(
                    f"Score {score:.1f}% is ≥80. Use proclaim_victory() instead."
                ),
            )

        self._db.update_war_fields(
            war_id, ceasefire_requested_by=requester, ceasefire_accepted=0
        )
        return CeasefireResult(
            ok=True,
            message=(
                f"'{requester}' has requested a ceasefire (score={score:.1f}%). "
                "The other party must call accept_ceasefire()."
            ),
        )

    def accept_ceasefire(
        self,
        war_id:    str,
        acceptor:  str,
    ) -> CeasefireResult:
        """Accept a pending ceasefire request.  Ends the war with no changes."""
        war = self._db.get_war(war_id)
        if war is None:
            return CeasefireResult(ok=False, message=f"War '{war_id}' not found.")
        if war["status"] != "active":
            return CeasefireResult(ok=False, message="War is not active.")
        if not war.get("ceasefire_requested_by"):
            return CeasefireResult(
                ok=False, message="No ceasefire has been requested for this war."
            )
        requester = war["ceasefire_requested_by"]
        if acceptor == requester:
            return CeasefireResult(
                ok=False, message="The ceasefire requester cannot accept their own request."
            )

        self._db.update_war_fields(
            war_id, status="ceasefire", ceasefire_accepted=1
        )
        self._clear_in_active_war(war_id, war["server_id"], war["scenario_id"])
        return CeasefireResult(
            ok=True,
            message=(
                f"Ceasefire accepted by '{acceptor}'. "
                f"War '{war_id}' ended with no territorial changes."
            ),
        )

    def surrender(
        self,
        war_id:     str,
        surrenderer: str,
    ) -> VictoryResult:
        """
        Surrender — available when score ≤ 15%.
        The opponent receives full victory rights (score set to 100).
        """
        war = self._db.get_war(war_id)
        if war is None:
            return VictoryResult(ok=False, victory_score=0, message=f"War '{war_id}' not found.")
        if war["status"] != "active":
            return VictoryResult(ok=False, victory_score=0, message="War is not active.")

        score = self._requester_score(war, surrenderer)
        if score > 15:
            return VictoryResult(
                ok=False,
                victory_score=score,
                message=f"Score {score:.1f}% is >15. Cannot surrender. Use ceasefire.",
            )

        # Set winner score to 100
        if surrenderer == war["attacker"]:
            self._db.update_war_fields(
                war_id, status="active",
                war_score_attacker=0, war_score_defender=100,
            )
            winner_score = 100.0
        else:
            self._db.update_war_fields(
                war_id, status="active",
                war_score_attacker=100, war_score_defender=0,
            )
            winner_score = 100.0

        return VictoryResult(
            ok=True,
            victory_score=winner_score,
            message=(
                f"'{surrenderer}' has surrendered. "
                "The opponent now holds full victory rights (score=100)."
            ),
        )

    def proclaim_victory(
        self,
        war_id:  str,
        winner:  str,
    ) -> VictoryResult:
        """
        Claim victory — available when score ≥ 80%.
        Returns the winner's current score as victory_score for spending.
        """
        war = self._db.get_war(war_id)
        if war is None:
            return VictoryResult(ok=False, victory_score=0, message=f"War '{war_id}' not found.")
        if war["status"] != "active":
            return VictoryResult(ok=False, victory_score=0, message="War is not active.")

        score = self._requester_score(war, winner)
        if score < 80:
            return VictoryResult(
                ok=False,
                victory_score=score,
                message=f"Score {score:.1f}% is <80. Need ≥80 to proclaim victory.",
            )

        return VictoryResult(
            ok=True,
            victory_score=score,
            message=(
                f"'{winner}' proclaims victory with score {score:.1f}%. "
                "Spend victory points before calling end_war()."
            ),
        )

    # ==================================================================
    # POST-WAR SPENDING
    # ==================================================================

    def spend_take_province(
        self,
        war_id:      str,
        winner:      str,
        province_id: str,
        cost:        float,
        current_day: int,
    ) -> SpendResult:
        """
        Take a province.  Province must be occupied; cost in [10, 20].
        Starts core conversion (60-120 days) and religion conversion if needed.
        """
        lo, hi = COST_TAKE_PROVINCE
        if not (lo <= cost <= hi):
            return SpendResult(
                ok=False, action="take_province", cost=cost,
                score_before=0, score_after=0,
                message=f"Province cost must be {lo}–{hi}."
            )

        war = self._db.get_war(war_id)
        if war is None:
            return SpendResult(
                ok=False, action="take_province", cost=cost,
                score_before=0, score_after=0,
                message=f"War '{war_id}' not found."
            )

        server_id   = war["server_id"]
        scenario_id = war["scenario_id"]
        score       = self._requester_score(war, winner)

        if cost > score:
            return SpendResult(
                ok=False, action="take_province", cost=cost,
                score_before=score, score_after=score,
                message=f"Insufficient victory score ({score:.1f} < {cost})."
            )

        # Province must be occupied by winner
        occ = self._db.get_province_occupation(server_id, scenario_id, province_id)
        if occ is None or not occ.get("is_occupied") or occ["occupying_country"] != winner:
            return SpendResult(
                ok=False, action="take_province", cost=cost,
                score_before=score, score_after=score,
                message=f"Province '{province_id}' is not fully occupied by '{winner}'."
            )

        # Deduct score
        new_score = score - cost
        self._set_requester_score(war_id, war, winner, new_score)

        effects = []

        # Transfer province ownership
        self._db.update_province_fields(
            server_id, scenario_id, province_id, owner_country=winner
        )
        effects.append(f"Province '{province_id}' owner → '{winner}'.")

        # Mark is_core=False, start conversion
        conv_days = (CORE_CONVERSION_MIN + CORE_CONVERSION_MAX) // 2  # 90 days
        self._db.upsert_province_core(
            server_id, scenario_id, province_id, winner,
            is_core=0,
            conversion_start_day=current_day,
            conversion_end_day=current_day + conv_days,
        )
        effects.append(f"Core conversion started: {conv_days} days.")

        # Religion conversion if needed
        prov_rel_row = self._db.get_province_religion(server_id, scenario_id, province_id)
        country_rel_row = self._db.get_country_religion(server_id, scenario_id, winner)
        if prov_rel_row and country_rel_row:
            if prov_rel_row["religion"] != country_rel_row["religion"]:
                rel_conv_days = (RELIGION_CONV_MIN + RELIGION_CONV_MAX) // 2  # 120 days
                self._db.upsert_province_religion_conversion(
                    server_id, scenario_id, province_id,
                    from_religion=prov_rel_row["religion"],
                    to_religion=country_rel_row["religion"],
                    conversion_start_day=current_day,
                    conversion_end_day=current_day + rel_conv_days,
                )
                effects.append(
                    f"Religion conversion started: "
                    f"{prov_rel_row['religion']} → {country_rel_row['religion']} "
                    f"({rel_conv_days} days)."
                )

        return SpendResult(
            ok=True, action="take_province", cost=cost,
            score_before=score, score_after=new_score,
            message=f"Province '{province_id}' annexed by '{winner}'.",
            effects=effects,
        )

    def spend_puppet_state(
        self,
        war_id:      str,
        winner:      str,
        target:      str,
        cost:        float,
        current_day: int,
    ) -> SpendResult:
        """
        Puppet a country.  Exclusive action (cannot combine with others).
        Cost in [80, 100].  Effects: forced alliance + 30% monthly treasury.
        """
        lo, hi = COST_PUPPET
        if not (lo <= cost <= hi):
            return SpendResult(
                ok=False, action="puppet", cost=cost,
                score_before=0, score_after=0,
                message=f"Puppet cost must be {lo}–{hi}."
            )

        war = self._db.get_war(war_id)
        if war is None:
            return SpendResult(
                ok=False, action="puppet", cost=cost,
                score_before=0, score_after=0,
                message=f"War '{war_id}' not found."
            )

        server_id   = war["server_id"]
        scenario_id = war["scenario_id"]
        score       = self._requester_score(war, winner)

        if cost > score:
            return SpendResult(
                ok=False, action="puppet", cost=cost,
                score_before=score, score_after=score,
                message=f"Insufficient victory score ({score:.1f} < {cost})."
            )

        new_score = score - cost
        self._set_requester_score(war_id, war, winner, new_score)

        # Create puppet relationship
        self._db.insert_puppet_state(server_id, scenario_id, target, winner)

        # Forced alliance: create or join an alliance
        existing = self._dip.get_country_alliances(server_id, scenario_id, winner)
        if existing:
            # Join the first existing alliance of the winner
            aid = existing[0]["alliance_id"] if isinstance(existing[0], dict) else existing[0].alliance_id
            self._db.add_alliance_member(aid, target, server_id, scenario_id)
            alliance_note = f"'{target}' forced into alliance '{aid}'."
        else:
            info = self._dip.create_alliance(
                server_id, scenario_id,
                [winner, target],
                alliance_name=f"{winner}_puppet_pact",
            )
            alliance_note = f"Forced alliance created (id={info.alliance_id})."

        return SpendResult(
            ok=True, action="puppet", cost=cost,
            score_before=score, score_after=new_score,
            message=f"'{target}' is now a puppet of '{winner}'.",
            effects=[alliance_note, "Puppet pays 30% of monthly treasury to overlord."],
        )

    def spend_reparations(
        self,
        war_id:      str,
        winner:      str,
        loser:       str,
        cost:        float,
        current_day: int,
    ) -> SpendResult:
        """
        Impose war reparations.  Cost in [30, 40].
        Effects for 2 years: loser -20% efficiency, winner +1.5 daily income.
        """
        lo, hi = COST_REPARATIONS
        if not (lo <= cost <= hi):
            return SpendResult(
                ok=False, action="reparations", cost=cost,
                score_before=0, score_after=0,
                message=f"Reparations cost must be {lo}–{hi}."
            )

        war = self._db.get_war(war_id)
        if war is None:
            return SpendResult(
                ok=False, action="reparations", cost=cost,
                score_before=0, score_after=0,
                message=f"War '{war_id}' not found."
            )

        server_id   = war["server_id"]
        scenario_id = war["scenario_id"]
        score       = self._requester_score(war, winner)

        if cost > score:
            return SpendResult(
                ok=False, action="reparations", cost=cost,
                score_before=score, score_after=score,
                message=f"Insufficient victory score ({score:.1f} < {cost})."
            )

        new_score = score - cost
        self._set_requester_score(war_id, war, winner, new_score)

        end_day = current_day + REPARATION_DURATION_DAYS
        self._db.insert_war_reparations(
            war_id, loser, winner, server_id, scenario_id,
            start_day=current_day, end_day=end_day,
        )

        # Apply immediate economy effects
        loser_row = self._db.get_country(server_id, scenario_id, loser)
        if loser_row:
            current_eff = float(loser_row.get("economy_efficiency") or 1.0)
            new_eff = max(0.5, current_eff + REPARATION_EFF_PENALTY)
            self._db.update_country_fields(
                server_id, scenario_id, loser, economy_efficiency=new_eff
            )

        winner_row = self._db.get_country(server_id, scenario_id, winner)
        if winner_row:
            current_inc = float(winner_row.get("daily_base_income") or 0.0)
            self._db.update_country_fields(
                server_id, scenario_id, winner,
                daily_base_income=current_inc + REPARATION_DAILY_INCOME,
            )

        return SpendResult(
            ok=True, action="reparations", cost=cost,
            score_before=score, score_after=new_score,
            message=f"War reparations imposed on '{loser}' for {REPARATION_DURATION_DAYS} days.",
            effects=[
                f"'{loser}' economy_efficiency {REPARATION_EFF_PENALTY:+.0%} for 2 years.",
                f"'{winner}' +{REPARATION_DAILY_INCOME} daily income for 2 years.",
            ],
        )

    def spend_insult(
        self,
        war_id:   str,
        winner:   str,
        loser:    str,
        cost:     float,
    ) -> SpendResult:
        """
        Insult the loser.  Cost in [20, 30].
        Effects: -15 base relation, +5 winner population opinion.
        """
        lo, hi = COST_INSULT
        if not (lo <= cost <= hi):
            return SpendResult(
                ok=False, action="insult", cost=cost,
                score_before=0, score_after=0,
                message=f"Insult cost must be {lo}–{hi}."
            )

        war = self._db.get_war(war_id)
        if war is None:
            return SpendResult(
                ok=False, action="insult", cost=cost,
                score_before=0, score_after=0,
                message=f"War '{war_id}' not found."
            )

        server_id   = war["server_id"]
        scenario_id = war["scenario_id"]
        score       = self._requester_score(war, winner)

        if cost > score:
            return SpendResult(
                ok=False, action="insult", cost=cost,
                score_before=score, score_after=score,
                message=f"Insufficient victory score ({score:.1f} < {cost})."
            )

        new_score = score - cost
        self._set_requester_score(war_id, war, winner, new_score)

        # Relation hit
        new_rel = self._db.adjust_base_relation(
            server_id, scenario_id, winner, loser, INSULT_RELATION_DELTA
        )

        # Opinion boost for winner
        winner_row = self._db.get_country(server_id, scenario_id, winner)
        if winner_row:
            op = int(winner_row.get("population_opinion") or 0)
            new_op = min(100, op + INSULT_OPINION_BONUS)
            self._db.update_country_fields(
                server_id, scenario_id, winner, population_opinion=new_op
            )

        return SpendResult(
            ok=True, action="insult", cost=cost,
            score_before=score, score_after=new_score,
            message=f"'{winner}' insulted '{loser}'.",
            effects=[
                f"Relation {winner}↔{loser} → {new_rel:.0f} ({INSULT_RELATION_DELTA:+.0f}).",
                f"'{winner}' population opinion +{INSULT_OPINION_BONUS}.",
            ],
        )

    # ==================================================================
    # END WAR
    # ==================================================================

    def end_war(
        self,
        war_id:      str,
        final_status: str = "peace",
    ) -> str:
        """
        Formally end a war.  Clears in_active_war for all participants.

        Parameters
        ----------
        final_status : "peace" | "attacker_victory" | "defender_victory" | "ceasefire"
        """
        war = self._db.get_war(war_id)
        if war is None:
            return f"War '{war_id}' not found."

        self._db.update_war_fields(war_id, status=final_status)
        self._clear_in_active_war(war_id, war["server_id"], war["scenario_id"])
        return f"War '{war_id}' ended with status '{final_status}'."

    # ==================================================================
    # DAILY WAR TICK
    # ==================================================================

    def process_war_tick(
        self,
        server_id:    str,
        scenario_id:  str,
        current_day:  int,
    ) -> list[WarTickResult]:
        """
        Daily tick for all active wars.

        - Completes pending core conversions (remove penalty).
        - Completes pending religion conversions (update province religion).
        - Processes reparation expirations (remove effects).

        Returns list of results (one per active war or shared effects).
        """
        results: list[WarTickResult] = []

        # --- Core conversions ---
        cores = self._db.get_pending_core_conversions(server_id, scenario_id)
        core_events: list[str] = []
        for core in cores:
            end_day = core.get("conversion_end_day")
            if end_day and current_day >= end_day:
                self._db.upsert_province_core(
                    server_id, scenario_id,
                    core["province_id"], core["country_id"],
                    is_core=1,
                    conversion_start_day=None,
                    conversion_end_day=None,
                )
                core_events.append(
                    f"Province '{core['province_id']}' is now a core of "
                    f"'{core['country_id']}'."
                )

        # --- Religion conversions ---
        conversions = self._db.get_pending_religion_conversions(server_id, scenario_id)
        rel_events: list[str] = []
        for conv in conversions:
            if current_day >= conv["conversion_end_day"]:
                self._db.upsert_province_religion(
                    server_id, scenario_id,
                    conv["province_id"],
                    conv["to_religion"],
                )
                self._db.delete_province_religion_conversion(
                    server_id, scenario_id, conv["province_id"]
                )
                rel_events.append(
                    f"Province '{conv['province_id']}' religion converted: "
                    f"{conv['from_religion']} → {conv['to_religion']}."
                )

        # --- Reparation expirations ---
        rep_events: list[str] = []
        active_reps = self._db.get_active_reparations(server_id, scenario_id, current_day)
        all_reps_all = self._db.get_active_reparations(server_id, scenario_id, 0)
        # Find reparations that expired today (end_day < current_day)
        with self._db._connection() as conn:
            conn.row_factory = __import__("sqlite3").Row
            expired = conn.execute(
                "SELECT * FROM war_reparations "
                "WHERE server_id=? AND scenario_id=? AND end_day < ?",
                (server_id, scenario_id, current_day),
            ).fetchall()
        for rep in [dict(r) for r in expired]:
            # Restore loser economy efficiency
            loser_row = self._db.get_country(
                server_id, scenario_id, rep["loser_country"]
            )
            if loser_row:
                current_eff = float(loser_row.get("economy_efficiency") or 1.0)
                restored    = min(1.0, current_eff - REPARATION_EFF_PENALTY)
                self._db.update_country_fields(
                    server_id, scenario_id, rep["loser_country"],
                    economy_efficiency=restored,
                )
            # Restore winner daily income
            winner_row = self._db.get_country(
                server_id, scenario_id, rep["winner_country"]
            )
            if winner_row:
                current_inc = float(winner_row.get("daily_base_income") or 0.0)
                self._db.update_country_fields(
                    server_id, scenario_id, rep["winner_country"],
                    daily_base_income=max(0.0, current_inc - REPARATION_DAILY_INCOME),
                )
            # Delete the reparation
            with self._db._connection() as conn:
                conn.execute(
                    "DELETE FROM war_reparations "
                    "WHERE war_id=? AND loser_country=? AND winner_country=?",
                    (rep["war_id"], rep["loser_country"], rep["winner_country"]),
                )
            rep_events.append(
                f"Reparations ended: '{rep['loser_country']}' → "
                f"'{rep['winner_country']}' (war={rep['war_id']})."
            )

        # --- Puppet treasury transfer (processed monthly; here we note it) ---
        # Actual transfer is done by the caller's monthly tick using
        # get_puppet_treasury_due() below.

        if core_events or rel_events or rep_events:
            results.append(WarTickResult(
                war_id="shared",
                core_conversions=core_events,
                religion_conversions=rel_events,
                reparation_notes=rep_events,
            ))
        return results

    # ==================================================================
    # PUPPET MONTHLY PAYMENT
    # ==================================================================

    def get_puppet_treasury_due(
        self,
        server_id:   str,
        scenario_id: str,
    ) -> list[dict]:
        """
        Return all puppet treasury transfers due this month.

        Returns list of dicts:
            puppet_country, overlord_country, amount_due
        """
        rows = []
        with self._db._connection() as conn:
            conn.row_factory = __import__("sqlite3").Row
            puppets = conn.execute(
                "SELECT * FROM puppet_states WHERE server_id=? AND scenario_id=?",
                (server_id, scenario_id),
            ).fetchall()

        for p in [dict(r) for r in puppets]:
            puppet  = p["puppet_country"]
            overlord = p["overlord_country"]
            puppet_row = self._db.get_country(server_id, scenario_id, puppet)
            if puppet_row:
                treasury = float(puppet_row.get("treasury") or 0.0)
                due = treasury * 0.30
                rows.append({
                    "puppet_country":  puppet,
                    "overlord_country": overlord,
                    "amount_due":      round(due, 2),
                })
        return rows

    def apply_puppet_payment(
        self,
        server_id:   str,
        scenario_id: str,
        puppet:      str,
        overlord:    str,
        amount:      float,
    ) -> str:
        """Deduct amount from puppet treasury and add to overlord."""
        puppet_row  = self._db.get_country(server_id, scenario_id, puppet)
        overlord_row = self._db.get_country(server_id, scenario_id, overlord)
        if not puppet_row or not overlord_row:
            return "Country not found."
        puppet_treasury  = float(puppet_row.get("treasury") or 0.0)
        overlord_treasury = float(overlord_row.get("treasury") or 0.0)
        deduct  = min(amount, puppet_treasury)
        self._db.update_country_fields(
            server_id, scenario_id, puppet,
            treasury=puppet_treasury - deduct,
        )
        self._db.update_country_fields(
            server_id, scenario_id, overlord,
            treasury=overlord_treasury + deduct,
        )
        return (
            f"Puppet payment: '{puppet}' paid {deduct:.2f} gold to '{overlord}'."
        )

    # ==================================================================
    # Internal helpers
    # ==================================================================

    def _requester_score(self, war: dict, requester: str) -> float:
        """Return the war score of the requesting country."""
        if requester == war["attacker"]:
            return float(war["war_score_attacker"])
        return float(war["war_score_defender"])

    def _set_requester_score(
        self, war_id: str, war: dict, requester: str, new_score: float
    ) -> None:
        new_score = max(0.0, min(100.0, new_score))
        if requester == war["attacker"]:
            self._db.update_war_fields(
                war_id,
                war_score_attacker=new_score,
                war_score_defender=100.0 - new_score,
            )
        else:
            self._db.update_war_fields(
                war_id,
                war_score_defender=new_score,
                war_score_attacker=100.0 - new_score,
            )

    def _clear_in_active_war(
        self, war_id: str, server_id: str, scenario_id: str
    ) -> None:
        """Clear in_active_war=0 for all participants if they have no other active wars."""
        participants = self._db.get_war_participants(war_id)
        war = self._db.get_war(war_id)
        # Include leader countries
        all_countries = set(p["country_id"] for p in participants)
        if war:
            all_countries.add(war["attacker"])
            all_countries.add(war["defender"])

        for cid in all_countries:
            other_wars = self._db.get_country_active_wars(server_id, scenario_id, cid)
            # Exclude the current war from the check
            other_active = [w for w in other_wars if w["war_id"] != war_id
                            and w["status"] == "active"]
            if not other_active:
                self._db.update_country_fields(
                    server_id, scenario_id, cid, in_active_war=0
                )
