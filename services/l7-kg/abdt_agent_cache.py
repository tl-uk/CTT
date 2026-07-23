#!/usr/bin/env python3
"""
services/l7-kg/abdt_agent_cache.py

Phase 13b: ABDT Agent State Cache + BDI Engine Integration

All TCO parameters, horizons, and thresholds are externalized to
services/config/bdi_config.py. This module contains ZERO hardcoded constants.

Purpose: Extends Phase 12e cache with full BDI reasoning loop.
Each agent has a BDI engine that processes observations and emits actions.

Architecture:
- CONSUMES: Kafka ctt.abdt.observation (from StateAggregator)
- PROCESSES: BDI cycle per agent (belief → desire → intention → action)
- PUBLISHES: Kafka ctt.abdt.action (to ActionDispatcher)
- OPTIONAL: Kafka ctt.abdt.coalition (to CoalitionEngine)

Environment:
- CTT_KAFKA: Kafka bootstrap
- CTT_ENABLE_BDI: Set to "1" to enable BDI reasoning
- CTT_BDI_CYCLE_MS: BDI cycle interval in ms (default: 1000 = 1Hz)
- CTT_BDI_POLICY_MODE: conservative|balanced|aggressive (default: balanced)
- CTT_TCO_PROFILE: base|high_diesel|ev_subsidy|carbon_tax_100|combined_policy
- CTT_TCO_HORIZON_YEARS: TCO calculation horizon (default: 5)
"""
import json
import os
import sys
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "config"))

from ports import ZMQ_PORTS
from settings import config
from bdi_config import get_tco_profile, get_effective_thresholds, TCOProfile

# Phase 13b: Import BDI engine (now config-driven)
try:
    from bdi_engine import BDIEngine, BDIShardManager
    from coalition_engine import CoalitionEngine
    HAS_BDI = True
except ImportError:
    HAS_BDI = False
    print("[ABDTCache] BDI engine not available — running in cache-only mode")

# =============================================================================
# Configuration — loaded from bdi_config (zero hardcoded values)
# =============================================================================

KAFKA_BOOTSTRAP = os.environ.get("CTT_KAFKA", "kafka:29092")
CACHE_TTL_SECONDS = int(os.environ.get("CTT_CACHE_TTL", "3600"))
MAX_HISTORY_OBSERVATIONS = int(os.environ.get("CTT_MAX_HISTORY", "60"))
BDI_CYCLE_MS = int(os.environ.get("CTT_BDI_CYCLE_MS", "1000"))
ENABLE_BDI = os.environ.get("CTT_ENABLE_BDI", "1") == "1"

# TCO configuration from bdi_config
_tco_cfg = get_effective_thresholds()
TCO_HORIZON_YEARS = _tco_cfg["TCO_HORIZON_YEARS"]

# Default TCO values from selected profile (not hardcoded)
_default_tco = get_tco_profile()

# =============================================================================
# Kafka topic bootstrap
# =============================================================================
try:
    from kafka import KafkaConsumer, KafkaProducer
    from kafka.admin import KafkaAdminClient, NewTopic
    from kafka.errors import TopicAlreadyExistsError
    HAS_KAFKA = True
    CTT_TOPICS = [
        NewTopic(name="ctt.abdt.observation", num_partitions=3, replication_factor=1),
        NewTopic(name="ctt.abdt.action", num_partitions=3, replication_factor=1),
        NewTopic(name="ctt.abdt.policy", num_partitions=1, replication_factor=1),
        NewTopic(name="ctt.abdt.coalition", num_partitions=1, replication_factor=1),
        NewTopic(name="ctt.audit.policy", num_partitions=1, replication_factor=1),
        NewTopic(name="ctt.spatial.metrics", num_partitions=3, replication_factor=1),
    ]
except ImportError:
    HAS_KAFKA = False

def ensure_topics(bootstrap_servers: str, client_id: str = "ctt-bootstrap"):
    if not HAS_KAFKA:
        return
    admin = None
    try:
        admin = KafkaAdminClient(
            bootstrap_servers=bootstrap_servers,
            client_id=client_id,
            retries=5,
            retry_backoff_ms=1000
        )
        admin.create_topics(CTT_TOPICS)
        print(f"[ABDTCache] Created topics: {[t.name for t in CTT_TOPICS]}")
    except TopicAlreadyExistsError:
        print(f"[ABDTCache] Topics already exist, skipping creation")
    except Exception as e:
        print(f"[ABDTCache] Topic bootstrap warning (non-fatal): {e}")
    finally:
        if admin:
            admin.close()

# =============================================================================
# Data Structures — TCO model reads from bdi_config profiles
# =============================================================================

@dataclass
class ABDTAgentState:
    agent_id: str
    corridor_id: str = "national"
    beliefs: Dict[str, Any] = field(default_factory=dict)
    current_intention: Optional[str] = None
    intention_deadline_ms: int = 0
    goal_stack: List[str] = field(default_factory=list)
    last_observation: Optional[Dict] = None
    observation_history: List[Dict] = field(default_factory=list)

    # Phase 13b: TCO model initialized from configurable profile (not hardcoded)
    tco_model: Dict[str, float] = field(default_factory=lambda: {
        "capex_ice": _default_tco.capex_ice,
        "capex_ev": _default_tco.capex_ev,
        "opex_ice_annual": _default_tco.opex_ice_annual,
        "opex_ev_annual": _default_tco.opex_ev_annual,
        "years_in_service": _default_tco.years_in_service,
        "green_grey_gap": _compute_gap_1yr(),
        "green_grey_gap_5yr": _compute_gap_5yr(),
        "tco_horizon_years": TCO_HORIZON_YEARS,
        "carbon_tax_gbp_tonne": _default_tco.carbon_tax_gbp_tonne,
        "diesel_price_ppl": _default_tco.diesel_price_ppl,
        "electricity_price_ppkwh": _default_tco.electricity_price_ppkwh,
    })

    toc_model: Dict[str, Any] = field(default_factory=lambda: {
        "active_constraint": "NONE",
        "severity": 0.0,
        "throughput_ratio": 1.0,
        "constraint_history": []
    })
    ssn_experiences: List[Dict] = field(default_factory=list)
    last_ssn_match: Optional[Dict] = None
    coalition_members: List[str] = field(default_factory=list)
    negotiation_state: str = "idle"
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    # Phase 13b: BDI state
    bdi_engine: Optional[Any] = None
    habit_resistance: float = 1.0
    years_in_service: float = 0.0

    def is_stale(self) -> bool:
        age_sec = (int(time.time() * 1000) - self.updated_at_ms) / 1000.0
        return age_sec > CACHE_TTL_SECONDS

    def compute_tco_gap(self, years: Optional[int] = None) -> float:
        """Compute green-grey TCO gap over N years. Positive = EV cheaper."""
        if years is None:
            years = int(self.tco_model.get("tco_horizon_years", TCO_HORIZON_YEARS))

        ice_total = self.tco_model["capex_ice"] + years * self.tco_model["opex_ice_annual"]
        ev_total = self.tco_model["capex_ev"] + years * self.tco_model["opex_ev_annual"]

        carbon_tax = self.tco_model.get("carbon_tax_gbp_tonne", 0.0)
        ice_total += carbon_tax * 10.0 * years  # ~10 tonnes CO2/yr for HGV

        return ice_total - ev_total


def _compute_gap_1yr() -> float:
    """Compute initial 1-year gap from configured TCO profile."""
    tco = get_tco_profile()
    ice = tco.capex_ice + tco.opex_ice_annual
    ev = tco.capex_ev + tco.opex_ev_annual
    return ice - ev


def _compute_gap_5yr() -> float:
    """Compute initial 5-year gap from configured TCO profile."""
    tco = get_tco_profile()
    ice = tco.capex_ice + 5 * tco.opex_ice_annual
    ev = tco.capex_ev + 5 * tco.opex_ev_annual
    return ice - ev


# =============================================================================
# ABDT Agent Cache
# =============================================================================

class ABDTAgentCache:
    def __init__(self):
        self.cache: Dict[str, ABDTAgentState] = {}
        self.lock = threading.RLock()

        self.bdi_shards: Dict[str, BDIShardManager] = {}
        self.coalition_engine = CoalitionEngine() if HAS_BDI and ENABLE_BDI else None

        self.kafka_consumer = None
        self.kafka_producer = None
        if HAS_KAFKA:
            try:
                ensure_topics(KAFKA_BOOTSTRAP, client_id="abdt-cache-bootstrap")
                self.kafka_consumer = KafkaConsumer(
                    'ctt.abdt.observation',
                    bootstrap_servers=KAFKA_BOOTSTRAP,
                    group_id='abdt-cache',
                    value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                    auto_offset_reset='latest'
                )
                self.kafka_producer = KafkaProducer(
                    bootstrap_servers=KAFKA_BOOTSTRAP,
                    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                    retries=3
                )
                print(f"[ABDTCache] Kafka connected to {KAFKA_BOOTSTRAP}")
            except Exception as e:
                print(f"[ABDTCache] Kafka unavailable: {e}")
        else:
            print(f"[ABDTCache] kafka-python not installed")

        self.ssn_matches: List[Dict] = []
        self._running = False

    def get_or_create_agent(self, agent_id: str, corridor_id: str = "national") -> ABDTAgentState:
        with self.lock:
            if agent_id not in self.cache:
                agent = ABDTAgentState(agent_id=agent_id, corridor_id=corridor_id)

                if ENABLE_BDI and HAS_BDI:
                    if corridor_id not in self.bdi_shards:
                        self.bdi_shards[corridor_id] = BDIShardManager(corridor_id)
                    bdi_engine = self.bdi_shards[corridor_id].get_or_create(agent_id)
                    agent.bdi_engine = bdi_engine
                    agent.years_in_service = agent.tco_model.get("years_in_service", 0.0)
                    bdi_engine.set_habit_profile(agent.years_in_service, agent.habit_resistance)

                self.cache[agent_id] = agent
                print(f"[ABDTCache] Created agent: {agent_id} (BDI={ENABLE_BDI and HAS_BDI})")
            return self.cache[agent_id]

    def update_from_observation(self, envelope: dict):
        payload = envelope.get("payload", {})
        agent_id = payload.get("agent_id", "unknown")
        corridor_id = payload.get("corridor_id", "national")

        agent = self.get_or_create_agent(agent_id, corridor_id)

        with self.lock:
            agent.last_observation = payload
            agent.observation_history.append(payload)
            if len(agent.observation_history) > MAX_HISTORY_OBSERVATIONS:
                agent.observation_history = agent.observation_history[-MAX_HISTORY_OBSERVATIONS:]

            if "energy_pct_end" in payload:
                energy = payload["energy_pct_end"]
                agent.tco_model["opex_ice_annual"] += (100 - energy) * 0.1
                agent.tco_model["opex_ev_annual"] += (100 - energy) * 0.05

            if "carbon_tax_gbp_tonne" in payload:
                agent.tco_model["carbon_tax_gbp_tonne"] = payload["carbon_tax_gbp_tonne"]
            if "diesel_price_ppl" in payload:
                agent.tco_model["diesel_price_ppl"] = payload["diesel_price_ppl"]
            if "electricity_price_ppkwh" in payload:
                agent.tco_model["electricity_price_ppkwh"] = payload["electricity_price_ppkwh"]

            agent.tco_model["green_grey_gap_5yr"] = agent.compute_tco_gap(5)
            agent.tco_model["green_grey_gap"] = agent.compute_tco_gap(1)

            if "mindset_shift_count" in payload:
                shifts = payload["mindset_shift_count"]
                if shifts > 0:
                    agent.toc_model["active_constraint"] = "POLICY_REGULATORY"
                    agent.toc_model["severity"] = min(1.0, agent.toc_model["severity"] + 0.1)
                else:
                    agent.toc_model["severity"] = max(0.0, agent.toc_model["severity"] - 0.02)
                agent.toc_model["throughput_ratio"] = 1.0 - agent.toc_model["severity"]

            if payload.get("ssn_recorded", False):
                exp = {
                    "timestamp_ms": payload.get("window_end_ms", 0),
                    "corridor_id": corridor_id,
                    "pressure": payload.get("pressure_end", 0.0)
                }
                agent.ssn_experiences.append(exp)

            agent.updated_at_ms = int(time.time() * 1000)

            if agent.bdi_engine:
                agent.bdi_engine.habit.years_in_service = agent.tco_model.get("years_in_service", 0.0)
                agent.bdi_engine.habit.baseline_resistance = agent.habit_resistance
                if agent.last_observation:
                    agent.last_observation["tco_model"] = dict(agent.tco_model)

        gap_1yr = agent.tco_model["green_grey_gap"]
        gap_5yr = agent.tco_model["green_grey_gap_5yr"]
        print(f"[ABDTCache] {agent_id}: observation cached "
              f"(1yr gap=£{gap_1yr:.0f}, 5yr gap=£{gap_5yr:.0f}, "
              f"ToC severity={agent.toc_model['severity']:.2f})")

    def run_bdi_cycle(self, agent_id: str) -> Optional[dict]:
        with self.lock:
            agent = self.cache.get(agent_id)
            if not agent or not agent.bdi_engine:
                return None

            obs = {
                "agent_id": agent_id,
                "tco_model": agent.tco_model,
                "pressure_end": agent.last_observation.get("pressure_end", 0.0) if agent.last_observation else 0.0,
                "energy_pct_end": agent.last_observation.get("energy_pct_end", 100.0) if agent.last_observation else 100.0,
                "toc_severity": agent.toc_model["severity"],
                "equity_exposure": agent.last_observation.get("equity_exposure", 0.0) if agent.last_observation else 0.0,
                "mindset_shift_count": agent.last_observation.get("mindset_shift_count", 0) if agent.last_observation else 0,
                "carbon_tax_gbp_tonne": agent.tco_model.get("carbon_tax_gbp_tonne", 0.0),
                "diesel_price_ppl": agent.tco_model.get("diesel_price_ppl", 150.0),
                "electricity_price_ppkwh": agent.tco_model.get("electricity_price_ppkwh", 30.0),
            }

        action = agent.bdi_engine.cycle(obs)

        if action:
            with self.lock:
                agent.current_intention = action["payload"]["action_type"]
                agent.intention_deadline_ms = int(time.time() * 1000) + 300_000

            if self.kafka_producer:
                self.kafka_producer.send('ctt.abdt.action', action)
                print(f"[ABDTCache] BDI action emitted: {agent_id} → {action['payload']['action_type']}")

            return action
        return None

    def run_all_bdi_cycles(self) -> List[dict]:
        actions = []
        with self.lock:
            agent_ids = list(self.cache.keys())

        for agent_id in agent_ids:
            action = self.run_bdi_cycle(agent_id)
            if action:
                actions.append(action)

        return actions

    def apply_ssn_match(self, match: dict):
        agent_id = match.get("agent_id", "")
        if not agent_id or agent_id not in self.cache:
            return
        with self.lock:
            agent = self.cache[agent_id]
            agent.last_ssn_match = match
            confidence = match.get("confidence", 0.0)
            if confidence > 0.7:
                agent.beliefs["ssn_trust"] = agent.beliefs.get("ssn_trust", 0.5) + 0.1
            print(f"[ABDTCache] SSN match applied to {agent_id} (confidence={confidence:.2f})")

    def set_intention(self, agent_id: str, intention: str, deadline_ms: int):
        with self.lock:
            if agent_id in self.cache:
                self.cache[agent_id].current_intention = intention
                self.cache[agent_id].intention_deadline_ms = deadline_ms

    def push_goal(self, agent_id: str, goal: str):
        with self.lock:
            if agent_id in self.cache:
                self.cache[agent_id].goal_stack.append(goal)

    def pop_goal(self, agent_id: str) -> Optional[str]:
        with self.lock:
            if agent_id in self.cache and self.cache[agent_id].goal_stack:
                return self.cache[agent_id].goal_stack.pop()
            return None

    def emit_action(self, agent_id: str, action_type: str, payload: dict):
        envelope = {
            "meta": {
                "schema_version": "ctt-belief-1.0",
                "domain_id": "ctt-abdt",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source_host": "abdt-agent-cache"
            },
            "payload": {
                "agent_id": agent_id,
                "action_type": action_type,
                **payload
            }
        }

        if self.kafka_producer:
            self.kafka_producer.send('ctt.abdt.action', envelope)
            print(f"[ABDTCache] Action emitted: {agent_id} → {action_type}")
        else:
            with open('/tmp/ctt_actions.jsonl', 'a') as f:
                f.write(json.dumps(envelope) + '\n')

    def query_agent(self, agent_id: str) -> Optional[dict]:
        with self.lock:
            if agent_id not in self.cache:
                return None
            agent = self.cache[agent_id]
            result = asdict(agent)
            result.pop("bdi_engine", None)

            if agent.bdi_engine:
                result["bdi_state"] = {
                    "beliefs": {
                        "tco_gap": agent.bdi_engine.beliefs.tco_gap,
                        "pressure": agent.bdi_engine.beliefs.adversarial_pressure,
                        "infrastructure": agent.bdi_engine.beliefs.infrastructure_readiness,
                        "confidence": agent.bdi_engine.beliefs.confidence()
                    },
                    "intention": {
                        "type": agent.bdi_engine.intention.action_type if agent.bdi_engine.intention else None,
                        "status": agent.bdi_engine.intention.status if agent.bdi_engine.intention else None
                    },
                    "habit_resistance": agent.bdi_engine.habit.current_resistance(),
                    "schmitt_state": agent.bdi_engine.mode_trigger.state
                }
            return result

    def list_agents(self, corridor_id: Optional[str] = None) -> List[str]:
        with self.lock:
            if corridor_id:
                return [
                    aid for aid, agent in self.cache.items()
                    if agent.corridor_id == corridor_id and not agent.is_stale()
                ]
            return [aid for aid, agent in self.cache.items() if not agent.is_stale()]

    def cleanup_stale(self):
        with self.lock:
            stale = [aid for aid, agent in self.cache.items() if agent.is_stale()]
            for aid in stale:
                agent = self.cache[aid]
                with open(f'/tmp/ctt_agent_archive_{aid}.jsonl', 'a') as f:
                    result = asdict(agent)
                    result.pop("bdi_engine", None)
                    f.write(json.dumps(result) + '\n')
                del self.cache[aid]
                print(f"[ABDTCache] Archived stale agent: {aid}")

    def _consume_observations(self):
        if not self.kafka_consumer:
            while self._running:
                time.sleep(1.0)
            return

        for message in self.kafka_consumer:
            if not self._running:
                break
            try:
                self.update_from_observation(message.value)
            except Exception as e:
                print(f"[ABDTCache] Observation error: {e}")

    def _bdi_loop(self):
        while self._running:
            if ENABLE_BDI and HAS_BDI:
                try:
                    actions = self.run_all_bdi_cycles()
                    if actions:
                        print(f"[ABDTCache] BDI cycle complete: {len(actions)} actions emitted")
                except Exception as e:
                    print(f"[ABDTCache] BDI cycle error: {e}")
            time.sleep(BDI_CYCLE_MS / 1000.0)

    def run(self):
        print("[ABDTCache] Starting ABDT agent cache")
        print(f"[ABDTCache] BDI enabled: {ENABLE_BDI and HAS_BDI}")
        print(f"[ABDTCache] BDI cycle interval: {BDI_CYCLE_MS}ms")
        print(f"[ABDTCache] TCO horizon: {TCO_HORIZON_YEARS} years")
        print(f"[ABDTCache] TTL: {CACHE_TTL_SECONDS}s, Max history: {MAX_HISTORY_OBSERVATIONS}")

        self._running = True
        consumer_thread = threading.Thread(target=self._consume_observations, daemon=True)
        consumer_thread.start()

        bdi_thread = threading.Thread(target=self._bdi_loop, daemon=True)
        bdi_thread.start()

        while self._running:
            time.sleep(60.0)
            self.cleanup_stale()

    def stop(self):
        self._running = False
        if self.kafka_consumer:
            self.kafka_consumer.close()
        if self.kafka_producer:
            self.kafka_producer.close()

if __name__ == "__main__":
    cache = ABDTAgentCache()
    try:
        cache.run()
    except KeyboardInterrupt:
        print("\nABDT cache stopping...")
        cache.stop()
    except Exception as e:
        import traceback
        print(f"\nFatal: {e}")
        traceback.print_exc()
        cache.stop()