#!/usr/bin/env python3
"""
scripts/test_sme_feed.py

Simulates a non-compliant SME (Small/Medium Enterprise) twin sending 
heterogeneous data to the CTT Ingestor. Tests the mapping logic that 
converts legacy SME schemas into CTT AgentState format.

Usage:
    python scripts/test_sme_feed.py                    # Run all tests
    python scripts/test_sme_feed.py --mode direct      # Test adapter logic only
    python scripts/test_sme_feed.py --mode zmq         # Feed live ZMQ stream
    python scripts/test_sme_feed.py --mode pipeline    # Full pipeline test
"""

import json
import zmq
import time
import random
import sys
import subprocess
from datetime import datetime

# Adjust path to import the ingestor's adapter
sys.path.insert(0, "services/data-pipeline/ingestor")
try:
    from main import sme_legacy_adapter, CTT_AgentState
except ImportError:
    print("❌ Could not import sme_legacy_adapter. Ensure services/data-pipeline/ingestor/main.py exists.")
    sys.exit(1)


def generate_non_compliant_sme_payload():
    """Generates realistic but schema-violating SME data."""
    fuel_types = ["Diesel", "Petrol", "Electric", "Hybrid", "Biodiesel"]
    truck_ids = [
        "SME_Volvo_01", "Haulier_T-100", "Legacy_Scania_99",
        "MomPop_Logistics_42", "Unregistered_HGV_X7"
    ]

    return {
        "truck_id": random.choice(truck_ids),
        "fuel_type": random.choice(fuel_types),
        "efficiency_score": round(random.uniform(0.05, 0.95), 2),
        "timestamp": datetime.now().isoformat(),
        "garbage_field_1": [1, 2, "noise"],
        "garbage_field_2": {"nested": "ignored"},
        "legacy_mode": "FAST_ECO",  # CTT doesn't know this enum
    }


def test_mapping_logic_direct():
    """Test 1: Validate the SME → CTT adapter logic directly."""
    print("=" * 70)
    print("TEST 1: Direct Mapping Logic (No Network)")
    print("=" * 70)

    for i in range(5):
        raw = generate_non_compliant_sme_payload()
        mapped = sme_legacy_adapter(raw)

        # Validate the output is a proper CTT_AgentState
        assert isinstance(mapped, CTT_AgentState),             f"Expected CTT_AgentState, got {type(mapped)}"
        assert mapped.uuid == raw["truck_id"],             f"UUID mismatch: {mapped.uuid} != {raw['truck_id']}"
        assert 0 <= mapped.adversarial_pressure <= 100,             f"Pressure out of range: {mapped.adversarial_pressure}"

        # Validate decarbonization logic
        expected_decarbonized = (raw.get("fuel_type") == "Electric")
        assert mapped.is_decarbonized == expected_decarbonized,             f"Expected is_decarbonized={expected_decarbonized} for fuel_type={raw.get('fuel_type')}"

        print(f"  [{i+1}] {mapped.uuid:25s} | "
              f"pressure={mapped.adversarial_pressure:5.1f} | "
              f"green={mapped.is_decarbonized}")

    print("✅ All mapping validations passed")


def test_zmq_feed():
    """Test 2: Send SME data to a ZMQ endpoint for manual consumption."""
    print("\n" + "=" * 70)
    print("TEST 2: ZMQ Live Feed (Manual Consumer Required)")
    print("=" * 70)

    context = zmq.Context()
    socket = context.socket(zmq.PUB)
    socket.bind("tcp://*:5557")

    print("\nPublishing SME data to tcp://localhost:5557")
    print("To consume, run in another terminal:")
    print('  python -c "import zmq; s=zmq.Context().socket(zmq.SUB); '
          's.connect(\'tcp://localhost:5557\'); s.setsockopt_string(zmq.SUBSCRIBE,\'\'); '
          'print(s.recv_string())"')
    print("Press Ctrl+C to stop.\n")

    try:
        for i in range(50):
            raw = generate_non_compliant_sme_payload()
            payload = json.dumps(raw)
            socket.send_string(payload)

            expected_pressure = (1.0 - raw['efficiency_score']) * 100
            print(f"  [{i+1:02d}] {raw['truck_id']:25s} | "
                  f"efficiency={raw['efficiency_score']:.2f} | "
                  f"expected_pressure={expected_pressure:.1f}")

            time.sleep(1.5)

    except KeyboardInterrupt:
        print("\n\n🛑 Stopped by user.")
    finally:
        socket.close()
        context.term()


def test_pipeline_integration():
    """Test 3: Full pipeline — SME data flows through Ingestor → Interpreter → Fusion → C++."""
    print("\n" + "=" * 70)
    print("TEST 3: Full Pipeline Integration")
    print("=" * 70)

    # Start pipeline components
    print("\nStarting pipeline components...")

    procs = []
    try:
        ingestor = subprocess.Popen(
            [sys.executable, "services/data-pipeline/ingestor/harvester.py"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        procs.append(("ingestor", ingestor))

        interpreter = subprocess.Popen(
            [sys.executable, "services/data-pipeline/interpreter/semantic_agent.py"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        procs.append(("interpreter", interpreter))

        fusion = subprocess.Popen(
            [sys.executable, "services/data-pipeline/fusion/fusion_engine.py"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        procs.append(("fusion", fusion))

        time.sleep(2)  # Let pipeline warm up

        # Send SME data
        context = zmq.Context()
        socket = context.socket(zmq.PUB)
        socket.bind("tcp://*:5557")

        print("\nSending 5 SME payloads through pipeline...")
        print("Flow: SME → Ingestor → Interpreter → Fusion → C++ Engine")

        for i in range(5):
            raw = generate_non_compliant_sme_payload()
            payload = json.dumps(raw)
            socket.send_string(payload)

            expected_pressure = (1.0 - raw['efficiency_score']) * 100
            print(f"  [{i+1}] {raw['truck_id']:25s} | "
                  f"efficiency={raw['efficiency_score']:.2f} | "
                  f"expected_pressure={expected_pressure:.1f}")

            time.sleep(2.0)

        print("\n✅ Pipeline feed complete")
        print("Check C++ engine terminal for perturbation logs")

    except KeyboardInterrupt:
        print("\n\n🛑 Stopped by user.")
    finally:
        socket.close()
        context.term()
        for name, proc in procs:
            print(f"Stopping {name}...")
            proc.terminate()
            proc.wait()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CTT SME Feed Simulator")
    parser.add_argument("--mode", choices=["direct", "zmq", "pipeline", "all"], default="all",
                        help="Test mode: direct, zmq, pipeline, or all")
    args = parser.parse_args()

    if args.mode in ("direct", "all"):
        test_mapping_logic_direct()
    if args.mode in ("zmq", "all"):
        test_zmq_feed()
    if args.mode in ("pipeline", "all"):
        test_pipeline_integration()