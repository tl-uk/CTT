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
from confluent_kafka import Producer

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
        self.producer = Producer({
            "bootstrap.servers": KAFKA_BOOTSTRAP,
            "client.id": f"ctt-audit-{CITY_ID}",
            "queue.buffering.max.messages": 5000,
            "queue.buffering.max.ms": 500,
            "compression.type": "lz4",
            "message.timeout.ms": 1000,  # Drop if Kafka unavailable
        })
        self._running = False
        self._last_states = {}

    def _delivery_report(self, err, msg):
        if err:
            # Cold path: silent fail
            pass

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

    def run(self):
        ctx = zmq.Context()

        # SUB to telemetry (5555)
        tele_sub = get_resilient_socket(ctx, zmq.SUB, is_sub=True)
        tele_sub.connect(ZMQ_PORTS.get("L1_TELEMETRY_SUB", "tcp://localhost:5555"))
        tele_sub.setsockopt_string(zmq.SUBSCRIBE, "")

        # SUB to perturbations (5556) — observe Fusion output
        pert_sub = get_resilient_socket(ctx, zmq.SUB, is_sub=True)
        pert_sub.connect(ZMQ_PORTS.get("L1_PERTURBATION_SUB", "tcp://localhost:5556"))
        pert_sub.setsockopt_string(zmq.SUBSCRIBE, "")

        print(f"[AuditLogger] Online | city={CITY_ID} | kafka={KAFKA_BOOTSTRAP}")
        print("[AuditLogger] COLD PATH — dropped messages do not affect real-time loop")

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

                            # Always log telemetry
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

                        envelope = self._envelope("perturbation", payload)
                        self.producer.produce(
                            PERTURBATION_TOPIC,
                            value=json.dumps(envelope).encode(),
                            callback=self._delivery_report,
                        )
                    except Exception:
                        pass

                self.producer.poll(0)

        finally:
            print("[AuditLogger] Flushing...")
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