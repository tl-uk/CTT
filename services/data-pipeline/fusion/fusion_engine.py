"""
services/data-pipeline/fusion/fusion_engine.py

This module implements a "Fusion Engine" that subscribes to interpreted data from the Semantic Interpreter 
and applies multi-source fusion logic to generate perturbations that can be sent to the L1 Engine. The Fusion 
Engine acts as a central hub for combining insights from various data sources (e.g., route delays, weather 
conditions, social media sentiment) and translating them into actionable commands for the simulation. 
This allows the CTT ecosystem to react to complex, real-world scenarios in a more holistic way, enhancing the 
realism and responsiveness of the simulation.

Fusion Engine: subscribes to interpreted data and sends Protobuf perturbations
directly to the C++ L1 Engine.
"""
import zmq
import sys
import os

# Generated protobuf module
sys.path.insert(0, os.path.dirname(__file__))
try:
    from ctt_messages_pb2 import MindsetPerturbation
except ImportError:
    print("❌ ctt_messages_pb2.py not found. Run: protoc --python_out=. api/proto/ctt_messages.proto")
    raise

def run_fusion():
    context = zmq.Context()
    
    # Input: interpreted data from Semantic Agent
    sub = context.socket(zmq.SUB)
    sub.connect("tcp://localhost:5561")
    sub.setsockopt_string(zmq.SUBSCRIBE, "")
    
    # Output: Protobuf perturbations to L1 Engine
    l1_control = context.socket(zmq.PUB)
    l1_control.connect("tcp://localhost:5556")

    print("⚡ Fusion Engine Online (Protobuf mode)")
    print("   Input:  tcp://localhost:5561")
    print("   Output: tcp://localhost:5556")

    while True:
        raw_json = sub.recv_string()
        import json
        data = json.loads(raw_json)
        
        # Build Protobuf message
        p = MindsetPerturbation()
        p.agent_uuid = data.get("agent_uuid", "all_hgv")
        p.pressure_delta = data.get("pressure_delta", 0.0)
        p.source = "Semantic_Interpreter_v1"
        
        # Serialize and send as binary
        l1_control.send(p.SerializeToString())

if __name__ == "__main__":
    run_fusion()