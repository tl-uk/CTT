"""
services/data-pipeline/interpreter/semantic_agent.py

This module implements a "Semantic Interpreter" agent that subscribes to raw data from the harvester 
(e.g., route delays) and transforms it into a format that can be understood by the C++ Simulation Engine. 
The interpreter applies semantic mapping rules to convert domain-specific information (like "route delay") 
into actionable insights (like "pressure increase on HGV category"). This allows the CTT ecosystem to react 
to real-world events in a meaningful way, bridging the gap between raw data and simulation inputs.

"""

import zmq, json
def run_interpreter():
    context = zmq.Context()
    sub = context.socket(zmq.SUB)
    sub.connect("tcp://localhost:5560")
    sub.setsockopt_string(zmq.SUBSCRIBE, "")
    pub = context.socket(zmq.PUB)
    pub.bind("tcp://*:5561")
    while True:
        raw = json.loads(sub.recv_string())
        # Semantic mapping: Route delay -> Pressure increase
        interpreted = {"target_category": "HGV", "pressure_mod": raw['impact'] * 0.5}
        pub.send_string(json.dumps(interpreted))
if __name__ == "__main__": run_interpreter()
