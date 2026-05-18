"""
services/data-pipeline/interpreter/semantic_agent.py

Semantic Interpreter: Maps raw harvester data to CTT Mindset perturbations.
Handles both SME format (efficiency_score) and GTFS format (impact/delay_minutes).
"""
import json
import time  # FIXED: moved to top-level (was trapped inside __main__)
import zmq
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "config"))
from ports import ZMQ_PORTS

def calculate_pressure(raw_data: dict) -> float:
    """
    Convert raw data to adversarial pressure (0-100 scale).

    Priority:
      1. efficiency_score (SME direct feed)
      2. delay_minutes / impact (GTFS-style delay)
      3. Default: 50.0
    """
    if "efficiency_score" in raw_data:
        score = float(raw_data["efficiency_score"])
        return round((1.0 - score) * 100, 1)

    if "impact" in raw_data:
        return float(raw_data["impact"])

    if "delay_minutes" in raw_data:
        return min(100.0, float(raw_data["delay_minutes"]) * 1.5)

    return 50.0

def run_semantic_interpreter():
    context = zmq.Context()

    # Input: raw data from Harvester
    sub = context.socket(zmq.SUB)
    sub.connect(ZMQ_PORTS["HARVESTER_SUB"])
    sub.setsockopt_string(zmq.SUBSCRIBE, "")

    # Output: interpreted data to Fusion
    pub = context.socket(zmq.PUB)
    pub.bind(ZMQ_PORTS["INTERPRETER_PUB"])

    print("🧠 Semantic Interpreter Online")
    print(f"   Input:  {ZMQ_PORTS['HARVESTER_SUB']}")
    print(f"   Output: {ZMQ_PORTS['INTERPRETER_PUB']}")
    print("   Logic:  pressure = (1.0 - efficiency) * 100  |  or delay * 1.5")

    # Slow-joiner guard
    time.sleep(0.5)

    while True:
        try:
            raw = json.loads(sub.recv_string())
        except json.JSONDecodeError as e:
            print(f"   ⚠️  Malformed JSON: {e}")
            continue
        except zmq.ZMQError as e:
            print(f"   ⚠️  ZMQ error: {e}")
            continue

        truck_id = raw.get("truck_id", "all_hgv")
        pressure = calculate_pressure(raw)

        interpreted = {
            "agent_uuid": truck_id,
            "pressure_delta": pressure,
            "source": raw.get("source", "unknown"),
            "route": raw.get("route", "unknown"),
            "raw_efficiency": raw.get("efficiency_score"),
            "raw_delay": raw.get("delay_minutes")
        }

        pub.send_string(json.dumps(interpreted))
        print(f"   → {truck_id:20s} | pressure={pressure:5.1f} | route={interpreted['route']}")

if __name__ == "__main__":
    run_semantic_interpreter()