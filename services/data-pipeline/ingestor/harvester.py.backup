"""
services/data-pipeline/ingestor/harvester.py

Mock harvester that simulates SME/GTFS data ingestion.
Publishes standardized payloads that the Semantic Interpreter expects.

Phase 2 upgrade path: Replace generate_mock_payload() with fetch_gtfs_realtime().
"""
import zmq
import time
import json
import sys
import os
import random

# Add config to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "config"))
from ports import ZMQ_PORTS

# Mock fleet registry — matches C++ engine test fleet + extras
MOCK_FLEET = [
    {"truck_id": "SME_Volvo_01", "fuel_type": "Diesel", "base_efficiency": 0.72},
    {"truck_id": "Haulier_T-100", "fuel_type": "Diesel", "base_efficiency": 0.65},
    {"truck_id": "Unregistered_HGV_X7", "fuel_type": "Diesel", "base_efficiency": 0.58},
    {"truck_id": "GreenFleet_BEV_09", "fuel_type": "Electric", "base_efficiency": 0.91},
]

def generate_mock_payload():
    """Generate a realistic SME payload with efficiency variance."""
    agent = random.choice(MOCK_FLEET)
    # Simulate route delay impact: delays reduce efficiency
    delay_penalty = random.uniform(0.0, 0.35)
    efficiency = max(0.1, agent["base_efficiency"] - delay_penalty)

    return {
        "truck_id": agent["truck_id"],
        "fuel_type": agent["fuel_type"],
        "efficiency_score": round(efficiency, 2),
        "route": random.choice(["Dover_A2", "M6_Corridor", "A14_Felixstowe", "M25_Orbit"]),
        "delay_minutes": int(delay_penalty * 60),
        "source": "mock_harvester",
        "timestamp": time.time()
    }

def run_harvester(mock_mode=True, external_port=None):
    context = zmq.Context()
    pub = context.socket(zmq.PUB)

    bind_addr = external_port or ZMQ_PORTS["HARVESTER_PUB"]
    pub.bind(bind_addr)

    print(f"📡 Harvester Online")
    print(f"   Mode:     {'MOCK' if mock_mode else 'EXTERNAL'}")
    print(f"   Binding:  {bind_addr}")
    print(f"   Schema:   truck_id, fuel_type, efficiency_score, route, delay_minutes")
    print(f"   Fleet:    {len(MOCK_FLEET)} registered agents")

    # ZMQ slow-joiner guard: allow subscribers to connect before first send
    time.sleep(0.5)

    try:
        while True:
            data = generate_mock_payload()
            pub.send_string(json.dumps(data))
            print(f"   → Sent {data['truck_id']} | efficiency={data['efficiency_score']:.2f} | delay={data['delay_minutes']}m")
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n🛑 Harvester stopped by user.")
    finally:
        pub.close()
        context.term()

if __name__ == "__main__":
    run_harvester()