""" 
services/l2-bridge/orchestrator.py

The Layer 2 Orchestrator is responsible for real-time monitoring of agent telemetry,
detecting swarm anomalies (e.g., multiple agents in the same sector hitting high pressure),
and emitting tactical policy adjustments to mitigate cascading failures.
"""
import asyncio
import json
from collections import defaultdict, deque
from ports import ZMQ_PORTS, get_resilient_socket
import zmq.asyncio

# Sliding window configuration
WINDOW_SIZE = 60          # Keep last 60 samples per agent
ANOMALY_PRESSURE = 80.0   # Pressure threshold for anomaly detection
ANOMALY_COUNT = 3         # Minimum agents in same sector to trigger
SECTOR_KEY = "sector"     # JSON field used for sector grouping (fallback: lat/lon bucketing)

class Layer2Orchestrator:
    def __init__(self):
        self.ctx = zmq.asyncio.Context()

        self.tele_sub = get_resilient_socket(self.ctx, zmq.SUB, is_sub=True)
        self.tele_sub.connect(ZMQ_PORTS["L1_TELEMETRY_SUB"])
        self.tele_sub.setsockopt_string(zmq.SUBSCRIBE, "")

        self.policy_pub = get_resilient_socket(self.ctx, zmq.PUB, is_sub=False)
        self.policy_pub.bind(ZMQ_PORTS["POLICY_PUB"])

        self.agent_history = {}   # agent_name -> deque of (timestamp, pressure, sector)
        self.sector_state = {}      # sector -> list of current pressures

    async def run(self):
        print("[L2 Orchestrator] Online | ZMQ async loop active")
        while True:
            try:
                msg = await self.tele_sub.recv_string()
                agents = json.loads(msg)
                self.update_windows(agents)
                if self.detect_swarm_anomaly():
                    await self.emit_tactical_policy()
            except json.JSONDecodeError as e:
                print(f"[L2 Orchestrator] JSON parse error: {e}")
            except Exception as e:
                print(f"[L2 Orchestrator] Loop error: {e}")
                await asyncio.sleep(0.1)

    def update_windows(self, agents):
        """Update sliding windows and sector aggregates."""
        import time
        now = time.time()
        for agent in agents:
            name = agent.get("entity_name", "unknown")
            pressure = agent.get("adversarial_pressure", 0.0)
            # Derive sector from payload if present; else fallback to lat/lon bucket
            sector = agent.get(SECTOR_KEY)
            if sector is None:
                lat = agent.get("lat", 0.0)
                lon = agent.get("lon", 0.0)
                sector = f"{int(lat)},{int(lon)}"

            if name not in self.agent_history:
                self.agent_history[name] = deque(maxlen=WINDOW_SIZE)
            self.agent_history[name].append((now, pressure, sector))

    def detect_swarm_anomaly(self) -> bool:
        """
        Detect if 3+ agents in the same sector simultaneously exceed ANOMALY_PRESSURE.
        This is the 'Schmitt Trigger avalanche' early warning.
        """
        sector_counts = defaultdict(int)
        for name, window in self.agent_history.items():
            if not window:
                continue
            _, pressure, sector = window[-1]  # Most recent sample
            if pressure >= ANOMALY_PRESSURE:
                sector_counts[sector] += 1

        for sector, count in sector_counts.items():
            if count >= ANOMALY_COUNT:
                print(f"[L2 Orchestrator] 🚨 SWARM ANOMALY detected in sector {sector}: {count} agents >= {ANOMALY_PRESSURE}")
                return True
        return False

    async def emit_tactical_policy(self):
        policy = {
            "sector": "SE1",
            "pressure_cap": 75.0,
            "source": "layer2_swarm_guard",
            "timestamp": asyncio.get_event_loop().time(),
        }
        await self.policy_pub.send_string(json.dumps(policy))
        print(f"[L2 Orchestrator] 📤 Tactical policy emitted: {policy}")


if __name__ == "__main__":
    orch = Layer2Orchestrator()
    try:
        asyncio.run(orch.run())
    except KeyboardInterrupt:
        print("\n🛑 L2 Orchestrator stopping...")