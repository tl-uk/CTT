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
import threading
import http.server
import socketserver

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "config"))
from ports import ZMQ_PORTS

# Protobuf import
try:
    from ctt_messages_pb2 import MindsetPerturbation  # type: ignore
except ImportError:
    print("❌ ctt_messages_pb2.py not found. Run: make proto")
    raise

# -----------------------------------------------------------------------------
# Healthcheck HTTP server (for Docker healthcheck)
# -----------------------------------------------------------------------------
class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"ok","role":"fusion"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress healthcheck noise

def start_health_server(port=8080):
    with socketserver.TCPServer(("", port), HealthHandler) as httpd:
        httpd.serve_forever()

# -----------------------------------------------------------------------------
# Main Fusion Loop
# -----------------------------------------------------------------------------
def run_fusion():
    context = zmq.Context()

    # Input: interpreted data from Semantic Agent
    sub = context.socket(zmq.SUB)
    interpreter_addr = ZMQ_PORTS.get("INTERPRETER_SUB", "tcp://localhost:5561")
    sub.connect(interpreter_addr)
    sub.setsockopt_string(zmq.SUBSCRIBE, "")

    # Output: Protobuf perturbations to L1 Engine
    l1_control = context.socket(zmq.PUB)
    bind_addr = ZMQ_PORTS.get("L1_PERTURBATION_PUB", "tcp://*:5556")
    l1_control.bind(bind_addr)

    print("⚡ Fusion Engine Online (Protobuf mode)")
    print(f"   Input:  {interpreter_addr}")
    print(f"   Output: {bind_addr}  ← BIND (C++ connects here)")

    # Slow-joiner guard
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
    # Start healthcheck server in background thread
    health_thread = threading.Thread(target=start_health_server, args=(8080,), daemon=True)
    health_thread.start()
    print("[Fusion] Healthcheck server on :8080")

    run_fusion()
