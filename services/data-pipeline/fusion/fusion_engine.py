"""
services/data-pipeline/fusion/fusion_engine.py

Fusion Engine: Subscribes to interpreted data, serializes Protobuf perturbations,
and broadcasts to the C++ L1 Engine.

CRITICAL: This module BINDS a PUB socket on port 5556.
The C++ engine SUB connects to this address.
"""
import zmq
import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "config"))
from ports import ZMQ_PORTS

# Protobuf import
try:
    from ctt_messages_pb2 import MindsetPerturbation  # type: ignore
except ImportError:
    print("❌ ctt_messages_pb2.py not found. Run: make proto")
    raise

def run_fusion():
    context = zmq.Context()

    # Input: interpreted data from Semantic Agent
    sub = context.socket(zmq.SUB)
    sub.connect(ZMQ_PORTS["INTERPRETER_SUB"])
    sub.setsockopt_string(zmq.SUBSCRIBE, "")

    # Output: Protobuf perturbations to L1 Engine
    l1_control = context.socket(zmq.PUB)
    l1_control.bind(ZMQ_PORTS["L1_PERTURBATION_PUB"])

    print("⚡ Fusion Engine Online (Protobuf mode)")
    print(f"   Input:  {ZMQ_PORTS['INTERPRETER_SUB']}")
    print(f"   Output: {ZMQ_PORTS['L1_PERTURBATION_PUB']}  ← BIND (C++ connects here)")

    # Slow-joiner guard: in container networks 0.5s is usually sufficient,
    # but ZMQ connections are async. Sleep allows peers to handshake.
    time.sleep(0.5)

    while True:
        try:
            raw_json = sub.recv_string()
            data = json.loads(raw_json)
        except (json.JSONDecodeError, zmq.ZMQError) as e:
            print(f"   ⚠️  Receive error: {e}")
            continue

        # Build Protobuf message
        p = MindsetPerturbation()
        p.agent_uuid = data.get("agent_uuid", "all_hgv")
        p.pressure_delta = float(data.get("pressure_delta", 0.0))
        p.source = data.get("source", "fusion_engine")

        # Serialize and send as binary
        serialized = p.SerializeToString()
        l1_control.send(serialized)

        print(f"   → Protobuf sent | agent={p.agent_uuid} | delta={p.pressure_delta:.1f} | bytes={len(serialized)}")

if __name__ == "__main__":
    run_fusion()