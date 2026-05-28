#!/usr/bin/env python3
"""
services/l5-macro/federation_bridge.py

Phase 6 — L5 Macro & Federation Bridge (ZMQ-only).
Consumes telemetry directly from ZMQ 5555, evaluates structural policy,
and emits to ZMQ POLICY_PUB (5563).
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

CITY_ID = config.CTT_CITY_ID
ZMQ_POLICY_PUB = ZMQ_PORTS.get("POLICY_PUB", "tcp://*:5563")
ZMQ_TELEMETRY_SUB = ZMQ_PORTS.get("L1_TELEMETRY_SUB", "tcp://localhost:5555")

class FederationBridge:
    def __init__(self):
        self.ctx = zmq.Context()
        self.policy_pub = get_resilient_socket(self.ctx, zmq.PUB)
        self.policy_pub.bind(ZMQ_POLICY_PUB)
        self.tele_sub = get_resilient_socket(self.ctx, zmq.SUB, is_sub=True)
        self.tele_sub.connect(ZMQ_TELEMETRY_SUB)
        self.tele_sub.setsockopt_string(zmq.SUBSCRIBE, "")
        # CRITICAL: Allow slow-joiner synchronization
        time.sleep(1.0)  # Give ZMQ time to establish subscription
        self._running = False
        self.window = defaultdict(list)

    def run(self):
        print(f"[FederationBridge] Online | city={CITY_ID} | ZMQ mode")
        print(f"[FederationBridge] ZMQ policy pub: {ZMQ_POLICY_PUB}")
        print("[FederationBridge] L5 → L2 feedback loop active")
        
        # Use Poller + blocking recv with timeout (correct SUB pattern)
        poller = zmq.Poller()
        poller.register(self.tele_sub, zmq.POLLIN)
        
        self._running = True
        last_eval = time.time()

        while self._running:
            # Block up to 1s waiting for telemetry
            socks = dict(poller.poll(timeout=1000))
            
            if self.tele_sub in socks:
                try:
                    msg = self.tele_sub.recv_string()
                    data = json.loads(msg)
                    if isinstance(data, list):
                        for agent in data:
                            city = agent.get("city_id", "unknown")
                            pressure = agent.get("adversarial_pressure", 0)
                            self.window[city].append(pressure)
                except Exception as e:
                    print(f"[FederationBridge] Parse error: {e}")

            if time.time() - last_eval >= 30:
                self._evaluate_and_emit()
                last_eval = time.time()

    def _evaluate_and_emit(self):
        local_pressures = self.window.get(CITY_ID, [])
        if not local_pressures:
            print(f"[FederationBridge] 📊 {CITY_ID} window empty — no data yet")
            return

        avg_pressure = sum(local_pressures) / len(local_pressures)
        self.window.clear()
        print(f"[FederationBridge] 📊 {CITY_ID} avg pressure={avg_pressure:.1f}")

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

    def stop(self):
        self._running = False

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