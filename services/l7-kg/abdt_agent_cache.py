#!/usr/bin/env python3
"""
services/l7-kg/abdt_agent_cache.py

Phase 12d: ABDT Agent State Cache — Temporal Decoupling Layer

Purpose: Stores ABDT agent beliefs, plans, and state independently of the 
reflexive 10ms tick. Enables ABDT agents to reason at human/policy timescales
while maintaining consistency with the digital twin.

Architecture:
- CONSUMES from: Kafka ctt.abdt.observation (aggregated state from StateAggregator)
- PUBLISHES to: Kafka ctt.abdt.action (decisions from ABDT reasoning)
- STORES: In-memory cache + optional Redis persistence
- QUERYABLE: REST API for ABDT agents to read/write state

Key insight: ABDT agents are NOT Flecs entities. They are Python objects that:
1. Observe aggregated state (via this cache)
2. Update their beliefs (BDI model)
3. Emit actions (via ActionDispatcher)
4. Record experiences (via L7 KG)

Scaling considerations:
- Each ABDT agent has its own cache entry
- Cache is sharded by agent_id for horizontal scaling
- TTL-based eviction (agents that haven't updated in 1 hour are archived)
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

# =============================================================================
# Configuration
# =============================================================================

KAFKA_BOOTSTRAP = os.environ.get("CTT_KAFKA", "ctt-kafka:9092")
CACHE_TTL_SECONDS = 3600  # 1 hour
MAX_HISTORY_OBSERVATIONS = 60  # 1 minute of observations

# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class ABDTAgentState:
    """Complete state for a single ABDT agent."""
    agent_id: str
    corridor_id: str = "national"

    # BDI Beliefs (updated by ABDT reasoning, not reflexive tick)
    beliefs: Dict[str, Any] = field(default_factory=dict)

    # Intentions (current plan)
    current_intention: Optional[str] = None
    intention_deadline_ms: int = 0

    # Desires (goal stack)
    goal_stack: List[str] = field(default_factory=list)

    # Observed state (from StateAggregator, aggregated)
    last_observation: Optional[Dict] = None
    observation_history: List[Dict] = field(default_factory=list)

    # TCO reasoning state
    tco_model: Dict[str, float] = field(default_factory=lambda: {
        "capex_ice": 50000.0,
        "capex_ev": 80000.0,
        "opex_ice": 15000.0,
        "opex_ev": 8000.0,
        "years_in_service": 0.0,
        "green_grey_gap": -23000.0
    })

    # ToC reasoning state
    toc_model: Dict[str, Any] = field(default_factory=lambda: {
        "active_constraint": "NONE",
        "severity": 0.0,
        "throughput_ratio": 1.0,
        "constraint_history": []
    })

    # SSN experience cache
    ssn_experiences: List[Dict] = field(default_factory=list)
    last_ssn_match: Optional[Dict] = None

    # Social model (coalition, negotiation state)
    coalition_members: List[str] = field(default_factory=list)
    negotiation_state: str = "idle"

    # Metadata
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def is_stale(self) -> bool:
        """Check if agent hasn't been updated within TTL."""
        age_sec = (int(time.time() * 1000) - self.updated_at_ms) / 1000.0
        return age_sec > CACHE_TTL_SECONDS

# =============================================================================
# ABDT Agent Cache
# =============================================================================

class ABDTAgentCache:
    def __init__(self):
        self.cache: Dict[str, ABDTAgentState] = {}
        self.lock = threading.RLock()

        # Kafka
        self.kafka_consumer = None
        self.kafka_producer = None
        try:
            from kafka import KafkaConsumer, KafkaProducer
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
            print(f"[ABDTCache] ⚠️  Kafka unavailable: {e}")

        # SSN match subscriber (from L7 KG)
        self.ssn_matches: List[Dict] = []

        self._running = False

    def get_or_create_agent(self, agent_id: str, corridor_id: str = "national") -> ABDTAgentState:
        """Get agent state or create new if not exists."""
        with self.lock:
            if agent_id not in self.cache:
                self.cache[agent_id] = ABDTAgentState(
                    agent_id=agent_id,
                    corridor_id=corridor_id
                )
                print(f"[ABDTCache] 🆕 Created agent: {agent_id}")
            return self.cache[agent_id]

    def update_from_observation(self, envelope: dict):
        """Update agent state from aggregated observation."""
        payload = envelope.get("payload", {})
        agent_id = payload.get("agent_id", "unknown")
        corridor_id = payload.get("corridor_id", "national")

        agent = self.get_or_create_agent(agent_id, corridor_id)

        with self.lock:
            agent.last_observation = payload
            agent.observation_history.append(payload)

            # Trim history
            if len(agent.observation_history) > MAX_HISTORY_OBSERVATIONS:
                agent.observation_history = agent.observation_history[-MAX_HISTORY_OBSERVATIONS:]

            # Update TCO model from observation
            if "energy_pct_end" in payload:
                energy = payload["energy_pct_end"]
                # Simple TCO update: more energy usage = higher opex
                agent.tco_model["opex_ice"] += (100 - energy) * 0.1
                agent.tco_model["opex_ev"] += (100 - energy) * 0.05
                # Recalculate gap
                total_ice = agent.tco_model["capex_ice"] + agent.tco_model["opex_ice"]
                total_ev = agent.tco_model["capex_ev"] + agent.tco_model["opex_ev"]
                agent.tco_model["green_grey_gap"] = total_ice - total_ev

            # Update ToC model from observation
            if "mindset_shift_count" in payload:
                shifts = payload["mindset_shift_count"]
                if shifts > 0:
                    agent.toc_model["active_constraint"] = "POLICY_REGULATORY"
                    agent.toc_model["severity"] = min(1.0, agent.toc_model["severity"] + 0.1)
                else:
                    agent.toc_model["severity"] = max(0.0, agent.toc_model["severity"] - 0.02)
                agent.toc_model["throughput_ratio"] = 1.0 - agent.toc_model["severity"]

            # Update SSN from observation
            if payload.get("ssn_recorded", False):
                exp = {
                    "timestamp_ms": payload.get("window_end_ms", 0),
                    "corridor_id": corridor_id,
                    "pressure": payload.get("pressure_end", 0.0)
                }
                agent.ssn_experiences.append(exp)

            agent.updated_at_ms = int(time.time() * 1000)

        print(f"[ABDTCache] 📥 {agent_id}: observation cached "
              f"(TCO gap={agent.tco_model['green_grey_gap']:.0f}, "
              f"ToC severity={agent.toc_model['severity']:.2f})")

    def apply_ssn_match(self, match: dict):
        """Apply SSN match from L7 KG to agent state."""
        agent_id = match.get("agent_id", "")
        if not agent_id or agent_id not in self.cache:
            return

        with self.lock:
            agent = self.cache[agent_id]
            agent.last_ssn_match = match

            # Update beliefs based on match
            confidence = match.get("confidence", 0.0)
            if confidence > 0.7:
                agent.beliefs["ssn_trust"] = agent.beliefs.get("ssn_trust", 0.5) + 0.1

            print(f"[ABDTCache] 🎯 SSN match applied to {agent_id} "
                  f"(confidence={confidence:.2f})")

    def set_intention(self, agent_id: str, intention: str, deadline_ms: int):
        """Set agent intention (called by ABDT reasoning)."""
        with self.lock:
            if agent_id in self.cache:
                self.cache[agent_id].current_intention = intention
                self.cache[agent_id].intention_deadline_ms = deadline_ms

    def push_goal(self, agent_id: str, goal: str):
        """Push goal onto agent's goal stack."""
        with self.lock:
            if agent_id in self.cache:
                self.cache[agent_id].goal_stack.append(goal)

    def pop_goal(self, agent_id: str) -> Optional[str]:
        """Pop goal from agent's goal stack."""
        with self.lock:
            if agent_id in self.cache and self.cache[agent_id].goal_stack:
                return self.cache[agent_id].goal_stack.pop()
            return None

    def emit_action(self, agent_id: str, action_type: str, payload: dict):
        """Emit action to Kafka for ActionDispatcher."""
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
            print(f"[ABDTCache] 🚀 Action emitted: {agent_id} → {action_type}")
        else:
            # File fallback
            with open('/tmp/ctt_actions.jsonl', 'a') as f:
                f.write(json.dumps(envelope) + '
')

    def query_agent(self, agent_id: str) -> Optional[dict]:
        """REST API: query agent state."""
        with self.lock:
            if agent_id not in self.cache:
                return None
            return asdict(self.cache[agent_id])

    def list_agents(self, corridor_id: Optional[str] = None) -> List[str]:
        """List all agents, optionally filtered by corridor."""
        with self.lock:
            if corridor_id:
                return [
                    aid for aid, agent in self.cache.items()
                    if agent.corridor_id == corridor_id and not agent.is_stale()
                ]
            return [aid for aid, agent in self.cache.items() if not agent.is_stale()]

    def cleanup_stale(self):
        """Remove stale agents from cache."""
        with self.lock:
            stale = [aid for aid, agent in self.cache.items() if agent.is_stale()]
            for aid in stale:
                # Archive to file before removing
                agent = self.cache[aid]
                with open(f'/tmp/ctt_agent_archive_{aid}.jsonl', 'a') as f:
                    f.write(json.dumps(asdict(agent)) + '
')
                del self.cache[aid]
                print(f"[ABDTCache] 🗑️  Archived stale agent: {aid}")

    def _consume_observations(self):
        """Background thread: consume from Kafka."""
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

    def run(self):
        print("[ABDTCache] 🚀 Starting ABDT agent cache")
        print(f"[ABDTCache] TTL: {CACHE_TTL_SECONDS}s, Max history: {MAX_HISTORY_OBSERVATIONS}")

        self._running = True

        # Start consumer thread
        consumer_thread = threading.Thread(target=self._consume_observations, daemon=True)
        consumer_thread.start()

        # Cleanup loop
        while self._running:
            time.sleep(60.0)  # Cleanup every minute
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
        print("
🛑 ABDT cache stopping...")
        cache.stop()
    except Exception as e:
        import traceback
        print(f"
💥 Fatal: {e}")
        traceback.print_exc()
        cache.stop()
