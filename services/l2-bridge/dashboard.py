"""
services/l2-bridge/dashboard.py

CTT L2 Dashboard — subscribes to C++ engine telemetry on port 5555.
"""
import zmq
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "config"))
from ports import ZMQ_PORTS

def run_dashboard():
    context = zmq.Context()
    subscriber = context.socket(zmq.SUB)
    subscriber.connect(ZMQ_PORTS["L1_TELEMETRY_SUB"])
    subscriber.setsockopt_string(zmq.SUBSCRIBE, "")

    print("🚀 CTT L2 Dashboard Active")
    print(f"   Listening: {ZMQ_PORTS['L1_TELEMETRY_SUB']}")
    print("   Press Ctrl+C to stop.")

    fleet_stats = {
        "total_agents": 0,
        "green_agents": 0,
        "legacy_agents": 0,
        "avg_adversarial_pressure": 0.0
    }

    try:
        while True:
            message = subscriber.recv_string()
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                continue

            if isinstance(data, list):
                fleet_stats["total_agents"] = len(data)
                fleet_stats["green_agents"] = sum(1 for a in data if a.get("is_decarbonized"))
                fleet_stats["legacy_agents"] = fleet_stats["total_agents"] - fleet_stats["green_agents"]

                pressures = [a.get("adversarial_pressure", 0) for a in data]
                fleet_stats["avg_adversarial_pressure"] = sum(pressures) / len(pressures) if pressures else 0

            os.system('cls' if os.name == 'nt' else 'clear')
            print("--- CTT Macro Fleet Status ---")
            print(f"Total Trucks:  {fleet_stats['total_agents']}")
            print(f"Green State:   {fleet_stats['green_agents']} ✅")
            print(f"Legacy State:  {fleet_stats['legacy_agents']} ⛽")
            print(f"Avg Pressure:  {fleet_stats['avg_adversarial_pressure']:.2f}")
            print(f"Last Update:   {time.strftime('%H:%M:%S')}")
            print("------------------------------")

    except KeyboardInterrupt:
        print("\nShutting down Dashboard.")
    finally:
        subscriber.close()
        context.term()

if __name__ == "__main__":
    run_dashboard()