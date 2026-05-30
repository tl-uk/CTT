"""
services/l2-orchestrator/orchestrator.py

CTT Layer 2 Orchestrator — Standalone Swarm Anomaly Detection Service.
Runs as a separate container for clean failure isolation and independent scaling.

Detects swarm anomalies (3+ agents in same sector hitting pressure >= 80)
and emits tactical policy adjustments to mitigate cascading failures.
"""
import json
import os
import sys
import time
import signal
import threading
from collections import defaultdict, deque

import zmq

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "config"))
from ports import ZMQ_PORTS, get_resilient_socket


class Layer2Orchestrator:
    """
    Subscribes to L1 engine telemetry, detects sector-level swarm anomalies,
    and publishes tactical pressure-cap policies on TACTICAL_PUB (5564).
    """

    ANOMALY_PRESSURE = 80.0
    ANOMALY_COUNT = 3
    WINDOW_SIZE = 60
    COOLDOWN_SECONDS = 30.0  # Suppress repeat alerts for same sector

    def __init__(self):
        self._running = False
        self._thread = None
        self.agent_history = {}
        self.sector_state = {}
        self.last_emission = {}  # sector -> timestamp

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print("[L2 Orchestrator] Started")

    def _run(self):
        ctx = zmq.Context()

        # Subscribe to L1 telemetry
        tele_sub = get_resilient_socket(ctx, zmq.SUB, is_sub=True)
        tele_sub.connect(ZMQ_PORTS.get("L1_TELEMETRY_SUB", "tcp://localhost:5555"))
        tele_sub.setsockopt_string(zmq.SUBSCRIBE, "")
        tele_sub.set(zmq.RCVTIMEO, 2000)

        # Publish tactical policies
        tactical_pub = get_resilient_socket(ctx, zmq.PUB)
        tactical_pub.bind(ZMQ_PORTS.get("TACTICAL_PUB", "tcp://*:5564"))
        time.sleep(0.5)  # slow-joiner guard

        print(f"[L2 Orchestrator] Online | Telemetry sub: {ZMQ_PORTS.get('L1_TELEMETRY_SUB')}"
              f" | Tactical pub: {ZMQ_PORTS.get('TACTICAL_PUB')}")

        while self._running:
            try:
                msg = tele_sub.recv_string()
                agents = json.loads(msg)
                self.update_windows(agents)
                if self.detect_swarm_anomaly():
                    self.emit_tactical_policy(tactical_pub)
            except json.JSONDecodeError as e:
                print(f"[L2 Orchestrator] JSON parse error: {e}")
            except zmq.error.Again:
                continue
            except Exception as e:
                print(f"[L2 Orchestrator] Loop error: {e}")
                time.sleep(0.1)

        tele_sub.close()
        tactical_pub.close()
        ctx.term()
        print("[L2 Orchestrator] Shutdown complete")

    def update_windows(self, agents):
        now = time.time()
        for agent in agents:
            name = agent.get("entity_name", "unknown")
            pressure = agent.get("adversarial_pressure", 0.0)
            lat = agent.get("lat", 0.0)
            lon = agent.get("lon", 0.0)
            sector = f"{int(lat)},{int(lon)}"
            if name not in self.agent_history:
                self.agent_history[name] = deque(maxlen=self.WINDOW_SIZE)
            self.agent_history[name].append((now, pressure, sector))

    def detect_swarm_anomaly(self):
        """Returns sector name if anomaly detected, else None."""
        sector_counts = defaultdict(int)
        for name, window in self.agent_history.items():
            if not window:
                continue
            _, pressure, sector = window[-1]
            if pressure >= self.ANOMALY_PRESSURE:
                sector_counts[sector] += 1
        for sector, count in sector_counts.items():
            if count >= self.ANOMALY_COUNT:
                print(f"[L2 Orchestrator] SWARM ANOMALY in sector {sector}: {count} agents >= {self.ANOMALY_PRESSURE}")
                return sector
        return None

    def _can_emit(self, sector: str) -> bool:
        now = time.time()
        last = self.last_emission.get(sector, 0)
        if (now - last) >= self.COOLDOWN_SECONDS:
            self.last_emission[sector] = now
            return True
        return False
    
    def emit_tactical_policy(self, pub_socket):
        policy = {
            "type": "tactical_pressure_cap",
            "sector": "SE1",
            "pressure_cap": 75.0,
            "source": "layer2_swarm_guard",
            "timestamp": time.time(),
        }
        pub_socket.send_string(json.dumps(policy))
        print(f"[L2 Orchestrator] Tactical policy emitted: {policy}")

    def stop(self):
        self._running = False


def main():
    orch = Layer2Orchestrator()

    def _sigterm_handler(signum, frame):
        print("[L2 Orchestrator] SIGTERM received, shutting down...")
        orch.stop()

    signal.signal(signal.SIGTERM, _sigterm_handler)
    signal.signal(signal.SIGINT, _sigterm_handler)

    orch.start()

    # Keep main thread alive
    while orch._running:
        time.sleep(1)

    if orch._thread:
        orch._thread.join(timeout=5.0)


if __name__ == "__main__":
    main()