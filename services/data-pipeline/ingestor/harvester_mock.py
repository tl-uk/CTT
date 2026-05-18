"""
services/data-pipeline/ingestor/harvester_mock.py

Mock harvester for development and CI testing.
Generates synthetic SME payloads without external API dependencies.
"""
import zmq
import time
import json
import sys
import os
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "config"))
from ports import ZMQ_PORTS

MOCK_FLEET = [
    {"truck_id": "SME_Volvo_01", "fuel_type": "Diesel", "base_efficiency": 0.72},
    {"truck_id": "Haulier_T-100", "fuel_type": "Diesel", "base_efficiency": 0.65},
    {"truck_id": "Unregistered_HGV_X7", "fuel_type": "Diesel", "base_efficiency": 0.58},
    {"truck_id": "GreenFleet_BEV_09", "fuel_type": "Electric", "base_efficiency": 0.91},
]

def generate_mock_payload():
    agent = random.choice(MOCK_FLEET)
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

def run_harvester():
    context = zmq.Context()
    pub = context.socket(zmq.PUB)
    pub.bind(ZMQ_PORTS["HARVESTER_PUB"])

    print("📡 Mock Harvester Online")
    print(f"   Binding: {ZMQ_PORTS['HARVESTER_PUB']}")
    print(f"   Fleet: {len(MOCK_FLEET)} agents")

    # Slow-joiner guard: allow interpreter SUB to connect before first message
    time.sleep(0.5)

    try:
        while True:
            data = generate_mock_payload()
            pub.send_string(json.dumps(data))
            print(f"   → {data['truck_id']} | efficiency={data['efficiency_score']:.2f} | delay={data['delay_minutes']}m")
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n🛑 Mock harvester stopped.")
    finally:
        pub.close()
        context.term()

if __name__ == "__main__":
    run_harvester()