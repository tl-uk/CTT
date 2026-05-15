"""
services/data-pipeline/ingestor/main.py

DEPRECATED — Intelligent Ingestor (direct-to-engine bypass).
This file is kept for reference but is NOT part of the standard pipeline.
The standard flow is: harvester → interpreter → fusion → C++ engine.

If you must use this direct path, it now binds to port 5562 to avoid
conflicting with the Fusion Engine on 5556.
"""
import json
import zmq
import sys
import os
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "config"))
from ports import ZMQ_PORTS

warnings.warn(
    "main.py is deprecated. Use the full pipeline (harvester → interpreter → fusion). "
    "This direct ingestor bypasses semantic mapping and fusion logic.",
    DeprecationWarning,
    stacklevel=2
)

from pydantic import BaseModel

class CTT_AgentState(BaseModel):
    uuid: str
    adversarial_pressure: float
    is_decarbonized: bool

def sme_legacy_adapter(raw_data):
    pressure = (1.0 - raw_data.get("efficiency_score", 0.5)) * 100
    return CTT_AgentState(
        uuid=raw_data.get("truck_id"),
        adversarial_pressure=pressure,
        is_decarbonized=(raw_data.get("fuel_type") == "Electric")
    )

def run_ingestor():
    context = zmq.Context()
    sender = context.socket(zmq.PUB)
    sender.bind(ZMQ_PORTS["LEGACY_INGESTOR_PUB"])

    print("📥 LEGACY Ingestor Online (DEPRECATED)")
    print(f"   Binding: {ZMQ_PORTS['LEGACY_INGESTOR_PUB']}")
    print("   WARNING: This bypasses interpreter + fusion. Use harvester.py instead.")

    incoming = {"truck_id": "SME_Volvo_01", "fuel_type": "Diesel", "efficiency_score": 0.2}
    clean_data = sme_legacy_adapter(incoming)

    sender.send_string(clean_data.json())
    print(f"Propagated normalized state: {clean_data.uuid}")

if __name__ == "__main__":
    run_ingestor()