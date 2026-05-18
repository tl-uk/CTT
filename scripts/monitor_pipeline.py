#!/usr/bin/env python3
"""
CTT Live Pipeline Monitor

Monitors the running digital twin WITHOUT stopping any components.
"""
import json
import time
import sys
import os
import subprocess
import zmq

# ---------------------------------------------------------------------------
# Config / Ports
# ---------------------------------------------------------------------------
# Try to import from config, fallback to hardcoded values
TELEMETRY_SUB = "tcp://localhost:5555"
FUSION_PUB = "tcp://localhost:5556"
HARVESTER_PUB = "tcp://*:5560"
INTERPRETER_PUB = "tcp://*:5561"

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "config"))
    from ports import ZMQ_PORTS
    TELEMETRY_SUB = ZMQ_PORTS.get("TELEMETRY_SUB", TELEMETRY_SUB)
    FUSION_PUB = ZMQ_PORTS.get("FUSION_PUB", FUSION_PUB)
    HARVESTER_PUB = ZMQ_PORTS.get("HARVESTER_PUB", HARVESTER_PUB)
    INTERPRETER_PUB = ZMQ_PORTS.get("INTERPRETER_PUB", INTERPRETER_PUB)
except Exception:
    pass  # Use hardcoded fallbacks

# Protobuf import
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "data-pipeline", "fusion"))
    from ctt_messages_pb2 import MindsetPerturbation
except ImportError:
    MindsetPerturbation = None


def check_engine_telemetry(timeout: float = 3.0) -> tuple[bool, list[dict]]:
    """Check if C++ engine is broadcasting telemetry. Returns (alive, agents)."""
    context = zmq.Context()
    sub = context.socket(zmq.SUB)
    sub.connect(TELEMETRY_SUB)
    sub.set(zmq.SUBSCRIBE, b"")
    sub.set(zmq.RCVTIMEO, int(timeout * 1000))

    try:
        msg = sub.recv()
        data = json.loads(msg.decode("utf-8"))
        agents = [a for a in data if isinstance(a, dict)]
        return True, agents
    except zmq.error.Again:
        return False, []
    except Exception as e:
        print(f"   ⚠️  Telemetry parse error: {e}")
        return False, []
    finally:
        sub.close()
        context.term()


def inject_test_perturbation(agent_uuid: str = "Volvo_eHGV_001", delta: float = 5.0) -> bool:
    """Send a test perturbation to the fusion port."""
    if MindsetPerturbation is None:
        print("   ⚠️  Protobuf not available — skipping perturbation injection")
        return False

    context = zmq.Context()
    pub = context.socket(zmq.PUB)
    pub.connect(FUSION_PUB)
    time.sleep(0.3)  # ZMQ slow joiner

    p = MindsetPerturbation()
    p.agent_uuid = agent_uuid
    p.pressure_delta = delta
    p.source = "live_monitor"

    try:
        pub.send(p.SerializeToString())
        return True
    except Exception as e:
        print(f"   ⚠️  Failed to send perturbation: {e}")
        return False
    finally:
        pub.close()
        context.term()


def check_port_occupied(port: int) -> bool:
    """Check if a TCP port is in use."""
    result = subprocess.run(
        ["lsof", "-ti", f":{port}"],
        capture_output=True, text=True
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def monitor_pipeline(duration: int = 10):
    """Monitor the live pipeline for a given duration."""
    print("=" * 60)
    print("CTT Live Pipeline Monitor")
    print("=" * 60)
    print(f"Telemetry: {TELEMETRY_SUB}")
    print(f"Fusion:    {FUSION_PUB}")
    print(f"Monitoring for {duration}s...")
    print()

    # Check 1: Engine telemetry
    print("🔍 Check 1: C++ Engine Telemetry")
    alive, agents = check_engine_telemetry(timeout=3.0)
    if alive:
        agent_names = [a.get("entity_name", "unknown") for a in agents]
        print(f"   ✅ Engine is broadcasting telemetry")
        print(f"   📊 Agents in world: {agent_names}")
        for a in agents[:3]:
            name = a.get("entity_name", "?")
            pressure = a.get("adversarial_pressure", "?")
            mode = a.get("mode", "?")
            print(f"      • {name}: mode={mode}, pressure={pressure}")
    else:
        print(f"   ❌ No telemetry detected — is the engine running?")
        print(f"      Run: make run-engine-fast")
        return False

    print()

    # Check 2: Pipeline flow (inject + observe)
    print("🔍 Check 2: Pipeline Flow (inject test perturbation)")
    target_agent = agents[0].get("entity_name", "Volvo_eHGV_001") if agents else "Volvo_eHGV_001"
    baseline_pressure = agents[0].get("adversarial_pressure", 0.0) if agents else 0.0
    print(f"   🎯 Target agent: {target_agent}")
    print(f"   📊 Baseline pressure: {baseline_pressure}")

    if inject_test_perturbation(agent_uuid=target_agent, delta=5.0):
        print(f"   ✅ Injected +5.0 pressure to {target_agent}")
    else:
        print(f"   ⚠️  Skipping perturbation (protobuf unavailable)")

    # Wait and check telemetry again
    time.sleep(1.5)
    alive, agents_post = check_engine_telemetry(timeout=3.0)
    if alive:
        print(f"   ✅ Telemetry still flowing after perturbation")
        target_post = next(
            (a for a in agents_post if a.get("entity_name") == target_agent),
            None
        )
        if target_post:
            new_pressure = target_post.get("adversarial_pressure", "?")
            print(f"   📊 {target_agent} pressure: {baseline_pressure} → {new_pressure}")
            if isinstance(new_pressure, (int, float)) and isinstance(baseline_pressure, (int, float)):
                if new_pressure > baseline_pressure:
                    print(f"   ✅ Perturbation APPLIED — pressure increased by {new_pressure - baseline_pressure}")
                else:
                    print(f"   ⚠️  Pressure unchanged — perturbation may not have reached agent")
    else:
        print(f"   ❌ Telemetry stopped after perturbation")
        return False

    print()

    # Check 3: Port occupancy
    print("🔍 Check 3: Port Health")
    ports = {
        "Engine Telemetry": (5555, TELEMETRY_SUB),
        "Fusion Perturbations": (5556, FUSION_PUB),
        "Harvester Raw Data": (5560, HARVESTER_PUB),
        "Interpreter Mapped": (5561, INTERPRETER_PUB),
    }
    for name, (port, addr) in ports.items():
        occupied = check_port_occupied(port)
        status = "✅ UP" if occupied else "⬜ DOWN"
        print(f"   {name:25s} | Port {port} | {status} | {addr}")

    print()
    print("=" * 60)
    print("✅ Pipeline health check complete")
    print("=" * 60)
    return True


if __name__ == "__main__":
    monitor_pipeline(duration=10)