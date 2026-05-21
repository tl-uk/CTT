"""
services/l2-bridge/dashboard.py

CTT Dashboard API — Control plane, telemetry query, and what-if scenario engine.
Exposes REST endpoints for a Grafana or custom frontend.
"""
import json
import os
import sys
import time
from collections import deque
from dataclasses import dataclass, asdict
from typing import Optional

import zmq
from flask import Flask, jsonify, request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "config"))
from ports import ZMQ_PORTS

# =============================================================================
# Configuration
# =============================================================================

TELEMETRY_BUFFER_SIZE = 1000
SCENARIO_HISTORY_SIZE = 50

# =============================================================================
# Data Models
# =============================================================================

@dataclass
class AgentState:
    entity_name: str
    mode: int
    powertrain: int
    energy_pct: float
    lat: float
    lon: float
    adversarial_pressure: float
    is_decarbonized: bool
    timestamp: float


@dataclass
class WhatIfScenario:
    scenario_id: str
    description: str
    parameter_changes: dict
    predicted_outcome: Optional[dict]
    applied_at: Optional[float]
    status: str  # "draft", "simulated", "applied"


# =============================================================================
# Telemetry Collector (Background Thread)
# =============================================================================

class TelemetryCollector:
    def __init__(self):
        self.buffer: deque[dict] = deque(maxlen=TELEMETRY_BUFFER_SIZE)
        self.latest_states: dict[str, AgentState] = {}
        self._running = False
        self._thread = None
        self._last_message_time: float = 0.0
        self._message_count: int = 0

    def start(self):
        import threading
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        ctx = zmq.Context()
        sub = ctx.socket(zmq.SUB)

        # Connect to engine telemetry with retry
        telemetry_addr = ZMQ_PORTS.get("L1_TELEMETRY_SUB", "tcp://localhost:5555")
        max_retries = 10
        for attempt in range(max_retries):
            try:
                sub.connect(telemetry_addr)
                break
            except zmq.ZMQError:
                print(f"[Dashboard] Telemetry connect attempt {attempt+1}/{max_retries} failed, retrying...")
                time.sleep(1)

        sub.setsockopt_string(zmq.SUBSCRIBE, "")
        sub.set(zmq.RCVTIMEO, 2000)

        print(f"[Dashboard] Telemetry subscriber connected to {telemetry_addr}")

        while self._running:
            try:
                msg = sub.recv()
                self._last_message_time = time.time()
                self._message_count += 1
                data = json.loads(msg.decode("utf-8"))
                if isinstance(data, list):
                    for agent in data:
                        self.buffer.append({
                            "time": time.time(),
                            "agent": agent
                        })
                        self.latest_states[agent.get("entity_name", "unknown")] = AgentState(
                            entity_name=agent.get("entity_name", "unknown"),
                            mode=agent.get("mode", 0),
                            powertrain=agent.get("powertrain", 0),
                            energy_pct=agent.get("energy_pct", 0.0),
                            lat=agent.get("lat", 0.0),
                            lon=agent.get("lon", 0.0),
                            adversarial_pressure=agent.get("adversarial_pressure", 0.0),
                            is_decarbonized=agent.get("is_decarbonized", False),
                            timestamp=time.time()
                        )
            except zmq.error.Again:
                continue
            except Exception as e:
                print(f"[Dashboard] Telemetry error: {e}")

        sub.close()
        ctx.term()

    def get_latest(self) -> list[dict]:
        return [asdict(state) for state in self.latest_states.values()]

    def get_history(self, agent_name: Optional[str] = None, limit: int = 100) -> list[dict]:
        if agent_name:
            return [
                entry for entry in self.buffer
                if entry["agent"].get("entity_name") == agent_name
            ][-limit:]
        return list(self.buffer)[-limit:]

    def get_agent_names(self) -> list[str]:
        return list(self.latest_states.keys())

    def is_healthy(self) -> bool:
        """Check if telemetry is flowing (received message within last 10s)."""
        if self._message_count == 0:
            return False
        return (time.time() - self._last_message_time) < 10.0


# =============================================================================
# What-If Scenario Engine
# =============================================================================

class ScenarioEngine:
    def __init__(self, collector: TelemetryCollector):
        self.collector = collector
        self.scenarios: deque[WhatIfScenario] = deque(maxlen=SCENARIO_HISTORY_SIZE)

    def create_scenario(self, description: str, parameter_changes: dict) -> WhatIfScenario:
        import uuid
        scenario = WhatIfScenario(
            scenario_id=str(uuid.uuid4())[:8],
            description=description,
            parameter_changes=parameter_changes,
            predicted_outcome=None,
            applied_at=None,
            status="draft"
        )
        self.scenarios.append(scenario)
        return scenario

    def simulate(self, scenario_id: str) -> Optional[dict]:
        for sc in self.scenarios:
            if sc.scenario_id == scenario_id:
                baseline = self.collector.latest_states
                predicted = {}
                for agent_name, state in baseline.items():
                    delta = sc.parameter_changes.get("pressure_delta", 0)
                    new_pressure = min(100.0, state.adversarial_pressure + delta)
                    predicted[agent_name] = {
                        "current_pressure": state.adversarial_pressure,
                        "predicted_pressure": new_pressure,
                        "would_decarbonize": new_pressure >= 15.0
                    }
                sc.predicted_outcome = predicted
                sc.status = "simulated"
                return predicted
        return None

    def apply_scenario(self, scenario_id: str) -> bool:
        """Send perturbation to C++ engine via ZMQ."""
        for sc in self.scenarios:
            if sc.scenario_id == scenario_id and sc.status == "simulated":
                ctx = zmq.Context()
                pub = ctx.socket(zmq.PUB)
                pub.bind(ZMQ_PORTS["L1_PERTURBATION_PUB"])

                time.sleep(0.3)  # slow-joiner guard

                for agent_name, outcome in (sc.predicted_outcome or {}).items():
                    payload = {
                        "agent_uuid": agent_name,
                        "pressure_delta": sc.parameter_changes.get("pressure_delta", 0),
                        "source": "dashboard_scenario"
                    }
                    pub.send_string(json.dumps(payload))

                pub.close()
                ctx.term()

                sc.applied_at = time.time()
                sc.status = "applied"
                return True
        return False

    def list_scenarios(self) -> list[dict]:
        return [
            {
                "scenario_id": sc.scenario_id,
                "description": sc.description,
                "status": sc.status,
                "applied_at": sc.applied_at
            }
            for sc in self.scenarios
        ]


# =============================================================================
# Flask App
# =============================================================================

app = Flask(__name__)
collector = TelemetryCollector()
scenarios = ScenarioEngine(collector)

# EAGER START: Start collector immediately at module load time
# This ensures the healthcheck passes even before first HTTP request
collector.start()
print("[Dashboard] Telemetry collector started eagerly")


# -----------------------------------------------------------------------------
# Health & Status
# -----------------------------------------------------------------------------

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "agents_online": len(collector.latest_states),
        "telemetry_messages": collector._message_count,
        "telemetry_flowing": collector.is_healthy(),
        "agent_names": collector.get_agent_names()
    })


@app.route("/api/v1/agents")
def list_agents():
    agents = collector.get_latest()
    return jsonify({
        "agents": agents,
        "count": len(agents),
        "timestamp": time.time()
    })


@app.route("/api/v1/agents/<agent_name>")
def get_agent(agent_name):
    state = collector.latest_states.get(agent_name)
    if state:
        return jsonify(asdict(state))
    return jsonify({"error": "Agent not found"}), 404


@app.route("/api/v1/agents/<agent_name>/history")
def get_agent_history(agent_name):
    limit = request.args.get("limit", 100, type=int)
    return jsonify({
        "agent": agent_name,
        "history": collector.get_history(agent_name, limit)
    })


# -----------------------------------------------------------------------------
# What-If Scenario API
# -----------------------------------------------------------------------------

@app.route("/api/v1/scenarios", methods=["POST"])
def create_scenario():
    data = request.get_json() or {}
    sc = scenarios.create_scenario(
        description=data.get("description", "Untitled"),
        parameter_changes=data.get("parameter_changes", {})
    )
    return jsonify({
        "scenario_id": sc.scenario_id,
        "status": sc.status,
        "message": "Scenario created. Run /simulate to preview."
    }), 201


@app.route("/api/v1/scenarios/<scenario_id>/simulate", methods=["POST"])
def simulate_scenario(scenario_id):
    result = scenarios.simulate(scenario_id)
    if result is None:
        return jsonify({"error": "Scenario not found"}), 404
    return jsonify({
        "scenario_id": scenario_id,
        "status": "simulated",
        "predicted_outcome": result
    })


@app.route("/api/v1/scenarios/<scenario_id>/apply", methods=["POST"])
def apply_scenario(scenario_id):
    success = scenarios.apply_scenario(scenario_id)
    if not success:
        return jsonify({"error": "Scenario not found or not simulated"}), 400
    return jsonify({
        "scenario_id": scenario_id,
        "status": "applied",
        "message": "Perturbation injected into C++ engine"
    })


@app.route("/api/v1/scenarios")
def list_scenarios():
    return jsonify({"scenarios": scenarios.list_scenarios()})


# -----------------------------------------------------------------------------
# Control Plane — Direct Perturbation
# -----------------------------------------------------------------------------

@app.route("/api/v1/control/perturb", methods=["POST"])
def direct_perturb():
    """Inject a raw perturbation directly (bypasses scenario engine)."""
    data = request.get_json() or {}
    agent_uuid = data.get("agent_uuid", "all_hgv")
    pressure_delta = float(data.get("pressure_delta", 0))

    ctx = zmq.Context()
    pub = ctx.socket(zmq.PUB)
    pub.bind(ZMQ_PORTS["L1_PERTURBATION_PUB"])
    time.sleep(0.3)

    payload = {
        "agent_uuid": agent_uuid,
        "pressure_delta": pressure_delta,
        "source": "dashboard_direct"
    }
    pub.send_string(json.dumps(payload))

    pub.close()
    ctx.term()

    return jsonify({
        "agent_uuid": agent_uuid,
        "pressure_delta": pressure_delta,
        "status": "sent"
    })


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    # Already started eagerly above, but ensure it's running
    if not collector._running:
        collector.start()
    app.run(host="0.0.0.0", port=5001, debug=False)