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
