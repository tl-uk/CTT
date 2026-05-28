#!/usr/bin/env python3
"""
services/l5-macro/audit_logger.py

Phase 6 — L5 Cold Path Audit Logger.
Subscribes to ZMQ telemetry (5555) and perturbations (5556),
writes structured JSON to Kafka for DfT compliance and L5 aggregation.

COLD PATH: If Kafka is down, messages are dropped. The real-time loop
in L1/L2/L3 continues unaffected.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "config"))

import zmq
from confluent_kafka import Producer, KafkaException

from ports import ZMQ_PORTS, get_resilient_socket
from settings import config

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

KAFKA_BOOTSTRAP = config.KAFKA_BOOTSTRAP_SERVERS
TELEMETRY_TOPIC = config.KAFKA_TELEMETRY_TOPIC
PERTURBATION_TOPIC = config.KAFKA_PERTURBATION_TOPIC
DECISION_TOPIC = "ctt.agent.decision"
CITY_ID = config.CTT_CITY_ID
REGION = config.CTT_REGION

# -----------------------------------------------------------------------------
# Audit Logger
# -----------------------------------------------------------------------------

class AuditLogger:
    def __init__(self):
        self.producer = None
        self._running = False
        self._last_states = {}

    def _delivery_report(self, err, msg):
        if err:
            pass  # Cold path: silent fail

    def _envelope(self, event_type: str, payload: dict) -> dict:
        return {
            "meta": {
                "event_type": event_type,
                "city_id": CITY_ID,
                "region": REGION,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source_host": os.uname().nodename,
            },
            "payload": payload,
        }

    def _init_kafka(self, retries: int = 5, delay: float = 3.0):
        """Lazy Kafka Producer init with retry. Never blocks ZMQ loop."""
        for attempt in range(1, retries + 1):
            try:
                self.producer = Producer({
                    "bootstrap.servers": KAFKA_BOOTSTRAP,
                    "client.id": f"ctt-audit-{CITY_ID}",
                    "queue.buffering.max.messages": 5000,
                    "queue.buffering.max.ms": 500,
                    "compression.type": "lz4",
                    "message.timeout.ms": 1000,
                    "socket.timeout.ms": 5000,
                    "metadata.max.age.ms": 5000,
                    # Suppress noisy librdkafka connection logs
                    "log_level": 4,  # ERROR only (0=EMERG, 6=DEBUG)
                })
                self.producer.poll(timeout=1)
                print(f"[AuditLogger] ✅ Kafka producer ready ({KAFKA_BOOTSTRAP})")
                return True
            except Exception as e:
                print(f"[AuditLogger] ⚠️ Kafka init attempt {attempt}/{retries}: {e}")
                time.sleep(delay)
        print("[AuditLogger] ❌ Kafka unavailable — running ZMQ-only (cold path)")
        return False

    def run(self):
        # --- Startup banner (must appear immediately in docker logs) ---
        print(f"[AuditLogger] Online | city={CITY_ID} | region={REGION}")
        print("[AuditLogger] COLD PATH — dropped messages do not affect real-time loop")

        # --- ZMQ setup (hot path, never blocks) ---
        ctx = zmq.Context()
        tele_sub = get_resilient_socket(ctx, zmq.SUB, is_sub=True)
        tele_sub.connect(ZMQ_PORTS.get("L1_TELEMETRY_SUB", "tcp://localhost:5555"))
        tele_sub.setsockopt_string(zmq.SUBSCRIBE, "")

        pert_sub = get_resilient_socket(ctx, zmq.SUB, is_sub=True)
        pert_sub.connect(ZMQ_PORTS.get("L1_PERTURBATION_SUB", "tcp://localhost:5556"))
        pert_sub.setsockopt_string(zmq.SUBSCRIBE, "")

        print("[AuditLogger] ZMQ subscribers connected")

        # --- Kafka setup (cold path, lazy init) ---
        self._init_kafka()

        poller = zmq.Poller()
        poller.register(tele_sub, zmq.POLLIN)
        poller.register(pert_sub, zmq.POLLIN)

        self._running = True
        try:
            while self._running:
                socks = dict(poller.poll(timeout=100))

                if tele_sub in socks:
                    try:
                        raw = tele_sub.recv()
                        data = json.loads(raw.decode("utf-8"))
                        if not isinstance(data, list):
                            continue

                        for agent in data:
                            name = agent.get("entity_name", "unknown")
                            was_decarb = self._last_states.get(name, {}).get("is_decarbonized", False)
                            now_decarb = agent.get("is_decarbonized", False)

                            if self.producer:
                                self.producer.produce(
                                    TELEMETRY_TOPIC,
                                    value=json.dumps(self._envelope("telemetry", agent)).encode(),
                                    callback=self._delivery_report,
                                )

                            if now_decarb and not was_decarb:
                                decision = self._envelope("decision", {
                                    "entity_name": name,
                                    "decision": "DECARBONIZED",
                                    "adversarial_pressure": agent.get("adversarial_pressure"),
                                    "timestamp": agent.get("timestamp"),
                                })
                                if self.producer:
                                    self.producer.produce(
                                        DECISION_TOPIC,
                                        value=json.dumps(decision).encode(),
                                        callback=self._delivery_report,
                                    )
                                print(f"[AuditLogger] 🌱 {name} DECARBONIZED (pressure={agent.get('adversarial_pressure')})")

                            self._last_states[name] = agent
                    except Exception:
                        pass

                if pert_sub in socks:
                    try:
                        raw = pert_sub.recv()
                        try:
                            payload = json.loads(raw.decode("utf-8"))
                        except json.JSONDecodeError:
                            payload = {"raw_hex": raw.hex(), "note": "protobuf_binary"}

                        if self.producer:
                            envelope = self._envelope("perturbation", payload)
                            self.producer.produce(
                                PERTURBATION_TOPIC,
                                value=json.dumps(envelope).encode(),
                                callback=self._delivery_report,
                            )
                    except Exception:
                        pass

                if self.producer:
                    self.producer.poll(0)

        finally:
            print("[AuditLogger] Shutting down...")
            if self.producer:
                self.producer.flush(timeout=2)
            tele_sub.close()
            pert_sub.close()
            ctx.term()

    def stop(self):
        self._running = False


if __name__ == "__main__":
    logger = AuditLogger()
    try:
        logger.run()
    except KeyboardInterrupt:
        print("\n🛑 Audit logger stopping...")
        logger.stop()