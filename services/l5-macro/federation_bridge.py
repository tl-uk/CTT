#!/usr/bin/env python3
"""
services/l5-macro/federation_bridge.py

Phase 12e — FIXED syntax error + internal Kafka topic bootstrap.
Uses get_resilient_socket to prevent "Address already in use" on rapid restarts.
"""
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "config"))

import zmq
from ports import ZMQ_PORTS, get_resilient_socket
from settings import config

# =============================================================================
# Phase 12e FIX: Docker-aware ZMQ addresses
# =============================================================================

CITY_ID = config.CTT_CITY_ID

ZMQ_POLICY_PUB = ZMQ_PORTS.get("POLICY_PUB", "tcp://*:5563")

if os.environ.get("CTT_DOCKER_MODE", "0") == "1":
    ZMQ_TELEMETRY_SUB = "tcp://ctt-engine:5555"
    KAFKA_BOOTSTRAP = "kafka:29092"
else:
    ZMQ_TELEMETRY_SUB = ZMQ_PORTS.get("L1_TELEMETRY_SUB", "tcp://localhost:5555")
    KAFKA_BOOTSTRAP = "localhost:9092"

# Phase 12e: Kafka integration + admin client for topic bootstrap
try:
    from kafka import KafkaProducer
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
    print("[FederationBridge] ⚠️  kafka-python not installed — audit logging disabled")

# =============================================================================
# Phase 7 — Cross-Domain Belief Envelope
# =============================================================================

BELIEF_SCHEMA_VERSION = "ctt-belief-1.0"
BELIEF_REQUIRED_FIELDS = ["meta", "payload"]
BELIEF_META_FIELDS = ["schema_version", "domain_id", "corridor_id", "timestamp", "source_host"]

DOMAIN_CAPABILITIES = {
    "domain-dft": {"observes": ["transport", "policy"], "emits": ["structural_policy"]},
    "domain-dhl": {"observes": ["logistics", "freight"], "emits": ["telemetry"]},
    "domain-nhs": {"observes": ["health", "air_quality", "equity"], "emits": ["health_belief"]},
    "domain-beis": {"observes": ["economy", "employment", "energy"], "emits": ["economic_belief"]},
    "domain-met-office": {"observes": ["climate", "weather", "heat_stress"], "emits": ["climate_belief"]},
    "domain-pod": {"observes": ["maritime", "freight", "terminal"], "emits": ["terminal_belief"]},
}


def ensure_topics(bootstrap_servers: str, client_id: str = "ctt-bootstrap"):
    """Idempotent topic creation. Safe to call from every service on startup."""
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
        print(f"[FederationBridge] ✅ Created topics: {[t.name for t in CTT_TOPICS]}")
    except TopicAlreadyExistsError:
        print(f"[FederationBridge] ℹ️ Topics already exist, skipping creation")
    except Exception as e:
        print(f"[FederationBridge] ⚠️ Topic bootstrap warning (non-fatal): {e}")
    finally:
        if admin:
            admin.close()

class FederationBridge:
    def __init__(self):
        self.ctx = zmq.Context()
        self.policy_pub = get_resilient_socket(self.ctx, zmq.PUB, is_sub=False)
        self.policy_pub.bind(ZMQ_POLICY_PUB)
        self.tele_sub = get_resilient_socket(self.ctx, zmq.SUB, is_sub=True)
        self._connect_with_retry(self.tele_sub, ZMQ_TELEMETRY_SUB)
        self.tele_sub.setsockopt_string(zmq.SUBSCRIBE, "")

        self.kafka_producer = None
        if HAS_KAFKA:
            try:
                ensure_topics(KAFKA_BOOTSTRAP, client_id="federation-bridge-bootstrap")
                self.kafka_producer = KafkaProducer(
                    bootstrap_servers=KAFKA_BOOTSTRAP,
                    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                    retries=3,
                    retry_backoff_ms=1000
                )
                print(f"[FederationBridge] Kafka producer connected to {KAFKA_BOOTSTRAP}")
            except Exception as e:
                print(f"[FederationBridge] ⚠️  Kafka connection failed: {e}")

        self._running = False
        self.window = defaultdict(list)

    def _connect_with_retry(self, socket, address, max_retries=30, delay=2.0):
        for attempt in range(max_retries):
            try:
                socket.connect(address)
                print(f"[FederationBridge] Connected to {address}")
                return
            except zmq.error.ZMQError as e:
                print(f"[FederationBridge] ⏳ Retry {attempt+1}/{max_retries}: {e}")
                time.sleep(delay)
        raise RuntimeError(f"Failed to connect to {address} after {max_retries} attempts")

    def run(self):
        print(f"[FederationBridge] Online | city={CITY_ID} | ZMQ mode")
        print(f"[FederationBridge] ZMQ policy pub: {ZMQ_POLICY_PUB}")
        print(f"[FederationBridge] ZMQ telemetry sub: {ZMQ_TELEMETRY_SUB}")
        print(f"[FederationBridge] Kafka: {KAFKA_BOOTSTRAP if self.kafka_producer else 'DISABLED'}")
        print("[FederationBridge] L5 → L2 feedback loop active")
        time.sleep(1.5)

        self._running = True
        last_eval = time.time()

        while self._running:
            try:
                msg = self.tele_sub.recv_string()
                data = json.loads(msg)
                if isinstance(data, dict) and self._validate_belief(data):
                    self._merge_belief(data)
                elif isinstance(data, list):
                    for agent in data:
                        city = agent.get("city_id", CITY_ID)
                        pressure = agent.get("adversarial_pressure", 0)
                        self.window[city].append(pressure)
            except zmq.error.Again:
                pass
            except Exception as e:
                print(f"[FederationBridge] Parse error: {e}")

            if time.time() - last_eval >= 30:
                self._evaluate_and_emit()
                last_eval = time.time()

    def _wrap_belief(self, payload: dict, corridor_id: str = "national") -> dict:
        return {
            "meta": {
                "schema_version": BELIEF_SCHEMA_VERSION,
                "domain_id": CITY_ID,
                "corridor_id": corridor_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source_host": os.environ.get("CTT_REGION", "uk-southeast"),
                "ttl_seconds": 300,
            },
            "payload": payload,
            "provenance": {
                "upstream_domains": [],
                "confidence": 1.0,
                "model_version": "ctt-phase12e",
            }
        }

    def _validate_belief(self, msg: dict) -> bool:
        if not isinstance(msg, dict):
            return False
        for field in BELIEF_REQUIRED_FIELDS:
            if field not in msg:
                return False
        meta = msg.get("meta", {})
        for field in BELIEF_META_FIELDS:
            if field not in meta:
                return False
        try:
            ts = datetime.fromisoformat(meta["timestamp"].replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - ts).total_seconds() > 300:
                return False
        except Exception:
            return False
        return True

    def _merge_belief(self, belief: dict):
        domain = belief["meta"]["domain_id"]
        corridor = belief["meta"]["corridor_id"]
        payload = belief["payload"]
        key = f"{domain}:{corridor}"
        self.window[key] = {
            "belief": belief,
            "received_at": time.time(),
        }
        print(f"[FederationBridge] Belief merged from {domain} for corridor {corridor}: "
              f"{list(payload.keys())}")

    def _evaluate_and_emit(self):
        local_pressures = self.window.get(CITY_ID, [])
        if not local_pressures:
            print(f"[FederationBridge] {CITY_ID} window empty — no data yet")
            return

        avg_pressure = sum(local_pressures) / len(local_pressures)
        self.window.clear()
        print(f"[FederationBridge] {CITY_ID} avg pressure={avg_pressure:.1f}")

        if avg_pressure > 60.0:
            policy = {
                "meta": {
                    "event_type": "structural_policy",
                    "city_id": CITY_ID,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "l5_federation_bridge",
                },
                "payload": {
                    "policy_type": "pressure_relief",
                    "pressure_cap": 75.0,
                    "toll_discount_pct": 10.0,
                    "target_sector": "all_hgv",
                    "reason": f"avg_pressure_exceeded_60 (actual={avg_pressure:.1f})",
                }
            }
            try:
                belief = self._wrap_belief(policy, corridor_id="national")
                self.policy_pub.send_string(json.dumps(belief))
                print(f"[FederationBridge] EMITTED belief envelope: pressure_cap=75.0")
                if self.kafka_producer:
                    self.kafka_producer.send('ctt.audit.policy', belief)
            except Exception as e:
                print(f"[FederationBridge] ZMQ publish failed: {e}")

    def stop(self):
        self._running = False
        if self.kafka_producer:
            self.kafka_producer.close()

if __name__ == "__main__":
    bridge = FederationBridge()
    try:
        bridge.run()
    except KeyboardInterrupt:
        print("\n🛑 Federation bridge stopping...")
        bridge.stop()
    except Exception as e:
        import traceback
        print(f"\n💥 Fatal: {e}")
        traceback.print_exc()
        bridge.stop()