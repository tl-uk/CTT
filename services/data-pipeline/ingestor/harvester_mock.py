"""
services/data-pipeline/ingestor/harvester_mock.py

Mock harvester for development and CI testing.
Generates synthetic SME payloads without external API dependencies.
"""
import zmq
import time
import json
import sys
import os
import random
import threading
import http.server
import socketserver

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "config"))
from ports import ZMQ_PORTS

# Extended fleet to match C++ engine fleet size
MOCK_FLEET = [
    {"truck_id": "Volvo_eHGV_001",   "fuel_type": "Electric", "base_efficiency": 0.72},
    {"truck_id": "Scania_eHGV_002",  "fuel_type": "Electric", "base_efficiency": 0.68},
    {"truck_id": "DAF_XF_HGV_003",   "fuel_type": "Diesel",   "base_efficiency": 0.55},
    {"truck_id": "MAN_TGX_HGV_004",  "fuel_type": "Hydrogen", "base_efficiency": 0.70},
    {"truck_id": "Renault_ETech_005","fuel_type": "Electric", "base_efficiency": 0.75},
    {"truck_id": "Ford_ETransit_006","fuel_type": "Electric", "base_efficiency": 0.82},
    {"truck_id": "Merc_eSprinter_007","fuel_type": "Electric", "base_efficiency": 0.80},
    {"truck_id": "Vauxhall_Movano_008","fuel_type": "Diesel", "base_efficiency": 0.52},
    {"truck_id": "Class_66_Freight_009","fuel_type": "Diesel", "base_efficiency": 0.45},
    {"truck_id": "Class_88_BiMode_010","fuel_type": "Hybrid", "base_efficiency": 0.60},
    {"truck_id": "Class_323_EMU_011",  "fuel_type": "Electric", "base_efficiency": 0.85},
    {"truck_id": "Stena_Freight_012",  "fuel_type": "Diesel",   "base_efficiency": 0.40},
    {"truck_id": "P&O_Hybrid_Ferry_013","fuel_type": "Hybrid",   "base_efficiency": 0.58},
    {"truck_id": "PedalMe_Cargo_014",  "fuel_type": "Electric", "base_efficiency": 0.90},
    {"truck_id": "Brompton_Cargo_015", "fuel_type": "Electric", "base_efficiency": 0.88},
    {"truck_id": "DHL_CargoDrone_016", "fuel_type": "Electric", "base_efficiency": 0.92},
    {"truck_id": "RoyalMail_Drone_017","fuel_type": "Electric", "base_efficiency": 0.91},
    {"truck_id": "Linde_EFork_018",    "fuel_type": "Electric", "base_efficiency": 0.87},
    {"truck_id": "JCB_Hydrogen_019",   "fuel_type": "Hydrogen", "base_efficiency": 0.78},
    {"truck_id": "Mercedes_Actros_020","fuel_type": "Diesel",   "base_efficiency": 0.53},
    {"truck_id": "Iveco_SWay_021",     "fuel_type": "Hydrogen", "base_efficiency": 0.72},
    {"truck_id": "Volvo_FL_Elec_022",  "fuel_type": "Electric", "base_efficiency": 0.76},
    {"truck_id": "Nissan_eNV200_023",  "fuel_type": "Electric", "base_efficiency": 0.84},
    {"truck_id": "Tesla_Semi_024",     "fuel_type": "Electric", "base_efficiency": 0.79},
    {"truck_id": "BYD_8TT_025",        "fuel_type": "Electric", "base_efficiency": 0.77},
]

ROUTES = [
    "Dover_A2", "M6_Corridor", "A14_Felixstowe", "M25_Orbit",
    "A1_Scotland", "M4_Wales", "A57_SnakePass", "M62_Lancs",
    "A30_Cornwall", "M8_Glasgow", "A9_Highlands", "M50_Ireland",
]

# -----------------------------------------------------------------------------
# Healthcheck HTTP server
# -----------------------------------------------------------------------------
class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"ok","role":"harvester"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

def start_health_server(port=8080):
    with socketserver.TCPServer(("", port), HealthHandler) as httpd:
        httpd.serve_forever()

# -----------------------------------------------------------------------------
# Payload generation
# -----------------------------------------------------------------------------
def generate_mock_payload():
    agent = random.choice(MOCK_FLEET)
    delay_penalty = random.uniform(0.0, 0.35)
    efficiency = max(0.1, agent["base_efficiency"] - delay_penalty)

    return {
        "truck_id": agent["truck_id"],
        "fuel_type": agent["fuel_type"],
        "efficiency_score": round(efficiency, 2),
        "route": random.choice(ROUTES),
        "delay_minutes": int(delay_penalty * 60),
        "source": "mock_harvester",
        "timestamp": time.time()
    }

# -----------------------------------------------------------------------------
# Main Harvester Loop
# -----------------------------------------------------------------------------
def run_harvester():
    context = zmq.Context()
    pub = context.socket(zmq.PUB)
    bind_addr = ZMQ_PORTS.get("HARVESTER_PUB", "tcp://*:5560")
    pub.bind(bind_addr)

    print("📡 Mock Harvester Online")
    print(f"   Binding: {bind_addr}")
    print(f"   Fleet: {len(MOCK_FLEET)} agents")

    # Slow-joiner guard
    time.sleep(0.5)

    try:
        while True:
            data = generate_mock_payload()
            pub.send_string(json.dumps(data))
            print(f"   → {data['truck_id']} | efficiency={data['efficiency_score']:.2f} | delay={data['delay_minutes']}m | route={data['route']}")
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n🛑 Mock harvester stopped.")
    finally:
        pub.close()
        context.term()

if __name__ == "__main__":
    health_thread = threading.Thread(target=start_health_server, args=(8080,), daemon=True)
    health_thread.start()
    print("[Harvester] Healthcheck server on :8080")

    run_harvester()
