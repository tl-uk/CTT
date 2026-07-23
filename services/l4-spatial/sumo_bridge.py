#!/usr/bin/env python3
"""
services/l4-spatial/sumo_bridge.py

Phase 14a: SUMO/libsumo Bridge — MMOG Zone Server

Purpose: Run SUMO as a physics "zone server" for a specific corridor.
Receives Flecs entity state via ZMQ, maps to SUMO vehicles, runs simulation steps,
and publishes SUMO-derived state (congestion, emissions, grid load) back.

MMOG Analogy:
- This is the "physics server" for one zone (corridor)
- Flecs entities = player/NPC avatars
- SUMO = the collision/physics engine
- ZMQ = the network protocol syncing entity state

Architecture:
- ZMQ SUB: Receives Flecs telemetry (tcp://ctt-engine:5555)
- libsumo: Direct C++ API (no TraCI socket overhead)
- ZMQ PUB: Publishes SUMO state (tcp://*:5557) for Flecs to consume
- Kafka: Publishes aggregated corridor metrics (grid load, emissions)

Environment:
- CTT_CORRIDOR_ID: Which corridor this instance serves
- CTT_SUMO_CONFIG: Path to .sumocfg file
- CTT_ZMQ_TELEMETRY: Flecs ZMQ pub address
- CTT_ZMQ_SUMO_PUB: Where to publish SUMO state
"""
import json
import os
import sys
import time
import threading
from collections import defaultdict
from typing import Dict, List, Optional, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "config"))

import zmq
from ports import ZMQ_PORTS, get_resilient_socket

# libsumo imports (uses C++ API directly)
try:
    import libsumo as traci
    HAS_SUMO = True
except ImportError:
    HAS_SUMO = False
    print("[SUMOBridge] libsumo not available — running in mock mode")

# =============================================================================
# Configuration
# =============================================================================

CORRIDOR_ID = os.environ.get("CTT_CORRIDOR_ID", "m20_corridor")
SUMO_CONFIG = os.environ.get("CTT_SUMO_CONFIG", f"/app/deploy/osm-networks/{CORRIDOR_ID}.sumocfg")
ZMQ_TELEMETRY_SUB = os.environ.get("CTT_ZMQ_TELEMETRY", "tcp://ctt-engine:5555")
ZMQ_SUMO_PUB = os.environ.get("CTT_ZMQ_SUMO_PUB", "tcp://*:5557")
KAFKA_BOOTSTRAP = os.environ.get("CTT_KAFKA", "kafka:29092")

# Vehicle class mapping: CTT mode → SUMO vClass
MODE_TO_VCLASS = {
    "diesel": "truck",
    "bev": "evehicle",
    "h2": "truck",
    "rail": "rail",
    "ship": "ship"
}

# =============================================================================
# SUMO Bridge
# =============================================================================

class SUMOBridge:
    def __init__(self):
        self.ctx = zmq.Context()

        # ZMQ: Subscribe to Flecs telemetry
        self.tele_sub = get_resilient_socket(self.ctx, zmq.SUB, is_sub=True)
        self._connect_with_retry(self.tele_sub, ZMQ_TELEMETRY_SUB)
        self.tele_sub.setsockopt_string(zmq.SUBSCRIBE, "")

        # ZMQ: Publish SUMO state back to Flecs
        self.sumo_pub = get_resilient_socket(self.ctx, zmq.PUB, is_sub=False)
        self.sumo_pub.bind(ZMQ_SUMO_PUB)

        # SUMO simulation state
        self.sumo_step = 0
        self.vehicle_map: Dict[str, str] = {}
        self.agent_state: Dict[str, Dict] = {}

        # Kafka producer for corridor metrics
        self.kafka_producer = None
        try:
            from kafka import KafkaProducer
            self.kafka_producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                retries=3
            )
            print(f"[SUMOBridge] Kafka connected to {KAFKA_BOOTSTRAP}")
        except Exception as e:
            print(f"[SUMOBridge] Kafka unavailable: {e}")

        self._running = False
        self.lock = threading.RLock()

        if HAS_SUMO:
            self._init_sumo()
        else:
            print("[SUMOBridge] Mock mode: SUMO simulation disabled")

    def _connect_with_retry(self, socket, address, max_retries=30, delay=2.0):
        for attempt in range(max_retries):
            try:
                socket.connect(address)
                print(f"[SUMOBridge] Connected to {address}")
                return
            except zmq.error.ZMQError as e:
                print(f"[SUMOBridge] Retry {attempt+1}/{max_retries}: {e}")
                time.sleep(delay)
        raise RuntimeError(f"Failed to connect to {address}")

    def _init_sumo(self):
        if not os.path.exists(SUMO_CONFIG):
            print(f"[SUMOBridge] SUMO config not found: {SUMO_CONFIG}")
            print(f"[SUMOBridge] Creating minimal mock network...")
            self._create_mock_network()

        print(f"[SUMOBridge] Starting SUMO with config: {SUMO_CONFIG}")
        traci.start(["sumo", "-c", SUMO_CONFIG, "--step-length", "0.1"])
        print(f"[SUMOBridge] SUMO simulation loaded, step length=100ms")

    def _create_mock_network(self):
        net_dir = os.path.dirname(SUMO_CONFIG)
        os.makedirs(net_dir, exist_ok=True)

        net_file = os.path.join(net_dir, f"{CORRIDOR_ID}.net.xml")
        with open(net_file, "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<net version="1.9">\n')
            f.write('    <location netOffset="0.00,0.00" convBoundary="0.00,0.00,1000.00,0.00"/>\n')
            f.write('    <edge id="E0" from="J0" to="J1">\n')
            f.write('        <lane id="E0_0" index="0" speed="13.89" length="1000.00" shape="0.00,0.00 1000.00,0.00"/>\n')
            f.write('    </edge>\n')
            f.write('    <junction id="J0" type="dead_end" x="0.00" y="0.00"/>\n')
            f.write('    <junction id="J1" type="dead_end" x="1000.00" y="0.00"/>\n')
            f.write('</net>\n')

        rou_file = os.path.join(net_dir, f"{CORRIDOR_ID}.rou.xml")
        with open(rou_file, "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<routes>\n')
            f.write('    <vType id="truck" vClass="truck" maxSpeed="25" accel="1.0" decel="2.0"/>\n')
            f.write('    <vType id="evehicle" vClass="passenger" maxSpeed="25" accel="1.2" decel="2.5" emissionClass="Energy/unknown"/>\n')
            f.write('</routes>\n')

        with open(SUMO_CONFIG, "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<configuration>\n')
            f.write('    <input>\n')
            f.write(f'        <net-file value="{CORRIDOR_ID}.net.xml"/>\n')
            f.write(f'        <route-files value="{CORRIDOR_ID}.rou.xml"/>\n')
            f.write('    </input>\n')
            f.write('    <time>\n')
            f.write('        <step-length value="0.1"/>\n')
            f.write('    </time>\n')
            f.write('</configuration>\n')

    def _parse_telemetry(self, raw_json: str) -> List[Dict]:
        try:
            data = json.loads(raw_json)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    def _sync_flecs_to_sumo(self, agents: List[Dict]):
        if not HAS_SUMO:
            return

        for agent in agents:
            agent_id = agent.get("entity_name", "unknown")
            mode = agent.get("mode", "diesel")
            speed = agent.get("speed_mps", 0.0)

            with self.lock:
                self.agent_state[agent_id] = agent

                if agent_id not in self.vehicle_map:
                    veh_id = f"sumo_{agent_id}"
                    vclass = MODE_TO_VCLASS.get(mode, "truck")
                    try:
                        traci.vehicle.add(veh_id, "route0", typeID=vclass, depart="now")
                        self.vehicle_map[agent_id] = veh_id
                        print(f"[SUMOBridge] Spawned {veh_id} ({vclass}) in {CORRIDOR_ID}")
                    except Exception:
                        pass
                else:
                    veh_id = self.vehicle_map[agent_id]

                try:
                    traci.vehicle.setSpeed(veh_id, speed)
                    current_class = traci.vehicle.getVehicleClass(veh_id)
                    target_class = MODE_TO_VCLASS.get(mode, "truck")
                    if current_class != target_class:
                        traci.vehicle.setVehicleClass(veh_id, target_class)
                        print(f"[SUMOBridge] {veh_id} switched to {target_class}")
                except Exception:
                    pass

    def _sync_sumo_to_flecs(self):
        if not HAS_SUMO:
            return

        corridor_metrics = {
            "corridor_id": CORRIDOR_ID,
            "sumo_step": self.sumo_step,
            "vehicles": {},
            "grid_load_mw": 0.0,
            "total_co2_g": 0.0,
            "total_nox_g": 0.0,
            "mean_speed_mps": 0.0
        }

        try:
            veh_ids = traci.vehicle.getIDList()
            speeds = []
            for vid in veh_ids:
                speed = traci.vehicle.getSpeed(vid)
                speeds.append(speed)
                try:
                    co2 = traci.vehicle.getCO2Emission(vid)
                    nox = traci.vehicle.getNOxEmission(vid)
                    corridor_metrics["total_co2_g"] += co2
                    corridor_metrics["total_nox_g"] += nox
                except:
                    pass

            if speeds:
                corridor_metrics["mean_speed_mps"] = sum(speeds) / len(speeds)

            bev_count = sum(1 for vid in veh_ids 
                          if traci.vehicle.getVehicleClass(vid) == "evehicle")
            corridor_metrics["grid_load_mw"] = bev_count * 0.15

        except Exception as e:
            print(f"[SUMOBridge] SUMO read error: {e}")

        envelope = {
            "meta": {
                "schema_version": "ctt-belief-1.0",
                "domain_id": "ctt-spatial",
                "corridor_id": CORRIDOR_ID,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "source_host": f"sumo-bridge-{CORRIDOR_ID}"
            },
            "payload": corridor_metrics,
            "provenance": {"model_version": "ctt-phase14a"}
        }

        self.sumo_pub.send_string(json.dumps(envelope))

        if self.kafka_producer:
            self.kafka_producer.send(f"ctt.spatial.{CORRIDOR_ID}", envelope)
            self.kafka_producer.send("ctt.spatial.metrics", envelope)

    def run(self):
        print(f"[SUMOBridge] Zone server starting for corridor: {CORRIDOR_ID}")
        print(f"[SUMOBridge] ZMQ sub: {ZMQ_TELEMETRY_SUB}")
        print(f"[SUMOBridge] ZMQ pub: {ZMQ_SUMO_PUB}")

        self._running = True
        last_sumo_step = time.time()
        SUMO_STEP_INTERVAL = 0.1

        while self._running:
            try:
                if self.tele_sub.poll(10):
                    msg = self.tele_sub.recv_string()
                    agents = self._parse_telemetry(msg)
                    self._sync_flecs_to_sumo(agents)

                now = time.time()
                if now - last_sumo_step >= SUMO_STEP_INTERVAL:
                    if HAS_SUMO:
                        traci.simulationStep()
                        self.sumo_step += 1
                    self._sync_sumo_to_flecs()
                    last_sumo_step = now

                time.sleep(0.001)

            except Exception as e:
                print(f"[SUMOBridge] Error: {e}")
                time.sleep(0.1)

        print("[SUMOBridge] Shutting down...")
        if HAS_SUMO:
            traci.close()

    def stop(self):
        self._running = False
        if self.kafka_producer:
            self.kafka_producer.close()


if __name__ == "__main__":
    bridge = SUMOBridge()
    try:
        bridge.run()
    except KeyboardInterrupt:
        print("\nSUMO bridge stopping...")
        bridge.stop()
