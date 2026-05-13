"""
services/data-pipeline/interpreter/semantic_agent.py

This module implements a "Semantic Interpreter" agent that subscribes to raw data from the harvester 
(e.g., route delays) and transforms it into a format that can be understood by the C++ Simulation Engine. 
The interpreter applies semantic mapping rules to convert domain-specific information (like "route delay") 
into actionable insights (like "pressure increase on HGV category"). This allows the CTT ecosystem to react 
to real-world events in a meaningful way, bridging the gap between raw data and simulation inputs.

"""

import zmq, json

def run_semantic_interpreter():
    context = zmq.Context()
    sub = context.socket(zmq.SUB)
    sub.connect("tcp://localhost:5560")
    sub.setsockopt_string(zmq.SUBSCRIBE, "")
    
    pub = context.socket(zmq.PUB)
    pub.bind("tcp://*:5561")

    print("🧠 Semantic Agent: Mapping SME data to CTT Mindset logic...")

    while True:
        raw = json.loads(sub.recv_string())
        
        # Mapping Logic: (1.0 - efficiency) * 100 = pressure
        pressure_calc = (1.0 - raw.get("efficiency_score", 0.5)) * 100
        
        interpreted = {
            "agent_uuid": raw.get("truck_id"),
            "pressure_delta": pressure_calc
        }
        pub.send_string(json.dumps(interpreted))

if __name__ == "__main__":
    run_semantic_interpreter()
