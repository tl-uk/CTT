#!/usr/bin/env python3
"""
services/l2-orchestrator/action_dispatcher.py

Phase 12d: Temporal Firewall — ABDT → Reflexive Action Dispatch

Purpose: Receives ABDT agent decisions and dispatches them as ZMQ perturbations
to the reflexive layer. Ensures ABDT reasoning never blocks the 10ms tick.

Architecture:
- SUBSCRIBES to: Kafka topic ctt.abdt.action (JSON action envelope)
- PUBLISHES to: ctt-engine ZMQ SUB (tcp://ctt-engine:5556)
- QUEUES: Thread-safe priority queue (urgent vs normal actions)
- RATE LIMITS: Max 10 perturbations/sec per agent (prevents thundering herd)

Scaling considerations:
- Can be replicated: each instance reads from Kafka consumer group
- ZMQ PUB socket can fan out to multiple engine instances
- Priority queue ensures policy interventions don't drown out agent actions

Phase 12e: Temporal Firewall — ABDT → Reflexive Action Dispatch
"""
import json
import os
import sys
import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional
import heapq

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "config"))

import zmq
from ports import ZMQ_PORTS, get_resilient_socket

# =============================================================================
# Configuration
# =============================================================================

ZMQ_PERTURBATION_PUB = os.environ.get("CTT_ZMQ_PERTURB", "tcp://ctt-engine:5556")
KAFKA_BOOTSTRAP = os.environ.get("CTT_KAFKA", "kafka:29092")

MAX_ACTIONS_PER_AGENT_PER_SEC = 10
RATE_LIMIT_WINDOW_SEC = 1.0

PRIORITY_URGENT = 0
PRIORITY_POLICY = 1
PRIORITY_AGENT = 2
PRIORITY_BACKGROUND = 3

# =============================================================================
# Kafka topic bootstrap
# =============================================================================
try:
    from kafka import KafkaConsumer
    from kafka.admin import KafkaAdminClient, NewTopic
    from kafka.errors import TopicAlreadyExistsError
    HAS_KAFKA = True
    CTT_TOPICS = [
        NewTopic(name="ctt.abdt.observation", num_partitions=3, replication_factor=1),
        NewTopic(name="ctt.abdt.action", num_partitions=3, replication_factor=1),
        NewTopic(name="ctt.abdt.policy", num_partitions=1, replication_factor=1),
        NewTopic(name="ctt.audit.policy", num_partitions=1, replication_factor=1),
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
        print(f"[ActionDispatcher] ✅ Created topics: {[t.name for t in CTT_TOPICS]}")
    except TopicAlreadyExistsError:
        print(f"[ActionDispatcher] ℹ️ Topics already exist, skipping creation")
    except Exception as e:
        print(f"[ActionDispatcher] ⚠️ Topic bootstrap warning (non-fatal): {e}")
    finally:
        if admin:
            admin.close()

# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class PrioritizedAction:
    priority: int
    timestamp_ms: int
    action_id: str
    agent_id: str
    action_type: str
    payload: dict

    def __post_init__(self):
        self._sort_key = (self.priority, self.timestamp_ms)

    def __lt__(self, other):
        return self._sort_key < other._sort_key

# =============================================================================
# Action Dispatcher
# =============================================================================

class ActionDispatcher:
    def __init__(self):
        self.ctx = zmq.Context()
        self.perturb_pub = get_resilient_socket(self.ctx, zmq.PUB, is_sub=False)
        self._connect_with_retry(self.perturb_pub, ZMQ_PERTURBATION_PUB)

        self.action_queue: list = []
        self.queue_lock = threading.RLock()

        self.agent_timestamps: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=MAX_ACTIONS_PER_AGENT_PER_SEC)
        )
        self.rate_lock = threading.RLock()

        self.kafka_consumer = None
        if HAS_KAFKA:
            try:
                ensure_topics(KAFKA_BOOTSTRAP, client_id="action-dispatcher-bootstrap")
                self.kafka_consumer = KafkaConsumer(
                    'ctt.abdt.action',
                    'ctt.abdt.policy',
                    bootstrap_servers=KAFKA_BOOTSTRAP,
                    group_id='action-dispatchers',
                    value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                    auto_offset_reset='latest',
                    enable_auto_commit=True,
                    max_poll_records=100
                )
                print(f"[ActionDispatcher] Kafka consumer connected to {KAFKA_BOOTSTRAP}")
            except Exception as e:
                print(f"[ActionDispatcher] ⚠️  Kafka unavailable: {e}")
                print(f"[ActionDispatcher] Reading actions from /tmp/ctt_actions.jsonl")
        else:
            print(f"[ActionDispatcher] Reading actions from /tmp/ctt_actions.jsonl")

        self._running = False
        self.action_counter = 0

    def _connect_with_retry(self, socket, address, max_retries=30, delay=2.0):
        for attempt in range(max_retries):
            try:
                socket.connect(address)
                print(f"[ActionDispatcher] Connected to {address}")
                return
            except zmq.error.ZMQError as e:
                print(f"[ActionDispatcher] ⏳ Retry {attempt+1}/{max_retries}: {e}")
                time.sleep(delay)
        raise RuntimeError(f"Failed to connect to {address}")

    def _check_rate_limit(self, agent_id: str) -> bool:
        with self.rate_lock:
            now = time.time()
            timestamps = self.agent_timestamps[agent_id]
            while timestamps and timestamps[0] < now - RATE_LIMIT_WINDOW_SEC:
                timestamps.popleft()
            if len(timestamps) >= MAX_ACTIONS_PER_AGENT_PER_SEC:
                return False
            timestamps.append(now)
            return True

    def _parse_action(self, envelope: dict) -> Optional[PrioritizedAction]:
        try:
            payload = envelope.get("payload", {})
            action_type = payload.get("action_type", "unknown")
            agent_id = payload.get("agent_id", "all")

            priority_map = {
                "emergency_stop": PRIORITY_URGENT,
                "collision_avoidance": PRIORITY_URGENT,
                "policy_intervention": PRIORITY_POLICY,
                "toll_change": PRIORITY_POLICY,
                "route_choice": PRIORITY_AGENT,
                "mode_switch": PRIORITY_AGENT,
                "parameter_update": PRIORITY_BACKGROUND,
                "exploration": PRIORITY_BACKGROUND,
            }
            priority = priority_map.get(action_type, PRIORITY_AGENT)

            self.action_counter += 1
            return PrioritizedAction(
                priority=priority,
                timestamp_ms=int(time.time() * 1000),
                action_id=f"act-{self.action_counter}-{agent_id}",
                agent_id=agent_id,
                action_type=action_type,
                payload=payload
            )
        except Exception as e:
            print(f"[ActionDispatcher] Parse error: {e}")
            return None

    def _dispatch_action(self, action: PrioritizedAction) -> bool:
        if not self._check_rate_limit(action.agent_id):
            print(f"[ActionDispatcher] ⏸️  Rate limited: {action.agent_id}")
            return False

        perturbation = {
            "agent_uuid": action.agent_id,
            "pressure_delta": action.payload.get("pressure_delta", 0.0),
            "source": f"abdt:{action.action_type}"
        }

        if action.action_type == "mode_switch":
            target_mode = action.payload.get("target_mode", "BEV")
            if target_mode in ["BEV", "FCEV"]:
                perturbation["pressure_delta"] = 15.0
            else:
                perturbation["pressure_delta"] = -10.0

        if action.action_type == "route_choice":
            corridor = action.payload.get("corridor_id", "national")
            perturbation["source"] = f"abdt:route:{corridor}"

        try:
            msg = json.dumps(perturbation)
            self.perturb_pub.send_string(msg)
            print(f"[ActionDispatcher] 🚀 {action.action_id}: {action.action_type} "
                  f"→ {action.agent_id} (δ={perturbation['pressure_delta']:.1f})")
            return True
        except Exception as e:
            print(f"[ActionDispatcher] ⚠️  Dispatch failed: {e}")
            return False

    def _process_kafka(self):
        if not self.kafka_consumer:
            while self._running:
                try:
                    if os.path.exists('/tmp/ctt_actions.jsonl'):
                        with open('/tmp/ctt_actions.jsonl', 'r') as f:
                            for line in f:
                                envelope = json.loads(line.strip())
                                action = self._parse_action(envelope)
                                if action:
                                    with self.queue_lock:
                                        heapq.heappush(self.action_queue, action)
                    time.sleep(0.5)
                except Exception as e:
                    print(f"[ActionDispatcher] File read error: {e}")
                    time.sleep(1.0)
            return

        for message in self.kafka_consumer:
            if not self._running:
                break
            try:
                envelope = message.value
                action = self._parse_action(envelope)
                if action:
                    with self.queue_lock:
                        heapq.heappush(self.action_queue, action)
            except Exception as e:
                print(f"[ActionDispatcher] Kafka parse error: {e}")

    def _dispatch_loop(self):
        while self._running:
            actions_to_dispatch = []
            with self.queue_lock:
                for _ in range(10):
                    if not self.action_queue:
                        break
                    actions_to_dispatch.append(heapq.heappop(self.action_queue))

            for action in actions_to_dispatch:
                self._dispatch_action(action)

            time.sleep(0.01)

    def run(self):
        print("[ActionDispatcher] 🚀 Starting action dispatch service")
        print(f"[ActionDispatcher] Rate limit: {MAX_ACTIONS_PER_AGENT_PER_SEC}/sec per agent")
        print(f"[ActionDispatcher] ZMQ target: {ZMQ_PERTURBATION_PUB}")

        self._running = True
        kafka_thread = threading.Thread(target=self._process_kafka, daemon=True)
        kafka_thread.start()

        try:
            self._dispatch_loop()
        except KeyboardInterrupt:
            print("\n🛑 Action dispatcher stopping...")
        finally:
            self.stop()

    def stop(self):
        self._running = False
        if self.kafka_consumer:
            self.kafka_consumer.close()

if __name__ == "__main__":
    dispatcher = ActionDispatcher()
    try:
        dispatcher.run()
    except Exception as e:
        import traceback
        print(f"\n💥 Fatal: {e}")
        traceback.print_exc()
        dispatcher.stop()