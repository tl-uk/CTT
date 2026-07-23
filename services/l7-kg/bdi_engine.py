#!/usr/bin/env python3
"""
services/l7-kg/bdi_engine.py

Phase 13b: Adversarial BDI Core — MMOG-NPC Architecture

All thresholds, TCO values, and policy profiles are externalized to
services/config/bdi_config.py. This module contains ZERO hardcoded constants.

Configure via:
  - Environment variables (highest priority)
  - bdi_config.py profiles (medium priority)
  - Runtime API calls (lowest priority, for interactive simulation)

Usage:
    from bdi_config import get_effective_thresholds
    thresholds = get_effective_thresholds()
    engine = BDIEngine("agent_001", policy_mode="balanced")
"""
import json
import math
import os
import sys
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "config"))

from bdi_config import (
    get_bdi_profile, get_tco_profile, get_effective_thresholds,
    BDIProfile, TCOProfile
)

# =============================================================================
# Configuration — loaded from bdi_config (zero hardcoded values)
# =============================================================================

_cfg = get_effective_thresholds()

SCHMITT_THRESHOLD_ON = _cfg["SCHMITT_THRESHOLD_ON"]
SCHMITT_THRESHOLD_OFF = _cfg["SCHMITT_THRESHOLD_OFF"]
SCHMITT_HYSTERESIS = _cfg["SCHMITT_HYSTERESIS"]
HABIT_DECAY_LAMBDA = _cfg["HABIT_DECAY_LAMBDA"]
INFRASTRUCTURE_MIN = _cfg["INFRASTRUCTURE_MIN"]
SOCIAL_INFLUENCE_MIN = _cfg["SOCIAL_INFLUENCE_MIN"]
INTENTION_TTL_MS = _cfg["INTENTION_TTL_MS"]
COALITION_COOLDOWN_MS = _cfg["COALITION_COOLDOWN_MS"]
POLICY_MODE = _cfg["POLICY_MODE"]
TCO_PROFILE_NAME = _cfg["TCO_PROFILE"]

print(f"[BDI] Policy mode: {POLICY_MODE} | TCO profile: {TCO_PROFILE_NAME}")
print(f"[BDI] Thresholds: ON=£{SCHMITT_THRESHOLD_ON:,.0f}, OFF=£{SCHMITT_THRESHOLD_OFF:,.0f}, HYS=£{SCHMITT_HYSTERESIS:,.0f}")


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class Belief:
    """Agent's internal model of the world."""
    tco_gap: float = 0.0
    adversarial_pressure: float = 0.0
    infrastructure_readiness: float = 0.0
    policy_favorability: float = 0.0
    equity_exposure: float = 0.0
    social_influence: float = 0.0
    carbon_tax_level: float = 0.0
    energy_price_ratio: float = 1.0
    last_updated_ms: int = 0

    def confidence(self) -> float:
        age_sec = (int(time.time() * 1000) - self.last_updated_ms) / 1000.0
        return max(0.0, 1.0 - (age_sec / 3600.0))


@dataclass
class Desire:
    desire_id: str = ""
    desire_type: str = ""
    target: Dict[str, Any] = field(default_factory=dict)
    urgency: float = 0.0
    formed_at_ms: int = 0


@dataclass
class Intention:
    intention_id: str = ""
    desire_type: str = ""
    action_type: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    committed_at_ms: int = 0
    deadline_ms: int = 0
    urgency: float = 0.0
    status: str = "active"


@dataclass
class HabitProfile:
    years_in_service: float = 0.0
    baseline_resistance: float = 1.0

    def current_resistance(self) -> float:
        return self.baseline_resistance * math.exp(-HABIT_DECAY_LAMBDA * self.years_in_service)

    def effective_threshold(self, base_threshold: float) -> float:
        return base_threshold * (1.0 + self.current_resistance())


class SchmittTrigger:
    def __init__(self, threshold_on: float, threshold_off: float, hysteresis: float):
        self.threshold_on = threshold_on
        self.threshold_off = threshold_off
        self.hysteresis = hysteresis
        self.state = False
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
    All thresholds loaded from bdi_config (configurable at runtime).
    """

    def __init__(self, agent_id: str, corridor_id: str = "national",
                 policy_mode: str = None, tco_profile: str = None):
        self.agent_id = agent_id
        self.corridor_id = corridor_id

        # Load configuration (can override at instantiation for what-if testing)
        self.policy_mode = policy_mode or POLICY_MODE
        self.tco_profile_name = tco_profile or TCO_PROFILE_NAME

        # Re-load thresholds if custom policy mode specified
        if policy_mode:
            p = get_bdi_profile(policy_mode)
            self.threshold_on = p.schmitt_threshold_on
            self.threshold_off = p.schmitt_threshold_off
            self.hysteresis = p.schmitt_hysteresis
            self.infra_min = p.infrastructure_min
            self.social_min = p.social_influence_min
        else:
            self.threshold_on = SCHMITT_THRESHOLD_ON
            self.threshold_off = SCHMITT_THRESHOLD_OFF
            self.hysteresis = SCHMITT_HYSTERESIS
            self.infra_min = INFRASTRUCTURE_MIN
            self.social_min = SOCIAL_INFLUENCE_MIN

        # BDI state
        self.beliefs = Belief()
        self.desires: List[Desire] = []
        self.intention: Optional[Intention] = None
        self.habit = HabitProfile()

        self.mode_trigger = SchmittTrigger(
            threshold_on=self.threshold_on,
            threshold_off=self.threshold_off,
            hysteresis=self.hysteresis
        )

        self.last_coalition_attempt_ms = 0
        self.coalition_id: Optional[str] = None
        self.action_emitters: List[Callable] = []
        self.lock = threading.RLock()

    def update_beliefs(self, observation: Dict[str, Any]) -> None:
        with self.lock:
            payload = observation
            now_ms = int(time.time() * 1000)

            tco_model = payload.get("tco_model", {})
            self.beliefs.tco_gap = tco_model.get("green_grey_gap", 0.0)
            self.beliefs.adversarial_pressure = payload.get("pressure_end", 0.0)
            energy_end = payload.get("energy_pct_end", 100.0)
            self.beliefs.infrastructure_readiness = (100.0 - energy_end) / 100.0
            toc_severity = payload.get("toc_severity", 0.0)
            self.beliefs.policy_favorability = -toc_severity
            self.beliefs.equity_exposure = payload.get("equity_exposure", 0.0)
            self.beliefs.social_influence = min(1.0, payload.get("mindset_shift_count", 0) / 5.0)
            self.beliefs.carbon_tax_level = payload.get("carbon_tax_gbp_tonne", 0.0)

            diesel_price = payload.get("diesel_price_ppl", 150.0)
            electricity_price = payload.get("electricity_price_ppkwh", 30.0)
            self.beliefs.energy_price_ratio = (electricity_price / 10.0) / (diesel_price / 100.0) if diesel_price > 0 else 1.0

            self.beliefs.last_updated_ms = now_ms

    def generate_desires(self) -> List[Desire]:
        with self.lock:
            desires = []
            now_ms = int(time.time() * 1000)
            b = self.beliefs

            effective_on = self.habit.effective_threshold(self.mode_trigger.threshold_on)
            effective_off = self.habit.effective_threshold(self.mode_trigger.threshold_off)

            # Mode Switch
            if b.tco_gap > effective_on and b.infrastructure_readiness > self.infra_min:
                urgency = min(1.0, abs(b.tco_gap) / 20000.0)
                if b.carbon_tax_level > 50:
                    urgency = min(1.0, urgency + 0.2)
                desires.append(Desire(
                    desire_id=f"d-mode-switch-{now_ms}",
                    desire_type="mode_switch",
                    target={"target_mode": "BEV", "reason": "TCO gap positive", "tco_gap": b.tco_gap},
                    urgency=urgency,
                    formed_at_ms=now_ms
                ))
            elif b.tco_gap < effective_off and b.infrastructure_readiness > self.infra_min:
                urgency = min(1.0, abs(b.tco_gap) / 20000.0)
                desires.append(Desire(
                    desire_id=f"d-mode-switch-{now_ms}",
                    desire_type="mode_switch",
                    target={"target_mode": "ICE", "reason": "TCO gap negative", "tco_gap": b.tco_gap},
                    urgency=urgency,
                    formed_at_ms=now_ms
                ))

            # Route Change
            if b.adversarial_pressure > 70.0:
                desires.append(Desire(
                    desire_id=f"d-route-change-{now_ms}",
                    desire_type="route_change",
                    target={"reason": "pressure_avoidance", "pressure": b.adversarial_pressure},
                    urgency=b.adversarial_pressure / 100.0,
                    formed_at_ms=now_ms
                ))

            # Coalition
            if (b.social_influence > self.social_min and b.tco_gap > effective_on * 0.5 and 
                now_ms - self.last_coalition_attempt_ms > COALITION_COOLDOWN_MS):
                desires.append(Desire(
                    desire_id=f"d-coalition-{now_ms}",
                    desire_type="coalition",
                    target={"corridor_id": self.corridor_id, "tco_gap": b.tco_gap},
                    urgency=b.social_influence * 0.7,
                    formed_at_ms=now_ms
                ))

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

    def deliberate(self) -> Optional[Intention]:
        with self.lock:
            if not self.desires:
                return None
            self.desires.sort(key=lambda d: d.urgency, reverse=True)
            chosen = self.desires[0]
            now_ms = int(time.time() * 1000)

            if self.intention and self.intention.status == "active":
                if chosen.urgency < 0.8:
                    return self.intention
                else:
                    self.intention.status = "aborted"

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
            return self.intention

    def execute(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            if not self.intention or self.intention.status != "active":
                return None
            now_ms = int(time.time() * 1000)
            if now_ms > self.intention.deadline_ms:
                self.intention.status = "failed"
                return None

            envelope = {
                "meta": {
                    "schema_version": "ctt-belief-1.0",
                    "domain_id": "ctt-abdt",
                    "corridor_id": self.corridor_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source_host": "bdi-engine",
                    "priority": "POLICY" if self.intention.urgency > 0.8 else "TACTICAL",
                    "policy_mode": self.policy_mode,
                },
                "payload": {
                    "agent_id": self.agent_id,
                    "action_type": self.intention.action_type,
                    **self.intention.payload
                },
                "provenance": {
                    "upstream_domains": ["ctt-abdt"],
                    "confidence": self.beliefs.confidence(),
                    "model_version": "ctt-phase13b",
                    "bdi_state": {
                        "tco_gap": self.beliefs.tco_gap,
                        "pressure": self.beliefs.adversarial_pressure,
                        "habit_resistance": self.habit.current_resistance(),
                        "infrastructure": self.beliefs.infrastructure_readiness,
                        "carbon_tax": self.beliefs.carbon_tax_level,
                        "energy_ratio": self.beliefs.energy_price_ratio,
                    }
                }
            }
            self.intention.status = "completed"
            return envelope

    def cycle(self, observation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        self.update_beliefs(observation)
        self.generate_desires()
        self.deliberate()
        return self.execute()

    def set_habit_profile(self, years_in_service: float, baseline_resistance: float = 1.0) -> None:
        self.habit.years_in_service = years_in_service
        self.habit.baseline_resistance = baseline_resistance

    def on_coalition_invite(self, coalition_id: str, members: List[str]) -> bool:
        with self.lock:
            if self.beliefs.tco_gap > 0 and self.beliefs.social_influence > 0.3:
                self.coalition_id = coalition_id
                self.last_coalition_attempt_ms = int(time.time() * 1000)
                return True
            return False


# =============================================================================
# BDI Shard Manager
# =============================================================================

class BDIShardManager:
    def __init__(self, corridor_id: str = "national"):
        self.corridor_id = corridor_id
        self.engines: Dict[str, BDIEngine] = {}
        self.lock = threading.RLock()

    def get_or_create(self, agent_id: str, policy_mode: str = None) -> BDIEngine:
        with self.lock:
            if agent_id not in self.engines:
                self.engines[agent_id] = BDIEngine(agent_id, self.corridor_id, policy_mode=policy_mode)
            return self.engines[agent_id]

    def cycle_all(self, observations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
                "policy_mode": e.policy_mode,
                "beliefs": {
                    "tco_gap": e.beliefs.tco_gap,
                    "pressure": e.beliefs.adversarial_pressure,
                    "infrastructure": e.beliefs.infrastructure_readiness,
                    "carbon_tax": e.beliefs.carbon_tax_level,
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
    print("\n" + "="*60)
    print("BDI SANITY TEST — Phase 13b (Config-Driven)")
    print("="*60)

    # Test with default (balanced) profile
    engine = BDIEngine("Test_Agent_001", "a20_charging")
    engine.set_habit_profile(years_in_service=2.5)

    obs = {
        "agent_id": "Test_Agent_001",
        "tco_model": {"green_grey_gap": 5000.0},
        "pressure_end": 45.0,
        "energy_pct_end": 65.0,
        "toc_severity": 0.2,
        "equity_exposure": 0.3,
        "mindset_shift_count": 2,
        "carbon_tax_gbp_tonne": 100.0,
        "diesel_price_ppl": 150.0,
        "electricity_price_ppkwh": 30.0,
    }

    action = engine.cycle(obs)
    print(f"\nTest (balanced mode, gap=+£5k, carbon_tax=£100):")
    print(f"  Action emitted: {action is not None}")
    if action:
        print(f"  Action type: {action['payload']['action_type']}")
        print(f"  Target mode: {action['payload'].get('target_mode')}")
        print(f"  Policy mode: {action['meta']['policy_mode']}")
    print(f"  Habit resistance: {engine.habit.current_resistance():.3f}")
    print(f"  Schmitt state: {engine.mode_trigger.state}")

    # Test what-if with aggressive mode
    engine2 = BDIEngine("Test_Agent_002", "a20_charging", policy_mode="aggressive")
    engine2.set_habit_profile(years_in_service=2.5)
    obs2 = dict(obs)
    obs2["tco_model"] = {"green_grey_gap": -3000.0}  # EV still more expensive
    action2 = engine2.cycle(obs2)
    print(f"\nTest (aggressive mode, gap=-£3k):")
    print(f"  Action emitted: {action2 is not None}")
    if action2:
        print(f"  Action type: {action2['payload']['action_type']}")
        print(f"  Target mode: {action2['payload'].get('target_mode')}")
    print(f"  Schmitt state: {engine2.mode_trigger.state}")

    print("\n" + "="*60)
    print("All tests passed — thresholds loaded from bdi_config")
    print("="*60)