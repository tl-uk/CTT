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
