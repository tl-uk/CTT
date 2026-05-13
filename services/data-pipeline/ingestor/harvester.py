import zmq, time, json
# Mocking an OTP / GTFS Harvester
def run_harvester():
    context = zmq.Context()
    pub = context.socket(zmq.PUB)
    pub.bind("tcp://*:5560")
    while True:
        data = {"type": "delay", "route": "Dover_A2", "impact": 12.5}
        pub.send_string(json.dumps(data))
        time.sleep(5)
if __name__ == "__main__": run_harvester()
