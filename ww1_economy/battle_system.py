"""
WW1 BATTLE SYSTEM
------------------
Triggers and resolves battles when opposing armies share a province.

Battle lifecycle
----------------
1. trigger_battle()    — called when an army enters a province occupied by an enemy.
                         Creates a battle record and sets both armies to in_combat.
2. resolve_battle_tick() — called each game day while battle is active.
                         Deals proportional damage to both sides.
3. check_retreats()    — after each tick, auto-retreats armies at ≤30% strength.
4. check_destroyed()   — if a retreating army is attacked, it is destroyed.

Damage formula (per tick):
    power_A = sum(quantity × battle_points) × (strength / 100)   for side A
    power_B = similar for side B
    total    = power_A + power_B

    if total > 0:
        damage_to_A = (power_B / total) × DAMAGE_RATE_PCT  (strength points)
        damage_to_B = (power_A / total) × DAMAGE_RATE_PCT

DAMAGE_RATE_PCT = 15 per tick (both sides combined lose 15 strength points;
                  distribution is proportional to relative power).

Retreat:  strength ≤ 30%  → retreat_army() called immediately.
Destroy:  attacked while state == 'retreating'  → army destroyed, +10 war score.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from ww1_economy.db         import EconomyDB
from ww1_economy.army_system import ArmySystem
from ww1_economy.war_system  import WarSystem


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DAMAGE_RATE_PCT:        float = 15.0  # total strength points distributed per tick
RETREAT_THRESHOLD:      float = 30.0  # strength ≤ this triggers retreat
MIN_BATTLE_TICK_GAP:    int   = 1     # minimum days between battle ticks
MAX_BATTLE_DURATION_DAYS: int = 10   # auto-resolve after this many game-days


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class TriggerBattleResult:
    ok:        bool
    battle_id: str | None
    message:   str


@dataclass
class BattleTick:
    battle_id:         str
    province_id:       str
    army_a_id:         str
    army_b_id:         str
    power_a:           float
    power_b:           float
    damage_to_a:       float
    damage_to_b:       float
    strength_a_after:  float
    strength_b_after:  float
    a_retreated:       bool = False
    b_retreated:       bool = False
    a_destroyed:       bool = False
    b_destroyed:       bool = False
    winner_army_id:    str | None = None
    message:           str = ""


@dataclass
class BattleProcessResult:
    battles_ticked:    int
    events:            list[BattleTick] = field(default_factory=list)


# ---------------------------------------------------------------------------
# BattleSystem
# ---------------------------------------------------------------------------

class BattleSystem:
    """
    Triggers and resolves battles.

    Parameters
    ----------
    db      : EconomyDB
    army    : ArmySystem
    war     : WarSystem  (for war score updates)
    """

    def __init__(
        self,
        db:   EconomyDB,
        army: ArmySystem,
        war:  WarSystem,
    ) -> None:
        self._db   = db
        self._army = army
        self._war  = war

    # ------------------------------------------------------------------
    # Trigger
    # ------------------------------------------------------------------

    def trigger_battle(
        self,
        server_id:   str,
        scenario_id: str,
        war_id:      str,
        army_a_id:   str,   # entering / attacker army
        army_b_id:   str,   # defending army
        province_id: str,
        current_day: int,
    ) -> TriggerBattleResult:
        """
        Start a battle between two armies in a province.

        The entering army must be in the same province as the defender.
        If the defender is in 'retreating' state, it is immediately destroyed.
        """
        row_a = self._db.get_army(army_a_id)
        row_b = self._db.get_army(army_b_id)

        if row_a is None or row_b is None:
            return TriggerBattleResult(ok=False, battle_id=None,
                                       message="One or both armies not found.")
        if row_a["province_id"] != row_b["province_id"]:
            return TriggerBattleResult(ok=False, battle_id=None,
                                       message="Armies are not in the same province.")
        if row_a["country_id"] == row_b["country_id"]:
            return TriggerBattleResult(ok=False, battle_id=None,
                                       message="Cannot battle your own army.")

        # Check existing active battle in this province
        existing = self._db.get_battle_in_province(server_id, scenario_id, province_id)
        if existing:
            return TriggerBattleResult(
                ok=False, battle_id=existing["battle_id"],
                message=f"Battle already active in '{province_id}'.",
            )

        # Defender is retreating → destroy immediately
        if row_b["state"] == "retreating":
            self._army.destroy_army(army_b_id)
            self._award_destroy_war_score(war_id, row_a["country_id"], row_b["country_id"])
            return TriggerBattleResult(
                ok=True, battle_id=None,
                message=(
                    f"Army '{army_b_id}' was retreating and has been destroyed "
                    f"(+{10} war score)."
                ),
            )

        battle_id = str(uuid.uuid4())
        self._db.insert_battle(
            battle_id, war_id, server_id, scenario_id,
            province_id, army_a_id, army_b_id, current_day,
        )
        # Set both armies to in_combat
        self._db.update_army_fields(army_a_id, state="in_combat")
        self._db.update_army_fields(army_b_id, state="in_combat")

        return TriggerBattleResult(
            ok=True,
            battle_id=battle_id,
            message=(
                f"Battle started in '{province_id}' "
                f"(battle_id={battle_id}, day={current_day})."
            ),
        )

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    def resolve_battle_tick(
        self,
        battle_id:   str,
        server_id:   str,
        scenario_id: str,
        current_day: int,
    ) -> BattleTick | None:
        """
        Apply one damage tick to an active battle.

        Auto-resolves if MAX_BATTLE_DURATION_DAYS exceeded.
        Only fires if current_day - last_tick_day >= MIN_BATTLE_TICK_GAP.
        Returns None if it is too early to tick.
        """
        battle = self._db.get_battle(battle_id)
        if battle is None or battle["status"] != "active":
            return None

        # Auto-resolve after 10 game-days
        start_day = int(battle.get("start_day") or current_day)
        if (current_day - start_day) >= MAX_BATTLE_DURATION_DAYS:
            return self._auto_resolve(battle, server_id, scenario_id, current_day)

        if (current_day - int(battle["last_tick_day"])) < MIN_BATTLE_TICK_GAP:
            return None

        army_a_id = battle["army_a_id"]
        army_b_id = battle["army_b_id"]

        row_a = self._db.get_army(army_a_id)
        row_b = self._db.get_army(army_b_id)

        if row_a is None or row_b is None:
            return None

        power_a = self._army.get_army_battle_power(army_a_id, server_id, scenario_id)
        power_b = self._army.get_army_battle_power(army_b_id, server_id, scenario_id)
        total   = power_a + power_b

        str_a = float(row_a["strength_pct"])
        str_b = float(row_b["strength_pct"])

        if total > 0:
            damage_a = (power_b / total) * DAMAGE_RATE_PCT
            damage_b = (power_a / total) * DAMAGE_RATE_PCT
        else:
            damage_a = DAMAGE_RATE_PCT / 2
            damage_b = DAMAGE_RATE_PCT / 2

        str_a_after = max(0.0, str_a - damage_a)
        str_b_after = max(0.0, str_b - damage_b)

        self._db.update_army_fields(army_a_id, strength_pct=str_a_after)
        self._db.update_army_fields(army_b_id, strength_pct=str_b_after)
        self._db.update_battle_fields(battle_id, last_tick_day=current_day)

        tick = BattleTick(
            battle_id        = battle_id,
            province_id      = battle["province_id"],
            army_a_id        = army_a_id,
            army_b_id        = army_b_id,
            power_a          = power_a,
            power_b          = power_b,
            damage_to_a      = damage_a,
            damage_to_b      = damage_b,
            strength_a_after = str_a_after,
            strength_b_after = str_b_after,
        )

        # Check retreats / destruction
        war  = self._db.get_war(battle["war_id"])

        self._check_retreat_or_destroy(
            tick, battle, war, army_a_id, row_a, str_a_after,
            server_id, scenario_id, current_day, side="a"
        )
        self._check_retreat_or_destroy(
            tick, battle, war, army_b_id, row_b, str_b_after,
            server_id, scenario_id, current_day, side="b"
        )

        # Determine battle winner if it ended
        if tick.a_destroyed or tick.a_retreated:
            tick.winner_army_id = army_b_id
        elif tick.b_destroyed or tick.b_retreated:
            tick.winner_army_id = army_a_id

        if tick.winner_army_id:
            self._db.update_battle_fields(
                battle_id,
                status="resolved",
                winner_army_id=tick.winner_army_id,
            )
            winner_row = self._db.get_army(tick.winner_army_id)
            loser_id   = army_b_id if tick.winner_army_id == army_a_id else army_a_id
            loser_row  = self._db.get_army(loser_id)

            if winner_row and loser_row and war:
                winner_country = winner_row["country_id"]
                beneficiary = (
                    "attacker" if winner_country == war["attacker"] else "defender"
                )
                self._war.add_war_score(battle["war_id"], "battle_win", beneficiary)

            # Release non-destroyed winner from combat
            if winner_row and winner_row["state"] == "in_combat":
                self._db.update_army_fields(tick.winner_army_id, state="idle")

        tick.message = self._build_tick_message(tick)
        return tick

    def process_all_battles(
        self,
        server_id:   str,
        scenario_id: str,
        current_day: int,
    ) -> BattleProcessResult:
        """Process all active battles in the scenario."""
        active = self._db.get_active_battles(server_id, scenario_id)
        result = BattleProcessResult(battles_ticked=0)
        for b in active:
            tick = self.resolve_battle_tick(
                b["battle_id"], server_id, scenario_id, current_day
            )
            if tick is not None:
                result.events.append(tick)
                result.battles_ticked += 1
        return result

    def get_active_battles(
        self, server_id: str, scenario_id: str
    ) -> list[dict]:
        return self._db.get_active_battles(server_id, scenario_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _auto_resolve(
        self,
        battle:      dict,
        server_id:   str,
        scenario_id: str,
        current_day: int,
    ) -> BattleTick:
        """
        Auto-resolve a battle that has exceeded MAX_BATTLE_DURATION_DAYS.
        Winner is the side with higher remaining strength; tie goes to army_a.
        """
        army_a_id = battle["army_a_id"]
        army_b_id = battle["army_b_id"]
        row_a = self._db.get_army(army_a_id)
        row_b = self._db.get_army(army_b_id)

        str_a = float(row_a["strength_pct"]) if row_a else 0.0
        str_b = float(row_b["strength_pct"]) if row_b else 0.0

        tick = BattleTick(
            battle_id        = battle["battle_id"],
            province_id      = battle["province_id"],
            army_a_id        = army_a_id,
            army_b_id        = army_b_id,
            power_a          = 0.0,
            power_b          = 0.0,
            damage_to_a      = 0.0,
            damage_to_b      = 0.0,
            strength_a_after = str_a,
            strength_b_after = str_b,
        )

        # Determine winner by strength
        if str_a >= str_b:
            tick.winner_army_id = army_a_id
            tick.b_retreated    = True
            if row_b:
                self._army.retreat_army(army_b_id, server_id, scenario_id, current_day)
        else:
            tick.winner_army_id = army_b_id
            tick.a_retreated    = True
            if row_a:
                self._army.retreat_army(army_a_id, server_id, scenario_id, current_day)

        self._db.update_battle_fields(
            battle["battle_id"],
            status="resolved",
            winner_army_id=tick.winner_army_id,
            last_tick_day=current_day,
        )

        war = self._db.get_war(battle["war_id"])
        winner_row = self._db.get_army(tick.winner_army_id)
        if winner_row and war:
            beneficiary = (
                "attacker"
                if winner_row["country_id"] == war["attacker"]
                else "defender"
            )
            self._war.add_war_score(battle["war_id"], "battle_win", beneficiary)

        if winner_row and winner_row["state"] == "in_combat":
            self._db.update_army_fields(tick.winner_army_id, state="idle")

        tick.message = (
            f"Battle auto-resolved after {MAX_BATTLE_DURATION_DAYS} days: "
            f"army '{tick.winner_army_id}' wins by strength "
            f"({str_a:.1f}% vs {str_b:.1f}%)."
        )
        return tick

    def _check_retreat_or_destroy(
        self,
        tick:        BattleTick,
        battle:      dict,
        war:         dict | None,
        army_id:     str,
        army_row:    dict,
        new_strength: float,
        server_id:   str,
        scenario_id: str,
        current_day: int,
        side:        str,  # "a" or "b"
    ) -> None:
        if new_strength > RETREAT_THRESHOLD:
            return

        other_army_id = battle["army_b_id"] if side == "a" else battle["army_a_id"]
        other_row     = self._db.get_army(other_army_id)

        if army_row["state"] == "retreating":
            # Already retreating → destroy
            self._army.destroy_army(army_id)
            if side == "a":
                tick.a_destroyed = True
            else:
                tick.b_destroyed = True

            # Award army_destroyed war score
            if other_row and war:
                beneficiary = (
                    "attacker"
                    if other_row["country_id"] == war["attacker"]
                    else "defender"
                )
                self._war.add_war_score(
                    battle["war_id"], "army_destroyed", beneficiary
                )
        else:
            # Retreat to base
            self._army.retreat_army(army_id, server_id, scenario_id, current_day)
            if side == "a":
                tick.a_retreated = True
            else:
                tick.b_retreated = True

    def _award_destroy_war_score(
        self,
        war_id:         str,
        winner_country: str,
        loser_country:  str,
    ) -> None:
        war = self._db.get_war(war_id)
        if war is None:
            return
        beneficiary = (
            "attacker" if winner_country == war["attacker"] else "defender"
        )
        self._war.add_war_score(war_id, "army_destroyed", beneficiary)

    def _build_tick_message(self, tick: BattleTick) -> str:
        parts = [
            f"Battle '{tick.battle_id}': "
            f"army_a str={tick.strength_a_after:.1f}%, "
            f"army_b str={tick.strength_b_after:.1f}%."
        ]
        if tick.a_retreated:
            parts.append(f"Army A retreated.")
        if tick.b_retreated:
            parts.append(f"Army B retreated.")
        if tick.a_destroyed:
            parts.append(f"Army A DESTROYED (+10 war score).")
        if tick.b_destroyed:
            parts.append(f"Army B DESTROYED (+10 war score).")
        if tick.winner_army_id:
            parts.append(f"Battle won by army '{tick.winner_army_id}' (+5 war score).")
        return " ".join(parts)
