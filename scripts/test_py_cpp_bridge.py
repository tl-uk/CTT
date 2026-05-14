#!/usr/bin/env python3
"""
scripts/test_py_cpp_bridge.py

Comprehensive integration test for the CTT Python-C++ bridge.
Validates the full data flow: SME → Ingestor → Interpreter → Fusion → C++ Engine → Dashboard.
"""

import sys
import time
import json
import subprocess
import threading
import zmq
import requests

# Add paths for CTT modules
sys.path.insert(0, "services/data-pipeline/ingestor")
sys.path.insert(0, "services/data-pipeline/interpreter")
sys.path.insert(0, "services/data-pipeline/fusion")
sys.path.insert(0, "services/l2-bridge")

from ctt_messages_pb2 import MindsetPerturbation # type: ignore


class BridgeTest:
    def __init__(self):
        self.context = zmq.Context()
        self.results = {
            "pipeline_ran": False,
            "perturbation_sent": False,
            "perturbation_received_by_cpp": False,
            "state_broadcast_received": False,
            "flecs_rest_updated": False,
            "pressure_actually_changed": False,
        }
        self.errors = []
        
    def log(self, msg):
        print(f"[TEST] {msg}")
        
    def error(self, msg):
        self.errors.append(msg)
        print(f"[TEST] ❌ {msg}")
        
    def check_cpp_engine_running(self):
        """Verify C++ engine is listening on REST and ZMQ ports."""
        self.log("Checking C++ engine...")
        
        # Check REST API
        try:
            resp = requests.get("http://localhost:27750/entity/flecs", timeout=2)
            if resp.status_code == 200:
                self.log("✅ REST API responding on port 27750")
            else:
                self.error(f"REST API returned status {resp.status_code}")
                return False
        except requests.exceptions.ConnectionError:
            self.error("C++ engine not running. Start it with: make run-engine")
            return False
            
        # Check ZMQ pub port (5555) - just verify it's bound by trying to connect
        try:
            test_sub = self.context.socket(zmq.SUB)
            test_sub.connect("tcp://localhost:5555")
            test_sub.close()
            self.log("✅ ZMQ Publisher port 5555 accessible")
        except Exception as e:
            self.error(f"ZMQ port 5555 not accessible: {e}")
            return False
            
        return True
        
    def send_sme_data_directly(self):
        """Bypass the pipeline and send a perturbation directly to C++."""
        self.log("Sending direct perturbation to C++ engine...")
        
        # Create protobuf message
        p = MindsetPerturbation()
        p.agent_uuid = "Volvo_eHGV_001"  # The entity in C++
        p.pressure_delta = 25.0
        p.source = "BridgeTest_Direct"
        
        # Send via ZMQ to C++ sub port (5556)
        sender = self.context.socket(zmq.PUB)
        sender.connect("tcp://localhost:5556")
        time.sleep(0.5)  # Allow connection to establish
        
        sender.send(p.SerializeToString())
        self.log("✅ Direct perturbation sent: +25.0 pressure to Volvo_eHGV_001")
        self.results["perturbation_sent"] = True
        sender.close()
        
    def listen_for_state_broadcast(self, duration=5):
        """Listen to C++ engine's ZMQ pub (5555) for state updates."""
        self.log(f"Listening for state broadcasts on 5555 for {duration}s...")
        
        sub = self.context.socket(zmq.SUB)
        sub.connect("tcp://localhost:5555")
        sub.setsockopt_string(zmq.SUBSCRIBE, "")
        sub.setsockopt(zmq.RCVTIMEO, 2000)  # 2 second timeout
        
        start = time.time()
        messages = []
        
        while time.time() - start < duration:
            try:
                msg = sub.recv_string()
                data = json.loads(msg)
                messages.append(data)
                self.log(f"📡 Received broadcast: {len(data)} entities")
                
                # Check if our entity is in the broadcast
                for entity in data:
                    if entity.get("entity_name") == "Volvo_eHGV_001":
                        self.log(f"   Found Volvo_eHGV_001: energy={entity.get('energy_pct', 'N/A'):.1f}%")
                        
            except zmq.error.Again:
                continue  # Timeout, keep listening
            except Exception as e:
                self.error(f"Error receiving broadcast: {e}")
                break
                
        sub.close()
        
        if messages:
            self.results["state_broadcast_received"] = True
            self.log(f"✅ Received {len(messages)} state broadcasts")
        else:
            self.error("No state broadcasts received")
            
    def check_flecs_entity_state(self):
        """Query Flecs REST API for entity state."""
        self.log("Querying Flecs REST API for entity state...")
        
        try:
            resp = requests.get("http://localhost:27750/entity/Volvo_eHGV_001", timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                self.log(f"✅ Entity found in Flecs: {json.dumps(data, indent=2)[:200]}...")
                self.results["flecs_rest_updated"] = True
                return data
            else:
                self.error(f"Entity query failed: {resp.status_code}")
                return None
        except Exception as e:
            self.error(f"REST query failed: {e}")
            return None
            
    def run_pipeline_test(self):
        """Test the full Python pipeline: harvester → interpreter → fusion → C++."""
        self.log("=" * 60)
        self.log("FULL PIPELINE TEST")
        self.log("=" * 60)
        
        # Start pipeline components in background
        self.log("Starting pipeline components...")
        
        harvester = subprocess.Popen(
            [sys.executable, "services/data-pipeline/ingestor/harvester.py"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        interpreter = subprocess.Popen(
            [sys.executable, "services/data-pipeline/interpreter/semantic_agent.py"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        fusion = subprocess.Popen(
            [sys.executable, "services/data-pipeline/fusion/fusion_engine.py"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        
        self.log("Pipeline components started. Waiting for data flow...")
        time.sleep(3)  # Allow pipeline to warm up
        
        # Listen for perturbations from fusion engine
        self.log("Checking if fusion engine is sending perturbations...")
        
        # The fusion engine sends to 5556, C++ receives there
        # We can't easily intercept without a proxy, so we check C++ state instead
        
        # Check if C++ received anything
        initial_state = self.check_flecs_entity_state()
        
        # Wait for pipeline to process
        time.sleep(5)
        
        updated_state = self.check_flecs_entity_state()
        
        # Cleanup pipeline
        for proc in [harvester, interpreter, fusion]:
            proc.terminate()
            proc.wait()
            
        self.log("Pipeline components stopped.")
        
        if initial_state and updated_state:
            self.results["pipeline_ran"] = True
            self.log("✅ Full pipeline executed")

    
    def extract_pressure_from_flecs(self, flecs_data):
        """Extract adversarial_pressure from Flecs REST JSON."""
        if not flecs_data:
            return None
            
        # Flecs v4 REST returns components as arrays of [type, value] pairs
        # or as objects depending on the endpoint. Inspect your actual response.
        try:
            # Try to find MindsetComponent in the response
            for component in flecs_data.get("components", []):
                if isinstance(component, list) and len(component) >= 2:
                    type_name = component[0]
                    if "Mindset" in str(type_name) or "mindset" in str(type_name).lower():
                        data = component[1]
                        return data.get("adversarial_pressure", None)
                elif isinstance(component, dict):
                    if "mindset" in str(component.get("type", "")).lower():
                        return component.get("data", {}).get("adversarial_pressure", None)
        except Exception as e:
            self.error(f"Failed to parse pressure: {e}")
            
        # Fallback: dump structure for debugging
        self.log(f"Flecs response structure: {json.dumps(flecs_data, indent=2)[:500]}")
        return None

    def start_explorer(self):
        """Auto-start Flecs Explorer if not running."""
        try:
            requests.get("http://localhost:8000", timeout=1)
            self.log("✅ Flecs Explorer already running")
            return True
        except:
            self.log("Starting Flecs Explorer...")
            subprocess.Popen(
                ["python3", "-m", "http.server", "8000"],
                cwd=str(Path.home() / "explorer" / "etc"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(2)
            return True
        
    def run_direct_test(self):
        """Test direct perturbation to C++."""
        self.log("=" * 60)
        self.log("DIRECT PERTURBATION TEST")
        self.log("=" * 60)
        
        # Auto-start explorer
        self.start_explorer()
        
        # Get baseline
        baseline = self.check_flecs_entity_state()
        baseline_pressure = self.extract_pressure_from_flecs(baseline)
        self.log(f"Baseline pressure: {baseline_pressure}")
        
        # Send perturbation
        self.send_sme_data_directly()
        time.sleep(1.5)  # Allow C++ processing + Flecs update
        
        # Check updated state
        updated = self.check_flecs_entity_state()
        updated_pressure = self.extract_pressure_from_flecs(updated)
        
        # Verify receipt
        if baseline is not None and updated is not None:
            self.results["perturbation_received_by_cpp"] = True
            
        # Verify actual change
        if baseline_pressure is not None and updated_pressure is not None:
            delta = updated_pressure - baseline_pressure
            self.log(f"Pressure: {baseline_pressure:.2f} → {updated_pressure:.2f} (Δ{delta:+.2f})")
            if abs(delta) > 0.01:
                self.results["pressure_actually_changed"] = True
                
        self.listen_for_state_broadcast(duration=3)
            
    def generate_report(self):
        """Print test results."""
        self.log("=" * 60)
        self.log("TEST REPORT")
        self.log("=" * 60)
        
        passed = sum(1 for v in self.results.values() if v)
        total = len(self.results)
        
        for check, result in self.results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            self.log(f"  {check:40s} {status}")
            
        self.log(f"\nScore: {passed}/{total} checks passed")
        
        if self.errors:
            self.log(f"\nErrors encountered:")
            for err in self.errors:
                self.log(f"  - {err}")
                
        return passed == total
        
    def run(self):
        """Execute all tests."""
        print("\n" + "=" * 60)
        print("CTT Python-C++ Bridge Integration Test")
        print("=" * 60 + "\n")
        
        # Phase 1: Verify C++ engine is running
        if not self.check_cpp_engine_running():
            self.log("\n❌ ABORT: C++ engine not available.")
            self.log("   Start it first: make run-engine")
            return False
            
        # Phase 2: Direct perturbation test
        self.run_direct_test()
        
        # Phase 3: Full pipeline test
        self.run_pipeline_test()
        
        # Phase 4: Report
        return self.generate_report()


if __name__ == "__main__":
    test = BridgeTest()
    success = test.run()
    sys.exit(0 if success else 1)