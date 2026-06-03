"""
services/l2-bridge/dashboard.py

CTT Dashboard API — Control plane, telemetry query, and what-if scenario engine.
Exposes REST endpoints for a Grafana or custom frontend.

Phase 6.5 NOTE: Layer2Orchestrator now runs as a separate service
(services/l2-orchestrator/) to avoid port conflicts and enable independent
scaling. This file retains the PolicySubscriber for L5 structural feedback.
"""
import json
import logging
import os
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, asdict
from typing import Optional

import zmq
from flask import Flask, jsonify, request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "config"))
from ports import ZMQ_PORTS, get_resilient_socket
from settings import config

# =============================================================================
# Logging
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ctt.dashboard")

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
    # Phase 7 — Externalities
    current_co2_g_km: float = 0.0
    current_nox_g_km: float = 0.0
    current_pm25_g_km: float = 0.0
    current_noise_db: float = 0.0
    cumulative_co2_kg: float = 0.0
    cumulative_nox_kg: float = 0.0
    cumulative_pm25_kg: float = 0.0
    # Phase 7 — Social impact
    accessibility_score: float = 0.0
    jobs_dependent: int = 0
    deprivation_index: float = 0.0
    equity_exposure: float = 0.0
    serves_deprived_ward: bool = False
    corridor_id: str = ""


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
        self._states_lock = threading.Lock()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        ctx = zmq.Context()
        sub = get_resilient_socket(ctx, zmq.SUB, is_sub=True)

        telemetry_addr = ZMQ_PORTS.get("L1_TELEMETRY_SUB", "tcp://localhost:5555")
        max_retries = 10
        for attempt in range(max_retries):
            try:
                sub.connect(telemetry_addr)
                break
            except zmq.ZMQError:
                logger.warning("Telemetry connect attempt %d/%d failed, retrying...", attempt + 1, max_retries)
                time.sleep(1)

        sub.setsockopt_string(zmq.SUBSCRIBE, "")
        sub.set(zmq.RCVTIMEO, 2000)

        logger.info("Telemetry subscriber connected to %s", telemetry_addr)

        while self._running:
            try:
                msg = sub.recv()
                data = json.loads(msg.decode("utf-8"))
                if isinstance(data, list):
                    recv_time = time.time()
                    with self._states_lock:
                        self._last_message_time = recv_time
                        self._message_count += len(data)
                        for agent in data:
                            self.buffer.append({
                                "time": recv_time,
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
                                timestamp=recv_time,
                                current_co2_g_km=agent.get("current_co2_g_km", 0.0),
                                current_nox_g_km=agent.get("current_nox_g_km", 0.0),
                                current_pm25_g_km=agent.get("current_pm25_g_km", 0.0),
                                current_noise_db=agent.get("current_noise_db", 0.0),
                                cumulative_co2_kg=agent.get("cumulative_co2_kg", 0.0),
                                cumulative_nox_kg=agent.get("cumulative_nox_kg", 0.0),
                                cumulative_pm25_kg=agent.get("cumulative_pm25_kg", 0.0),
                                accessibility_score=agent.get("accessibility_score", 0.0),
                                jobs_dependent=agent.get("jobs_dependent", 0),
                                deprivation_index=agent.get("deprivation_index", 0.0),
                                equity_exposure=agent.get("equity_exposure", 0.0),
                                serves_deprived_ward=agent.get("serves_deprived_ward", False),
                                corridor_id=agent.get("corridor_id", "")
                            )
            except zmq.error.Again:
                continue
            except Exception as e:
                logger.exception("Telemetry error: %s", e)

        sub.close()
        ctx.term()

    def _get_states_snapshot(self) -> dict[str, AgentState]:
        with self._states_lock:
            return dict(self.latest_states)

    def get_latest(self) -> list[dict]:
        states = self._get_states_snapshot()
        return [asdict(state) for state in states.values()]

    def get_history(self, agent_name: Optional[str] = None, limit: int = 100) -> list[dict]:
        # deque iteration is atomic enough for CPython, but slice for safety
        with self._states_lock:
            buf = list(self.buffer)
        if agent_name:
            return [
                entry for entry in buf
                if entry["agent"].get("entity_name") == agent_name
            ][-limit:]
        return buf[-limit:]

    def get_agent_names(self) -> list[str]:
        with self._states_lock:
            return list(self.latest_states.keys())

    def is_healthy(self) -> bool:
        with self._states_lock:
            msg_count = self._message_count
            last_time = self._last_message_time
        if msg_count == 0:
            return False
        return (time.time() - last_time) < 10.0


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
                baseline = self.collector._get_states_snapshot()
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
                pub = get_resilient_socket(ctx, zmq.PUB)
                pub.connect(ZMQ_PORTS["L1_PERTURBATION_SUB"])
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
# Policy Subscriber (Phase 6 — L5 Structural Feedback)
# =============================================================================

class PolicySubscriber:
    def __init__(self):
        self._running = False
        self._thread = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        ctx = zmq.Context()
        sub = get_resilient_socket(ctx, zmq.SUB, is_sub=True)
        policy_addr = ZMQ_PORTS.get("POLICY_SUB", "tcp://localhost:5563")
        try:
            sub.connect(policy_addr)
        except zmq.ZMQError:
            pass
        sub.setsockopt_string(zmq.SUBSCRIBE, "")
        logger.info("PolicySubscriber listening on %s", policy_addr)

        while self._running:
            try:
                msg = sub.recv_string()
                data = json.loads(msg)
                logger.info("Structural policy received: %s", data)
            except zmq.error.Again:
                continue
            except Exception as e:
                logger.exception("PolicySubscriber error: %s", e)
        sub.close()
        ctx.term()

    def stop(self):
        self._running = False


# =============================================================================
# Flask App
# =============================================================================

app = Flask(__name__)
collector = TelemetryCollector()
scenarios = ScenarioEngine(collector)
policy_sub = PolicySubscriber()

# EAGER START
collector.start()
policy_sub.start()
logger.info("Telemetry collector + Policy subscriber started eagerly")


# -----------------------------------------------------------------------------
# Health & Status
# -----------------------------------------------------------------------------

@app.route("/health")
def health():
    try:
        return jsonify({
            "status": "ok",
            "agents_online": len(collector._get_states_snapshot()),
            "telemetry_messages": collector._message_count,
            "telemetry_flowing": collector.is_healthy(),
            "agent_names": collector.get_agent_names()
        })
    except Exception as e:
        logger.exception("Health endpoint error: %s", e)
        return jsonify({"status": "error", "detail": str(e)}), 500


@app.route("/api/v1/agents")
def list_agents():
    try:
        agents = collector.get_latest()
        return jsonify({
            "agents": agents,
            "count": len(agents),
            "timestamp": time.time()
        })
    except Exception as e:
        logger.exception("List agents error: %s", e)
        return jsonify({"status": "error", "detail": str(e)}), 500


@app.route("/api/v1/agents/<agent_name>")
def get_agent(agent_name):
    try:
        state = collector._get_states_snapshot().get(agent_name)
        if state:
            return jsonify(asdict(state))
        return jsonify({"error": "Agent not found"}), 404
    except Exception as e:
        logger.exception("Get agent error: %s", e)
        return jsonify({"status": "error", "detail": str(e)}), 500


@app.route("/api/v1/agents/<agent_name>/history")
def get_agent_history(agent_name):
    try:
        limit = request.args.get("limit", 100, type=int)
        return jsonify({
            "agent": agent_name,
            "history": collector.get_history(agent_name, limit)
        })
    except Exception as e:
        logger.exception("Agent history error: %s", e)
        return jsonify({"status": "error", "detail": str(e)}), 500

# ---------------------------------------------------------------------------
# Phase 7 — Externality & Social Impact Aggregation
# ---------------------------------------------------------------------------

@app.route("/api/v1/externality/summary")
def externality_summary():
    """Aggregate emissions across all agents, by corridor and powertrain."""
    try:
        agents = collector.get_latest()
        summary = {
            "total_co2_kg": 0.0,
            "total_nox_kg": 0.0,
            "total_pm25_kg": 0.0,
            "avg_noise_db": 0.0,
            "by_corridor": {},
            "by_powertrain": {},
            "deprived_ward_exposure": {
                "agents_serving": 0,
                "total_equity_exposure": 0.0,
                "total_jobs_at_risk": 0
            }
        }
        noise_count = 0
        for agent in agents:
            summary["total_co2_kg"] += agent.get("cumulative_co2_kg", 0.0)
            summary["total_nox_kg"] += agent.get("cumulative_nox_kg", 0.0)
            summary["total_pm25_kg"] += agent.get("cumulative_pm25_kg", 0.0)
            n = agent.get("current_noise_db", 0.0)
            if n > 0:
                summary["avg_noise_db"] += n
                noise_count += 1

            corridor = agent.get("corridor_id", "unknown")
            if corridor not in summary["by_corridor"]:
                summary["by_corridor"][corridor] = {
                    "agent_count": 0, "co2_kg": 0.0, "nox_kg": 0.0,
                    "pm25_kg": 0.0, "jobs_dependent": 0
                }
            summary["by_corridor"][corridor]["agent_count"] += 1
            summary["by_corridor"][corridor]["co2_kg"] += agent.get("cumulative_co2_kg", 0.0)
            summary["by_corridor"][corridor]["nox_kg"] += agent.get("cumulative_nox_kg", 0.0)
            summary["by_corridor"][corridor]["pm25_kg"] += agent.get("cumulative_pm25_kg", 0.0)
            summary["by_corridor"][corridor]["jobs_dependent"] += agent.get("jobs_dependent", 0)

            pt = agent.get("powertrain", 0)
            pt_name = {0: "ICE_DIESEL", 1: "ICE_PETROL", 2: "BEV_ELECTRIC",
                       3: "FCEV_HYDROGEN", 4: "HYBRID"}.get(pt, "UNKNOWN")
            if pt_name not in summary["by_powertrain"]:
                summary["by_powertrain"][pt_name] = {"agent_count": 0, "co2_kg": 0.0}
            summary["by_powertrain"][pt_name]["agent_count"] += 1
            summary["by_powertrain"][pt_name]["co2_kg"] += agent.get("cumulative_co2_kg", 0.0)

            if agent.get("serves_deprived_ward", False):
                summary["deprived_ward_exposure"]["agents_serving"] += 1
                summary["deprived_ward_exposure"]["total_equity_exposure"] += agent.get("equity_exposure", 0.0)
                summary["deprived_ward_exposure"]["total_jobs_at_risk"] += agent.get("jobs_dependent", 0)

        if noise_count > 0:
            summary["avg_noise_db"] /= noise_count

        return jsonify(summary)
    except Exception as e:
        logger.exception("Externality summary error: %s", e)
        return jsonify({"status": "error", "detail": str(e)}), 500


@app.route("/api/v1/social-impact/corridor/<corridor_id>")
def corridor_social_impact(corridor_id):
    """Social impact profile for a specific corridor."""
    try:
        agents = collector.get_latest()
        corridor_agents = [a for a in agents if a.get("corridor_id") == corridor_id]
        if not corridor_agents:
            return jsonify({"error": "Corridor not found or no agents assigned"}), 404

        return jsonify({
            "corridor_id": corridor_id,
            "agent_count": len(corridor_agents),
            "avg_accessibility": sum(a.get("accessibility_score", 0) for a in corridor_agents) / len(corridor_agents),
            "total_jobs_dependent": sum(a.get("jobs_dependent", 0) for a in corridor_agents),
            "avg_deprivation": sum(a.get("deprivation_index", 0) for a in corridor_agents) / len(corridor_agents),
            "serves_deprived_ward_count": sum(1 for a in corridor_agents if a.get("serves_deprived_ward")),
            "agents": corridor_agents
        })
    except Exception as e:
        logger.exception("Social impact corridor error: %s", e)
        return jsonify({"status": "error", "detail": str(e)}), 500


# -----------------------------------------------------------------------------
# What-If Scenario API
# -----------------------------------------------------------------------------

@app.route("/api/v1/scenarios", methods=["POST"])
def create_scenario():
    try:
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
    except Exception as e:
        logger.exception("Create scenario error: %s", e)
        return jsonify({"status": "error", "detail": str(e)}), 500


@app.route("/api/v1/scenarios/<scenario_id>/simulate", methods=["POST"])
def simulate_scenario(scenario_id):
    try:
        result = scenarios.simulate(scenario_id)
        if result is None:
            return jsonify({"error": "Scenario not found"}), 404
        return jsonify({
            "scenario_id": scenario_id,
            "status": "simulated",
            "predicted_outcome": result
        })
    except Exception as e:
        logger.exception("Simulate scenario error: %s", e)
        return jsonify({"status": "error", "detail": str(e)}), 500


@app.route("/api/v1/scenarios/<scenario_id>/apply", methods=["POST"])
def apply_scenario(scenario_id):
    try:
        success = scenarios.apply_scenario(scenario_id)
        if not success:
            return jsonify({"error": "Scenario not found or not simulated"}), 400
        return jsonify({
            "scenario_id": scenario_id,
            "status": "applied",
            "message": "Perturbation injected into C++ engine"
        })
    except Exception as e:
        logger.exception("Apply scenario error: %s", e)
        return jsonify({"status": "error", "detail": str(e)}), 500


@app.route("/api/v1/scenarios")
def list_scenarios():
    try:
        return jsonify({"scenarios": scenarios.list_scenarios()})
    except Exception as e:
        logger.exception("List scenarios error: %s", e)
        return jsonify({"status": "error", "detail": str(e)}), 500


# -----------------------------------------------------------------------------
# Control Plane — Direct Perturbation
# -----------------------------------------------------------------------------

@app.route("/api/v1/control/perturb", methods=["POST"])
def direct_perturb():
    """Inject a raw perturbation directly (bypasses scenario engine)."""
    try:
        data = request.get_json() or {}
        agent_uuid = data.get("agent_uuid", "all_hgv")
        pressure_delta = float(data.get("pressure_delta", 0))

        ctx = zmq.Context()
        pub = get_resilient_socket(ctx, zmq.PUB)
        pub.connect(ZMQ_PORTS["L1_PERTURBATION_SUB"])
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
    except Exception as e:
        logger.exception("Direct perturb error: %s", e)
        return jsonify({"status": "error", "detail": str(e)}), 500


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    if not collector._running:
        collector.start()
    if not policy_sub._running:
        policy_sub.start()
    app.run(host="0.0.0.0", port=5001, debug=False)