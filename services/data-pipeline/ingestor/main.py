"""
services/data-pipeline/ingestor/main.py

This module serves as the "Intelligent Ingestor" for the CTT ecosystem. It is responsible for receiving 
heterogeneous data from various sources (e.g., SME Twins, external APIs), transforming it into the internal 
schema expected by the C++ Simulation Engine, and then propagating it through the CTT communication channels 
(e.g., ZMQ, Kafka).
"""
from pydantic import BaseModel
import json
import zmq

# 1. The CTT Internal Schema (What your C++ Engine expects)
class CTT_AgentState(BaseModel):
    uuid: str
    adversarial_pressure: float
    is_decarbonized: bool

# 2. An Adapter for a "Non-Compliant" SME Twin
def sme_legacy_adapter(raw_data):
    """
    SME Twin sends: {"truck_id": "T-100", "fuel_type": "Diesel", "efficiency_score": 0.4}
    We need to map 'efficiency_score' to 'adversarial_pressure'.
    """
    # Logic: Lower efficiency = Higher adversarial pressure
    pressure = (1.0 - raw_data.get("efficiency_score", 0.5)) * 100
    
    return CTT_AgentState(
        uuid=raw_data.get("truck_id"),
        adversarial_pressure=pressure,
        is_decarbonized=(raw_data.get("fuel_type") == "Electric")
    )

def run_ingestor():
    # Setup ZMQ to push to the C++ Engine (or Kafka)
    context = zmq.Context()
    sender = context.socket(zmq.PUB)
    sender.bind("tcp://*:5556") # Internal CTT bus

    print("📥 Intelligent Ingestor Online. Waiting for heterogeneous data...")

    # Simulated incoming data from a non-compliant SME
    incoming_junk = {"truck_id": "SME_Volvo_01", "fuel_type": "Diesel", "efficiency_score": 0.2}

    # Transform
    clean_data = sme_legacy_adapter(incoming_junk)
    
    # Push to the CTT ecosystem
    sender.send_string(clean_data.json())
    print(f"Propagated normalized state: {clean_data.uuid}")

if __name__ == "__main__":
    run_ingestor()