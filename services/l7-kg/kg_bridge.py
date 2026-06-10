#!/usr/bin/env python3
"""
services/l7-kg/kg_bridge.py

ZMQ bridge between C++ L1 Engine (Flecs ECS) and Python L7 Knowledge Graph.

Bidirectional flow:
  C++ → Python: SSN_Experience records (compressed vectors + metadata)
  Python → C++: Similarity matches ("agent X, your situation matches a past success")

This bridge runs as a background thread in the L2 Orchestrator or as a
standalone service in the Docker Compose stack.
"""
import json
import logging
import os
import sys
import threading
import time
from typing import Dict, Any, Optional
import zmq
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "config"))
from ports import ZMQ_PORTS, get_resilient_socket

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ctt.kg_bridge")


class KGBridge:
    """
    ZMQ bridge for SSN experience exchange between C++ engine and Python KG.

    Protocol:
      SUB on CTT_KG_TOPIC (default: "ctt.kg.experience")
      PUB on CTT_KG_MATCH_TOPIC (default: "ctt.kg.match")
    """

    def __init__(self, 
                 sub_addr: str = None,
                 pub_addr: str = None,
                 experience_topic: str = "ctt.kg.experience",
                 match_topic: str = "ctt.kg.match"):
        self.ctx = zmq.Context()

        # Subscriber: receives SSN experiences from C++ engine
        self.sub = get_resilient_socket(self.ctx, zmq.SUB, is_sub=True)
        self.sub_addr = sub_addr or ZMQ_PORTS.get("L1_TELEMETRY_SUB", "tcp://localhost:5555")
        self.sub.connect(self.sub_addr)
        self.sub.setsockopt_string(zmq.SUBSCRIBE, experience_topic)
        logger.info("KG Bridge SUB connected to %s (topic: %s)", self.sub_addr, experience_topic)

        # Publisher: sends similarity matches back to C++ engine
        self.pub = get_resilient_socket(self.ctx, zmq.PUB)
        self.pub_addr = pub_addr or "tcp://localhost:5565"  # Dedicated KG port
        self.pub.bind(self.pub_addr)
        logger.info("KG Bridge PUB bound to %s (topic: %s)", self.pub_addr, match_topic)

        self.experience_topic = experience_topic
        self.match_topic = match_topic
        self._running = False
        self._thread = None

    def start(self):
        """Start the bridge in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("KG Bridge started")

    def _run(self):
        """Main loop: receive experiences, process, emit matches."""
        while self._running:
            try:
                # Receive multipart: [topic, payload]
                topic = self.sub.recv_string(zmq.RCVTIMEO, 2000)
                payload = self.sub.recv_json()

                logger.debug("Received experience from %s", payload.get("agent_id", "unknown"))

                # TODO: Integrate with sig_compressor and learn_mod
                # For now, echo back a simple match
                match = self._process_experience(payload)
                if match:
                    self.pub.send_string(self.match_topic, zmq.SNDMORE)
                    self.pub.send_json(match)

            except zmq.error.Again:
                continue
            except Exception as e:
                logger.exception("KG Bridge error: %s", e)

    def _process_experience(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Process an SSN experience record and return a match if applicable.

        Phase 9 stub — full implementation requires:
        1. sig_compressor.py integration
        2. learn_mod.py integration  
        3. KG query backend (RDF/OWL or vector DB)
        """
        agent_id = payload.get("agent_id")
        if not agent_id:
            return None

        # Stub: always return a "recognition" match for testing
        return {
            "agent_id": agent_id,
            "match_type": "recognition_stub",
            "confidence": 0.85,
            "recommended_procedure": payload.get("procedure", {}),
            "timestamp": time.time()
        }

    def stop(self):
        """Stop the bridge."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.sub.close()
        self.pub.close()
        self.ctx.term()
        logger.info("KG Bridge stopped")


# =============================================================================
# Standalone service entry point
# =============================================================================
if __name__ == "__main__":
    bridge = KGBridge()
    bridge.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down KG Bridge...")
        bridge.stop()
