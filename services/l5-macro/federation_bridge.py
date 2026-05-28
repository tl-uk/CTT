#!/usr/bin/env python3
"""
services/l5-macro/federation_bridge.py

Phase 6 — L5 Macro & Federation Bridge.
Consumes aggregated telemetry from Kafka, detects structural patterns,
and emits slow-varying policy parameters back to the local L2/L3 stack
via ZMQ POLICY_PUB (5563).

This is the L5 → L2 feedback loop. It is not real-time; it evaluates
on 30-second windows.
"""
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "config"))

import zmq
from confluent_kafka import Consumer, Producer, KafkaException

from ports import ZMQ_PORTS, get_resilient_socket
from settings import config

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

KAFKA_BOOTSTRAP = config.KAFKA_BOOTSTRAP_SERVERS
TELEMETRY_TOPIC = config.KAFKA_TELEMETRY_TOPIC
POLICY_TOPIC = config.KAFKA_POLICY_TOPIC
GROUP_ID = config.KAFKA_CONSUMER_GROUP
CITY_ID = config.CTT_CITY_ID

ZMQ_POLICY_PUB = ZMQ_PORTS.get("POLICY_PUB", "tcp://*:5563")

# -----------------------------------------------------------------------------
# Federation Bridge
# -----------------------------------------------------------------------------

class FederationBridge:
    def __init__(self):
        self.consumer = None
        self.producer = None
        self.ctx = zmq.Context()
        self.policy_pub = get_resilient_socket(self.ctx, zmq.PUB)
        self.policy_pub.bind(ZMQ_POLICY_PUB)
        self._running = False
        self.window = defaultdict(list)

    def _delivery_report(self, err, msg):
        if err:
            print(f"[FederationBridge] Kafka delivery failed: {err}")

    def _init_kafka(self, retries: int = 5, delay: float = 3.0):
        """Lazy Kafka init. Prints status so docker logs -f is never empty."""
        for attempt in range(1, retries + 1):
            try:
                self.consumer = Consumer({
                    "bootstrap.servers": KAFKA_BOOTSTRAP,
                    "group.id": f"{GROUP_ID}-federation",
                    "auto.offset.reset": "latest",
                    "enable.auto.commit": True,
                    "session.timeout.ms": 6000,
                    "socket.timeout.ms": 5000,
                    "metadata.max.age.ms": 5000,
                })
                self.consumer.subscribe([TELEMETRY_TOPIC])

                self.producer = Producer({
                    "bootstrap.servers": KAFKA_BOOTSTRAP,
                    "client.id": f"ctt-federation-{CITY_ID}",
                    "queue.buffering.max.ms": 1000,
                    "socket.timeout.ms": 5000,
                })
                # Test metadata fetch
                self.consumer.poll(timeout=1)
                print(f"[FederationBridge] ✅ Kafka consumer/producer ready ({KAFKA_BOOTSTRAP})")
                return True
            except Exception as e:
                print(f"[FederationBridge] ⚠️ Kafka init attempt {attempt}/{retries}: {e}")
                time.sleep(delay)
        print("[FederationBridge] ❌ Kafka unavailable — policy evaluation suspended")
        return False

    def run(self):
        # --- Startup banner (must appear immediately in docker logs) ---
        print(f"[FederationBridge] Online | city={CITY_ID}")
        print(f"[FederationBridge] ZMQ policy pub: {ZMQ_POLICY_PUB}")
        print("[FederationBridge] L5 → L2 feedback loop active")
        # --- lazy Kafka init (non-blocking) ---
        kafka_ready = self._init_kafka()
        if not kafka_ready:
            print("[FederationBridge] ⚠️ Starting in ZMQ-only mode (Kafka unavailable)")
        
        last_eval = time.time()
        consecutive_errors = 0

        try:
            while self._running:
                if kafka_ready and self.consumer:
                    try:
                        msg = self.consumer.poll(timeout=1.0)
                        consecutive_errors = 0  # Reset on success
                        
                        if msg is None:
                            pass
                        elif msg.error():
                            print(f"[FederationBridge] Kafka error: {msg.error()}")
                        else:
                            try:
                                data = json.loads(msg.value().decode("utf-8"))
                                payload = data.get("payload", {})
                                city = payload.get("city_id", "unknown")
                                pressure = payload.get("adversarial_pressure", 0)
                                self.window[city].append(pressure)
                            except Exception as e:
                                print(f"[FederationBridge] Parse error: {e}")

                    except Exception as e:
                        consecutive_errors += 1
                        print(f"[FederationBridge] ⚠️ Consumer poll failed ({consecutive_errors}): {e}")
                        if consecutive_errors >= 10:
                            print("[FederationBridge] ❌ Too many errors — backing off to ZMQ-only for 60s")
                            kafka_ready = False
                            try:
                                self.consumer.close()
                            except Exception:
                                pass
                            self.consumer = None
                            time.sleep(60)
                            kafka_ready = self._init_kafka()
                            consecutive_errors = 0

                # Evaluate every 30 seconds regardless of Kafka state
                if time.time() - last_eval >= 30:
                    self._evaluate_and_emit()
                    last_eval = time.time()
        # Graceful shutdown on Ctrl+C
        finally:
            if self.consumer:
                self.consumer.close()
            self.policy_pub.close()
            self.ctx.term()

    def _evaluate_and_emit(self):
        """Structural policy: if local city avg pressure > 60, recommend relief."""
        if not self.window:
            return

        local_pressures = self.window.get(CITY_ID, [])
        if not local_pressures:
            self.window.clear()
            return

        avg_pressure = sum(local_pressures) / len(local_pressures)
        self.window.clear()

        print(f"[FederationBridge] 📊 {CITY_ID} avg pressure={avg_pressure:.1f} over last window")

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

            self.policy_pub.send_string(json.dumps(policy))
            print(f"[FederationBridge] 🏛️ EMITTED local policy: pressure_cap=75.0")

            if self.producer:
                self.producer.produce(
                    POLICY_TOPIC,
                    value=json.dumps(policy).encode(),
                    callback=self._delivery_report,
                )
                self.producer.poll(0)

    def stop(self):
        self._running = False


if __name__ == "__main__":
    bridge = FederationBridge()
    try:
        bridge.run()
    except KeyboardInterrupt:
        print("\n🛑 Federation bridge stopping...")
        bridge.stop()