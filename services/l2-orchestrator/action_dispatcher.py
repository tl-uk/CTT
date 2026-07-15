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
KAFKA_BOOTSTRAP = os.environ.get("CTT_KAFKA", "ctt-kafka:9092")

# Rate limiting
MAX_ACTIONS_PER_AGENT_PER_SEC = 10
RATE_LIMIT_WINDOW_SEC = 1.0

# Priority levels
PRIORITY_URGENT = 0    # Safety-critical: collision avoidance, emergency stop
PRIORITY_POLICY = 1      # Policy interventions: toll changes, ULEZ expansion
PRIORITY_AGENT = 2       # Normal agent decisions: route choice, mode switch
PRIORITY_BACKGROUND = 3  # Learning updates: parameter tuning, exploration

# =============================================================================
# Data Structures
# =============================================================================

@dataclass(order=True)
class PrioritizedAction:
    """Action with priority for heapq ordering."""
    priority: int
    timestamp_ms: int
    action_id: str
    agent_id: str
    action_type: str
    payload: dict

    def __post_init__(self):
        # Ensure heapq orders by priority then timestamp
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

        # Priority queue (thread-safe via lock)
        self.action_queue: list = []
        self.queue_lock = threading.RLock()

        # Rate limiters per agent
        self.agent_timestamps: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=MAX_ACTIONS_PER_AGENT_PER_SEC)
        )
        self.rate_lock = threading.RLock()

        # Kafka consumer
        self.kafka_consumer = None
        try:
            from kafka import KafkaConsumer
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
        """Check if agent has exceeded action rate limit."""
        with self.rate_lock:
            now = time.time()
            timestamps = self.agent_timestamps[agent_id]

            # Remove timestamps outside window
            while timestamps and timestamps[0] < now - RATE_LIMIT_WINDOW_SEC:
                timestamps.popleft()

            if len(timestamps) >= MAX_ACTIONS_PER_AGENT_PER_SEC:
                return False

            timestamps.append(now)
            return True

    def _parse_action(self, envelope: dict) -> Optional[PrioritizedAction]:
        """Parse Kafka message into PrioritizedAction."""
        try:
            payload = envelope.get("payload", {})
            action_type = payload.get("action_type", "unknown")
            agent_id = payload.get("agent_id", "all")

            # Map action type to priority
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
        """Dispatch single action as ZMQ perturbation."""
        if not self._check_rate_limit(action.agent_id):
            print(f"[ActionDispatcher] ⏸️  Rate limited: {action.agent_id}")
            return False

        # Convert action to Protobuf-compatible perturbation
        # The C++ engine expects: agent_uuid, pressure_delta, source
        perturbation = {
            "agent_uuid": action.agent_id,
            "pressure_delta": action.payload.get("pressure_delta", 0.0),
            "source": f"abdt:{action.action_type}"
        }

        # Special handling for mode_switch
        if action.action_type == "mode_switch":
            # Mode switches require larger pressure changes
            target_mode = action.payload.get("target_mode", "BEV")
            if target_mode in ["BEV", "FCEV"]:
                perturbation["pressure_delta"] = 15.0  # Push toward decarbonization
            else:
                perturbation["pressure_delta"] = -10.0  # Pull toward ICE

        # Special handling for route_choice
        if action.action_type == "route_choice":
            # Route changes affect corridor_id (handled by engine's SocialImpactComponent)
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
        """Background thread: consume from Kafka and enqueue actions."""
        if not self.kafka_consumer:
            # File-based fallback for testing
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

        # Kafka consumer loop
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
        """Main loop: drain priority queue and dispatch actions."""
        while self._running:
            actions_to_dispatch = []

            with self.queue_lock:
                # Drain up to 10 actions per iteration
                for _ in range(10):
                    if not self.action_queue:
                        break
                    actions_to_dispatch.append(heapq.heappop(self.action_queue))

            for action in actions_to_dispatch:
                self._dispatch_action(action)

            time.sleep(0.01)  # 100 Hz dispatch loop (well below 10ms tick)

    def run(self):
        print("[ActionDispatcher] 🚀 Starting action dispatch service")
        print(f"[ActionDispatcher] Rate limit: {MAX_ACTIONS_PER_AGENT_PER_SEC}/sec per agent")
        print(f"[ActionDispatcher] ZMQ target: {ZMQ_PERTURBATION_PUB}")

        self._running = True

        # Start Kafka consumer thread
        kafka_thread = threading.Thread(target=self._process_kafka, daemon=True)
        kafka_thread.start()

        # Main dispatch loop
        try:
            self._dispatch_loop()
        except KeyboardInterrupt:
            print("
🛑 Action dispatcher stopping...")
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
        print(f"
💥 Fatal: {e}")
        traceback.print_exc()
        dispatcher.stop()
