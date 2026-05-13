#!/usr/bin/env python3
"""
scripts/test_sme_feed.py

Simulates a non-compliant SME (Small/Medium Enterprise) twin sending 
heterogeneous data to the CTT Ingestor. Tests the mapping logic that 
converts legacy SME schemas into CTT AgentState format.

# From CTT_Project root
python scripts/test_sme_feed.py          # Run both tests
python scripts/test_sme_feed.py --mode direct   # Test adapter logic only
python scripts/test_sme_feed.py --mode zmq      # Feed live ZMQ stream

"""

import json
import zmq
import time
import random
import sys
from datetime import datetime

# Adjust path to import the ingestor's adapter
sys.path.insert(0, "services/data-ingestor")
try:
    from main import sme_legacy_adapter, CTT_AgentState
except ImportError:
    print("❌ Could not import sme_legacy_adapter. Ensure services/data-ingestor/main.py exists.")
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
    """Tests the adapter without network I/O."""
    print("=" * 70)
    print("TEST 1: Direct Mapping Logic (No Network)")
    print("=" * 70)
    
    for i in range(5):
        raw = generate_non_compliant_sme_payload()
        mapped = sme_legacy_adapter(raw)
        
        print(f"\n  SME Raw:")
        print(f"    {json.dumps(raw, indent=4)}")
        print(f"  → CTT Mapped:")
        print(f"    uuid={mapped.uuid}, pressure={mapped.adversarial_pressure:.1f}, "
              f"decarbonized={mapped.is_decarbonized}")


def test_zmq_feed():
    """Sends non-compliant SME JSON to a ZMQ endpoint for live testing."""
    print("\n" + "=" * 70)
    print("TEST 2: ZMQ Live Feed (Send to Ingestor)")
    print("=" * 70)
    
    context = zmq.Context()
    socket = context.socket(zmq.PUB)
    socket.bind("tcp://*:5557")
    
    print("\nPublishing SME data to tcp://localhost:5557")
    print("Start your ingestor listening on this port, or use:")
    print("  python -c \"import zmq; s=zmq.Context().socket(zmq.SUB); "
          "s.connect('tcp://localhost:5557'); s.setsockopt_string(zmq.SUBSCRIBE,''); "
          "print(s.recv_string())\"")
    print("Press Ctrl+C to stop.\n")
    
    try:
        for i in range(50):
            raw = generate_non_compliant_sme_payload()
            payload = json.dumps(raw)
            socket.send_string(payload)
            
            # Derive expected pressure for inline validation
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


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="CTT SME Feed Simulator")
    parser.add_argument("--mode", choices=["direct", "zmq", "both"], default="both",
                        help="Test mode: direct mapping only, ZMQ feed only, or both")
    args = parser.parse_args()
    
    if args.mode in ("direct", "both"):
        test_mapping_logic_direct()
    if args.mode in ("zmq", "both"):
        test_zmq_feed()