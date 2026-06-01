#!/usr/bin/env python3
"""
services/l5-macro/federation_bridge.py

Phase 6.5 — L5 Macro & Federation Bridge (ZMQ resilience hardened).
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
import copy

# =============================================================================
# Phase 7 — Cross-Domain Belief Envelope
# Minimal shared JSON schema so NHS/BEIS/Met Office can federate without
# schema lock-in. Each domain publishes beliefs scoped to shared spatial
# corridors; CTT resolves conflicts at the L5 layer.
# =============================================================================

BELIEF_SCHEMA_VERSION = "ctt-belief-1.0"
BELIEF_REQUIRED_FIELDS = ["meta", "payload"]
BELIEF_META_FIELDS = ["schema_version", "domain_id", "corridor_id", "timestamp", "source_host"]

# Domain capability registry (who can observe what)
DOMAIN_CAPABILITIES = {
    "domain-dft": {"observes": ["transport", "policy"], "emits": ["structural_policy"]},
    "domain-dhl": {"observes": ["logistics", "freight"], "emits": ["telemetry"]},
    "domain-nhs": {"observes": ["health", "air_quality", "equity"], "emits": ["health_belief"]},
    "domain-beis": {"observes": ["economy", "employment", "energy"], "emits": ["economic_belief"]},
    "domain-met-office": {"observes": ["climate", "weather", "heat_stress"], "emits": ["climate_belief"]},
    "domain-pod": {"observes": ["maritime", "freight", "terminal"], "emits": ["terminal_belief"]},
}

CITY_ID = config.CTT_CITY_ID
ZMQ_POLICY_PUB = ZMQ_PORTS.get("POLICY_PUB", "tcp://*:5563")
ZMQ_TELEMETRY_SUB = ZMQ_PORTS.get("L1_TELEMETRY_SUB", "tcp://localhost:5555")

class FederationBridge:
    def __init__(self):
        self.ctx = zmq.Context()
        # Phase 6.5: Use resilient sockets (LINGER=0 prevents TIME_WAIT on restart)
        self.policy_pub = get_resilient_socket(self.ctx, zmq.PUB, is_sub=False)
        self.policy_pub.bind(ZMQ_POLICY_PUB)
        self.tele_sub = get_resilient_socket(self.ctx, zmq.SUB, is_sub=True)
        self.tele_sub.connect(ZMQ_TELEMETRY_SUB)
        self.tele_sub.setsockopt_string(zmq.SUBSCRIBE, "")
        self._running = False
        self.window = defaultdict(list)

    def run(self):
        print(f"[FederationBridge] Online | city={CITY_ID} | ZMQ mode")
        print(f"[FederationBridge] ZMQ policy pub: {ZMQ_POLICY_PUB}")
        print(f"[FederationBridge] ZMQ telemetry sub: {ZMQ_TELEMETRY_SUB}")
        print("[FederationBridge] L5 → L2 feedback loop active")
        time.sleep(1.5)

        self._running = True
        last_eval = time.time()

        while self._running:
            try:
                msg = self.tele_sub.recv_string()
                data = json.loads(msg)
                # Phase 7: Detect belief envelope vs raw telemetry
                if isinstance(data, dict) and self._validate_belief(data):
                    # External domain belief — merge for conflict resolution
                    self._merge_belief(data)
                elif isinstance(data, list):
                    # Raw local telemetry
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
        """Wrap a domain-specific payload in the cross-domain belief envelope."""
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
                "model_version": "ctt-phase7",
            }
        }

    def _validate_belief(self, msg: dict) -> bool:
        """Validate incoming belief envelope without schema lock-in."""
        if not isinstance(msg, dict):
            return False
        for field in BELIEF_REQUIRED_FIELDS:
            if field not in msg:
                return False
        meta = msg.get("meta", {})
        for field in BELIEF_META_FIELDS:
            if field not in meta:
                return False
        # Reject stale beliefs (> 5 min TTL)
        try:
            ts = datetime.fromisoformat(meta["timestamp"].replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - ts).total_seconds() > 300:
                return False
        except Exception:
            return False
        return True

    def _merge_belief(self, belief: dict):
        """Merge an external belief into the local window for conflict resolution."""
        domain = belief["meta"]["domain_id"]
        corridor = belief["meta"]["corridor_id"]
        payload = belief["payload"]
        # Store in window keyed by domain+corridor for later conflict resolution
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
                # Phase 7: Wrap policy in belief envelope for cross-domain federation
                belief = self._wrap_belief(policy, corridor_id="national")
                self.policy_pub.send_string(json.dumps(belief))
                print(f"[FederationBridge] EMITTED belief envelope: pressure_cap=75.0")
            except Exception as e:
                print(f"[FederationBridge] ZMQ publish failed: {e}")

    def stop(self):
        self._running = False

if __name__ == "__main__":
    bridge = FederationBridge()
    try:
        bridge.run()
    except KeyboardInterrupt:
        print("
🛑 Federation bridge stopping...")
        bridge.stop()
    except Exception as e:
        import traceback
        print(f"
💥 Fatal: {e}")
        traceback.print_exc()
        bridge.stop()