#!/usr/bin/env python3
"""
services/l7-kg/bdi_engine.py

Phase 13a: Adversarial BDI Core — MMOG-NPC Architecture

Purpose: Belief-Desire-Intention reasoning for ABDT agents.
Treats each agent as an autonomous "player" in a national-scale MMOG,
where the environment (SUMO/Flecs) is the physics engine and BDI is the
AI controller.

Architecture:
- Beliefs: Updated from AggregatedObservation (Kafka)
- Desires: Generated from TCO gap, pressure, equity, habit resistance
- Intentions: Selected via Schmitt Trigger with hysteresis (prevents flip-flop)
- Habit Resistance: Exponential decay based on years_in_service
- Action Emission: Kafka → ActionDispatcher → ZMQ → Engine/SUMO

MMOG Patterns:
- Interest Management: Only reason about agents in active corridors
- LOD (Level of Detail): BDI runs at 1Hz (coarse), reflexive at 100Hz (fine)
- Delta Compression: Observations already aggregated 100:1 by StateAggregator
"""
import json
import math
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable

# =============================================================================
# Configuration
# =============================================================================

SCHMITT_THRESHOLD_ON = 5000.0       # GBP: TCO gap must exceed this to switch ON
SCHMITT_THRESHOLD_OFF = -2000.0   # GBP: TCO gap must drop below this to switch OFF
SCHMITT_HYSTERESIS = 1000.0         # GBP: dead zone between on/off
HABIT_DECAY_LAMBDA = 0.15           # Exponential decay constant (higher = faster decay)
INTENTION_TTL_MS = 300_000          # 5 minutes before intention expires
COALITION_COOLDOWN_MS = 600_000    # 10 minutes between coalition attempts

# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class Belief:
    """Agent's internal model of the world."""
    tco_gap: float = 0.0                    # Green-to-Grey price gap (GBP)
    adversarial_pressure: float = 0.0       # Normalized 0-100
    infrastructure_readiness: float = 0.0   # Charging/grid availability 0-1
    policy_favorability: float = 0.0        # -1 (hostile) to +1 (favorable)
    equity_exposure: float = 0.0            # Deprivation index impact
    social_influence: float = 0.0           # Neighbor adoption rate 0-1
    last_updated_ms: int = 0

    def confidence(self) -> float:
        """Belief confidence decays with age."""
        age_sec = (int(time.time() * 1000) - self.last_updated_ms) / 1000.0
        return max(0.0, 1.0 - (age_sec / 3600.0))  # 1 hour half-life


@dataclass
class Desire:
    """Something the agent wants to achieve."""
    desire_id: str = ""
    desire_type: str = ""                 # mode_switch, route_change, coalition, maintain
    target: Dict[str, Any] = field(default_factory=dict)
    urgency: float = 0.0                    # 0-1, higher = more urgent
    formed_at_ms: int = 0


@dataclass
class Intention:
    """Committed plan to satisfy a desire."""
    intention_id: str = ""
    desire_type: str = ""
    action_type: str = ""                   # mode_switch, route_change, etc.
    payload: Dict[str, Any] = field(default_factory=dict)
    committed_at_ms: int = 0
    deadline_ms: int = 0
    urgency: float = 0.0                    # carried from desire
    status: str = "active"                  # active, completed, failed, aborted


@dataclass
class HabitProfile:
    """Habit resistance modeled as exponential decay."""
    years_in_service: float = 0.0
    baseline_resistance: float = 1.0        # Max resistance at t=0

    def current_resistance(self) -> float:
        """Resistance decays as agent ages with current mode."""
        return self.baseline_resistance * math.exp(-HABIT_DECAY_LAMBDA * self.years_in_service)

    def effective_threshold(self, base_threshold: float) -> float:
        """Threshold is harder to cross when habit resistance is high."""
        return base_threshold * (1.0 + self.current_resistance())


class SchmittTrigger:
    """
    Hysteresis comparator to prevent mode flip-flopping.
    MMOG analogy: "sticky" state changes like aggro toggles in NPCs.
    """
    def __init__(self, threshold_on: float, threshold_off: float, hysteresis: float):
        self.threshold_on = threshold_on
        self.threshold_off = threshold_off
        self.hysteresis = hysteresis
        self.state = False  # Current committed state
        self.last_input = 0.0

    def evaluate(self, value: float) -> bool:
        self.last_input = value
        if not self.state and value > (self.threshold_on + self.hysteresis):
            self.state = True
        elif self.state and value < (self.threshold_off - self.hysteresis):
            self.state = False
        return self.state

    def __repr__(self) -> str:
        return f"SchmittTrigger(state={self.state}, last={self.last_input:.0f})"


# =============================================================================
# BDI Engine
# =============================================================================

class BDIEngine:
    """
    Per-agent BDI loop. Stateless across agents — can be sharded by agent_id.
    MMOG analogy: This is the "AI Controller" for each NPC/player.
    """

    def __init__(self, agent_id: str, corridor_id: str = "national"):
        self.agent_id = agent_id
        self.corridor_id = corridor_id

        # BDI state
        self.beliefs = Belief()
        self.desires: List[Desire] = []
        self.intention: Optional[Intention] = None
        self.habit = HabitProfile()

        # Schmitt triggers for mode switching (one per transition direction)
        self.mode_trigger = SchmittTrigger(
            threshold_on=SCHMITT_THRESHOLD_ON,
            threshold_off=SCHMITT_THRESHOLD_OFF,
            hysteresis=SCHMITT_HYSTERESIS
        )

        # Coalition state
        self.last_coalition_attempt_ms = 0
        self.coalition_id: Optional[str] = None

        # Callbacks for action emission
        self.action_emitters: List[Callable] = []
        self.lock = threading.RLock()

    # -------------------------------------------------------------------------
    # Belief Update (from AggregatedObservation)
    # -------------------------------------------------------------------------

    def update_beliefs(self, observation: Dict[str, Any]) -> None:
        """
        Update beliefs from StateAggregator observation envelope.
        observation = envelope['payload'] (the AggregatedObservation dict)
        """
        with self.lock:
            payload = observation
            now_ms = int(time.time() * 1000)

            # TCO gap from ABDT cache or compute from payload
            tco_model = payload.get("tco_model", {})
            self.beliefs.tco_gap = tco_model.get("green_grey_gap", 0.0)

            # Pressure from observation
            self.beliefs.adversarial_pressure = payload.get("pressure_end", 0.0)

            # Infrastructure readiness heuristic
            energy_end = payload.get("energy_pct_end", 100.0)
            self.beliefs.infrastructure_readiness = (100.0 - energy_end) / 100.0

            # Policy favorability from ToC severity
            toc_severity = payload.get("toc_severity", 0.0)
            self.beliefs.policy_favorability = -toc_severity  # High severity = hostile policy

            # Equity exposure
            self.beliefs.equity_exposure = payload.get("equity_exposure", 0.0)

            # Social influence from mindset shifts in corridor
            self.beliefs.social_influence = min(1.0, payload.get("mindset_shift_count", 0) / 5.0)

            self.beliefs.last_updated_ms = now_ms

            print(f"[BDI] {self.agent_id}: beliefs updated "
                  f"(tco_gap={self.beliefs.tco_gap:.0f}, pressure={self.beliefs.adversarial_pressure:.1f})")

    # -------------------------------------------------------------------------
    # Desire Formation
    # -------------------------------------------------------------------------

    def generate_desires(self) -> List[Desire]:
        """
        Generate desires based on current beliefs.
        MMOG analogy: NPC "aggro check" — evaluate threats/opportunities.
        """
        with self.lock:
            desires = []
            now_ms = int(time.time() * 1000)
            b = self.beliefs

            # Desire 1: Mode Switch (primary decarbonization driver)
            effective_on = self.habit.effective_threshold(self.mode_trigger.threshold_on)
            effective_off = self.habit.effective_threshold(self.mode_trigger.threshold_off)

            if b.tco_gap > effective_on and b.infrastructure_readiness > 0.3:
                desires.append(Desire(
                    desire_id=f"d-mode-switch-{now_ms}",
                    desire_type="mode_switch",
                    target={"target_mode": "BEV", "reason": "TCO gap positive"},
                    urgency=min(1.0, b.tco_gap / 20000.0),
                    formed_at_ms=now_ms
                ))
            elif b.tco_gap < effective_off and b.infrastructure_readiness > 0.3:
                desires.append(Desire(
                    desire_id=f"d-mode-switch-{now_ms}",
                    desire_type="mode_switch",
                    target={"target_mode": "ICE", "reason": "TCO gap negative"},
                    urgency=min(1.0, abs(b.tco_gap) / 20000.0),
                    formed_at_ms=now_ms
                ))

            # Desire 2: Route Change (pressure avoidance)
            if b.adversarial_pressure > 70.0:
                desires.append(Desire(
                    desire_id=f"d-route-change-{now_ms}",
                    desire_type="route_change",
                    target={"reason": "pressure_avoidance", "pressure": b.adversarial_pressure},
                    urgency=b.adversarial_pressure / 100.0,
                    formed_at_ms=now_ms
                ))

            # Desire 3: Coalition Formation (social influence + TCO)
            if (b.social_influence > 0.4 and b.tco_gap > effective_on * 0.5 and 
                now_ms - self.last_coalition_attempt_ms > COALITION_COOLDOWN_MS):
                desires.append(Desire(
                    desire_id=f"d-coalition-{now_ms}",
                    desire_type="coalition",
                    target={"corridor_id": self.corridor_id, "tco_gap": b.tco_gap},
                    urgency=b.social_influence * 0.7,
                    formed_at_ms=now_ms
                ))

            # Desire 4: Maintain (default, low urgency)
            if not desires:
                desires.append(Desire(
                    desire_id=f"d-maintain-{now_ms}",
                    desire_type="maintain",
                    target={"current_mode": "current"},
                    urgency=0.1,
                    formed_at_ms=now_ms
                ))

            self.desires = desires
            return desires

    # -------------------------------------------------------------------------
    # Intention Selection (Deliberation)
    # -------------------------------------------------------------------------

    def deliberate(self) -> Optional[Intention]:
        """
        Select highest-urgency desire and commit as intention.
        MMOG analogy: NPC "decision tree" — pick best action from available desires.
        """
        with self.lock:
            if not self.desires:
                return None

            # Sort by urgency descending
            self.desires.sort(key=lambda d: d.urgency, reverse=True)
            chosen = self.desires[0]
            now_ms = int(time.time() * 1000)

            # If we already have an active intention, check for override
            if self.intention and self.intention.status == "active":
                if chosen.urgency < 0.8:  # Only override if new desire is critical
                    return self.intention
                else:
                    self.intention.status = "aborted"

            # Commit new intention
            self.intention = Intention(
                intention_id=f"i-{chosen.desire_id}",
                desire_type=chosen.desire_type,
                action_type=chosen.desire_type,
                payload=chosen.target,
                urgency=chosen.urgency,
                committed_at_ms=now_ms,
                deadline_ms=now_ms + INTENTION_TTL_MS,
                status="active"
            )

            print(f"[BDI] {self.agent_id}: INTENTION COMMITTED → {self.intention.action_type} "
                  f"(urgency={chosen.urgency:.2f})")

            return self.intention

    # -------------------------------------------------------------------------
    # Action Execution
    # -------------------------------------------------------------------------

    def execute(self) -> Optional[Dict[str, Any]]:
        """
        Execute current intention, emit action envelope if ready.
        Returns action envelope dict or None.
        """
        with self.lock:
            if not self.intention or self.intention.status != "active":
                return None

            now_ms = int(time.time() * 1000)
            if now_ms > self.intention.deadline_ms:
                self.intention.status = "failed"
                return None

            # Build action envelope
            envelope = {
                "meta": {
                    "schema_version": "ctt-belief-1.0",
                    "domain_id": "ctt-abdt",
                    "corridor_id": self.corridor_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source_host": "bdi-engine",
                    "priority": "POLICY" if self.intention.urgency > 0.8 else "TACTICAL"
                },
                "payload": {
                    "agent_id": self.agent_id,
                    "action_type": self.intention.action_type,
                    **self.intention.payload
                },
                "provenance": {
                    "upstream_domains": ["ctt-abdt"],
                    "confidence": self.beliefs.confidence(),
                    "model_version": "ctt-phase13a",
                    "bdi_state": {
                        "tco_gap": self.beliefs.tco_gap,
                        "pressure": self.beliefs.adversarial_pressure,
                        "habit_resistance": self.habit.current_resistance()
                    }
                }
            }

            # Mark intention as completed (one-shot actions)
            self.intention.status = "completed"

            print(f"[BDI] {self.agent_id}: ACTION EMITTED → {self.intention.action_type}")
            return envelope

    # -------------------------------------------------------------------------
    # Full BDI Cycle
    # -------------------------------------------------------------------------

    def cycle(self, observation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Single BDI cycle: Belief → Desire → Intention → Action."""
        self.update_beliefs(observation)
        self.generate_desires()
        self.deliberate()
        return self.execute()

    # -------------------------------------------------------------------------
    # Habit Profile Management
    # -------------------------------------------------------------------------

    def set_habit_profile(self, years_in_service: float, baseline_resistance: float = 1.0) -> None:
        self.habit.years_in_service = years_in_service
        self.habit.baseline_resistance = baseline_resistance

    # -------------------------------------------------------------------------
    # Coalition Hooks
    # -------------------------------------------------------------------------

    def on_coalition_invite(self, coalition_id: str, members: List[str]) -> bool:
        """Evaluate coalition invitation. Returns True if accepted."""
        with self.lock:
            if self.beliefs.tco_gap > 0 and self.beliefs.social_influence > 0.3:
                self.coalition_id = coalition_id
                self.last_coalition_attempt_ms = int(time.time() * 1000)
                return True
            return False


# =============================================================================
# BDI Shard Manager (MMOG Zone Pattern)
# =============================================================================

class BDIShardManager:
    """
    Manages BDI engines sharded by agent_id.
    MMOG analogy: "Zone server" managing NPCs in one corridor.
    """

    def __init__(self, corridor_id: str = "national"):
        self.corridor_id = corridor_id
        self.engines: Dict[str, BDIEngine] = {}
        self.lock = threading.RLock()

    def get_or_create(self, agent_id: str) -> BDIEngine:
        with self.lock:
            if agent_id not in self.engines:
                self.engines[agent_id] = BDIEngine(agent_id, self.corridor_id)
            return self.engines[agent_id]

    def cycle_all(self, observations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Run BDI cycle for all agents with observations."""
        actions = []
        for obs in observations:
            agent_id = obs.get("agent_id", "unknown")
            engine = self.get_or_create(agent_id)
            action = engine.cycle(obs)
            if action:
                actions.append(action)
        return actions

    def get_agent_state(self, agent_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            if agent_id not in self.engines:
                return None
            e = self.engines[agent_id]
            return {
                "agent_id": agent_id,
                "beliefs": {
                    "tco_gap": e.beliefs.tco_gap,
                    "pressure": e.beliefs.adversarial_pressure,
                    "infrastructure": e.beliefs.infrastructure_readiness,
                    "confidence": e.beliefs.confidence()
                },
                "intention": {
                    "type": e.intention.action_type if e.intention else None,
                    "status": e.intention.status if e.intention else None
                },
                "habit_resistance": e.habit.current_resistance(),
                "schmitt_state": e.mode_trigger.state
            }


if __name__ == "__main__":
    # Quick sanity test
    engine = BDIEngine("Test_Agent_001", "a20_charging")
    engine.set_habit_profile(years_in_service=2.5)

    obs = {
        "agent_id": "Test_Agent_001",
        "tco_model": {"green_grey_gap": 8000.0},
        "pressure_end": 45.0,
        "energy_pct_end": 65.0,
        "toc_severity": 0.2,
        "equity_exposure": 0.3,
        "mindset_shift_count": 2
    }

    action = engine.cycle(obs)
    print("\n" + "="*60)
    print("BDI SANITY TEST")
    print("="*60)
    print(f"Action emitted: {action is not None}")
    if action:
        print(f"Action type: {action['payload']['action_type']}")
        print(f"Target mode: {action['payload'].get('target_mode')}")
    print(f"Habit resistance: {engine.habit.current_resistance():.3f}")
    print(f"Schmitt state: {engine.mode_trigger.state}")
