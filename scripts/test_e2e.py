#!/usr/bin/env python3
"""
scripts/test_e2e.py

End-to-end pipeline verification for CTT.

Modes:
  --mode standalone : Starts interpreter + fusion, acts as harvester, verifies via telemetry
  --mode inject     : Assumes all components running; just injects test payloads

This test verifies:
  1. Data flows: harvester → interpreter → fusion → C++ engine
  2. C++ engine applies perturbations (observed via telemetry on 5555)
  3. No port conflicts or ZMQ topology errors

Usage:
  Terminal 1: make run-engine
  Terminal 2: python scripts/test_e2e.py --mode standalone
"""
import argparse
import json
import os
import subprocess
import sys
import time
import signal
import zmq

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "config"))
from ports import ZMQ_PORTS

# Test payloads — must match what interpreter expects
TEST_PAYLOADS = [
    {"truck_id": "Volvo_eHGV_001", "fuel_type": "Diesel", "efficiency_score": 0.69, "route": "Test_Route_A", "source": "e2e_test"},
    {"truck_id": "all_hgv", "fuel_type": "Diesel", "efficiency_score": 0.42, "route": "Test_Route_B", "source": "e2e_test"},
    {"truck_id": "Volvo_eHGV_001", "fuel_type": "Diesel", "efficiency_score": 0.15, "route": "Test_Route_C", "source": "e2e_test"},
]

def wait_for_port(port: int, timeout: float = 5.0, host: str = "localhost") -> bool:
    """Poll until a TCP port is accepting connections."""
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            time.sleep(0.2)
    return False

def kill_processes(procs):
    """Gracefully terminate subprocesses."""
    for name, proc in procs:
        print(f"\n🛑 Stopping {name} (PID {proc.pid})...")
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

def run_standalone_test():
    """Full test: start pipeline components, inject data, verify via telemetry."""
    print("=" * 70)
    print("CTT End-to-End Pipeline Test (Standalone Mode)")
    print("=" * 70)
    print("\nPre-flight checks...")

    # Check C++ engine telemetry port is alive
    if not wait_for_port(5555, timeout=3.0):
        print("❌ C++ Engine not detected on port 5555. Run 'make run-engine' first.")
        sys.exit(1)
    print("✅ C++ Engine telemetry detected on port 5555")

    # Check no existing pipeline processes that would cause port conflicts
    for port in [5560, 5561]:
        if wait_for_port(port, timeout=0.5):
            print(f"⚠️  Port {port} already in use. Run 'make stop-pipeline' first.")
            sys.exit(1)
    print("✅ Pipeline ports 5560/5561 are free")

    # Start interpreter and fusion as subprocesses
    procs = []
    root = os.path.dirname(os.path.dirname(__file__))

    try:
        interpreter = subprocess.Popen(
            [sys.executable, os.path.join(root, "services", "data-pipeline", "interpreter", "semantic_agent.py")],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env={**os.environ, "PYTHONPATH": os.path.join(root, "services", "config")}
        )
        procs.append(("interpreter", interpreter))

        fusion = subprocess.Popen(
            [sys.executable, os.path.join(root, "services", "data-pipeline", "fusion", "fusion_engine.py")],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env={**os.environ, "PYTHONPATH": os.path.join(root, "services", "config")}
        )
        procs.append(("fusion", fusion))

        # Wait for components to bind their ports
        print("\n⏳ Waiting for pipeline components to bind ports...")
        if not wait_for_port(5561, timeout=5.0):
            print("❌ Interpreter failed to bind port 5561")
            sys.exit(1)
        if not wait_for_port(5556, timeout=5.0):
            print("❌ Fusion failed to bind port 5556")
            sys.exit(1)
        print("✅ Interpreter + Fusion are online")

        # Setup ZMQ: act as harvester + telemetry listener
        context = zmq.Context()

        # PUB on 5560 (replacing harvester)
        harvester_pub = context.socket(zmq.PUB)
        harvester_pub.bind(ZMQ_PORTS["HARVESTER_PUB"])

        # SUB on 5555 (C++ telemetry)
        telemetry_sub = context.socket(zmq.SUB)
        telemetry_sub.connect(ZMQ_PORTS["L1_TELEMETRY_SUB"])
        telemetry_sub.setsockopt_string(zmq.SUBSCRIBE, "")

        # ZMQ slow-joiner: allow connections to establish
        time.sleep(1.0)

        print("\n📡 Sending test payloads through pipeline...")
        print(f"{'#':>3} | {'Agent':20s} | {'Efficiency':>10s} | {'Expected ΔP':>12s}")
        print("-" * 55)

        expected_pressures = {}
        for i, payload in enumerate(TEST_PAYLOADS, 1):
            expected_pressure = round((1.0 - payload["efficiency_score"]) * 100, 1)
            expected_pressures[payload["truck_id"]] = expected_pressure

            harvester_pub.send_string(json.dumps(payload))
            print(f"{i:>3} | {payload['truck_id']:20s} | {payload['efficiency_score']:>10.2f} | {expected_pressure:>12.1f}")
            time.sleep(1.5)  # Allow pipeline processing + engine tick

        print("\n⏳ Waiting for telemetry feedback (up to 5s)...")

        # Collect telemetry for up to 5 seconds
        deadline = time.time() + 5.0
        telemetry_found = False
        agent_states = {}

        while time.time() < deadline:
            try:
                msg = telemetry_sub.recv_string(flags=zmq.NOBLOCK)
                data = json.loads(msg)
                if isinstance(data, list):
                    for agent in data:
                        agent_states[agent.get("entity_name", "unknown")] = agent
                    telemetry_found = True
                    # Check if we see our test agents with non-zero pressure
                    break
            except zmq.Again:
                time.sleep(0.1)

        print("\n" + "=" * 70)
        print("RESULTS")
        print("=" * 70)

        if not telemetry_found:
            print("❌ NO TELEMETRY RECEIVED")
            print("   Possible causes:")
            print("   • C++ engine not broadcasting (check make run-engine)")
            print("   • ZMQ SUB failed to connect to 5555")
            print("   • Pipeline dropped messages (check component logs below)")
            success = False
        else:
            print("✅ Telemetry received from C++ engine")
            print(f"   Agents in world: {list(agent_states.keys())}")

            # Check if Volvo_eHGV_001 (the C++ test fleet agent) has pressure > 0
            volvo = agent_states.get("Volvo_eHGV_001", {})
            pressure = volvo.get("adversarial_pressure", 0)

            if pressure > 0:
                print(f"✅ Perturbation APPLIED — Volvo_eHGV_001 pressure = {pressure:.1f}")
                success = True
            else:
                print(f"❌ Perturbation NOT APPLIED — Volvo_eHGV_001 pressure = {pressure:.1f}")
                print("   The pipeline delivered data but the C++ engine may not have parsed Protobuf.")
                success = False

        # Print component logs for diagnosis
        print("\n--- Interpreter Log ---")
        interpreter.stdout.close()
        print("(see process output)")

        print("\n--- Fusion Log ---")
        fusion.stdout.close()
        print("(see process output)")

        harvester_pub.close()
        telemetry_sub.close()
        context.term()

        if success:
            print("\n🎉 END-TO-END TEST PASSED")
            sys.exit(0)
        else:
            print("\n💥 END-TO-END TEST FAILED")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\n🛑 Test interrupted by user.")
    finally:
        kill_processes(procs)

def run_inject_test():
    """Lightweight: assumes everything running, just injects payloads."""
    print("=" * 70)
    print("CTT Pipeline Inject Test")
    print("=" * 70)

    context = zmq.Context()
    pub = context.socket(zmq.PUB)
    pub.bind(ZMQ_PORTS["HARVESTER_PUB"])
    time.sleep(0.5)

    print("\n📡 Injecting test payloads...")
    for payload in TEST_PAYLOADS:
        pub.send_string(json.dumps(payload))
        print(f"   → {payload['truck_id']} | efficiency={payload['efficiency_score']}")
        time.sleep(1.0)

    print("\n✅ Inject complete. Check C++ engine terminal for perturbation logs.")
    pub.close()
    context.term()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CTT End-to-End Pipeline Test")
    parser.add_argument("--mode", choices=["standalone", "inject"], default="standalone",
                        help="standalone: full test with subprocesses | inject: just send data")
    args = parser.parse_args()

    if args.mode == "standalone":
        run_standalone_test()
    else:
        run_inject_test()
