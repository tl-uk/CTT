"""
services/data-pipeline/ingestor/harvester.py

This is a mock harvester that simulates the behavior of an OTP / GTFS harvester. 
It uses ZeroMQ to publish messages containing delay information for a specific route every 5 seconds. 
The messages are sent in JSON format, making it easy for subscribers to parse and use the data. 
This setup allows us to test the data pipeline without needing access to real OTP / GTFS data sources.

"""
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
