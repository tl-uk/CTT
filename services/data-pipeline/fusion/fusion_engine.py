"""
services/data-pipeline/fusion/fusion_engine.py

This module implements a "Fusion Engine" that subscribes to interpreted data from the Semantic Interpreter 
and applies multi-source fusion logic to generate perturbations that can be sent to the L1 Engine. The Fusion 
Engine acts as a central hub for combining insights from various data sources (e.g., route delays, weather 
conditions, social media sentiment) and translating them into actionable commands for the simulation. 
This allows the CTT ecosystem to react to complex, real-world scenarios in a more holistic way, enhancing the 
realism and responsiveness of the simulation.

"""
import zmq, json
def run_fusion():
    context = zmq.Context()
    sub = context.socket(zmq.SUB)
    sub.connect("tcp://localhost:5561")
    sub.setsockopt_string(zmq.SUBSCRIBE, "")
    # Command & Control link to L1 Engine
    l1_control = context.socket(zmq.PUB)
    l1_control.connect("tcp://localhost:5556") 
    while True:
        data = json.loads(sub.recv_string())
        # Multi-source fusion logic here
        perturbation = {"agent_uuid": "all_hgv", "delta": data['pressure_mod']}
        l1_control.send_string(json.dumps(perturbation))
if __name__ == "__main__": run_fusion()
