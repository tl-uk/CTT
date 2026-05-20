#!/usr/bin/env python3
"""
CTT Pipeline Observer — Passive Monitor

Observes the live digital twin WITHOUT injecting data or stopping components.
Verifies data flows: Harvester → Interpreter → Fusion → Engine → Telemetry

Usage:
    python scripts/observe_pipeline.py [--duration 30]
    python scripts/observe_pipeline.py --mode docker [--duration 60]
"""
import json
import time
import sys
import os
import argparse
import subprocess
from datetime import datetime
from collections import deque

import zmq

# ---------------------------------------------------------------------------
# Ports (hardcoded fallbacks)
# ---------------------------------------------------------------------------
TELEMETRY_SUB = "tcp://localhost:5555"
HARVESTER_SUB = "tcp://localhost:5560"
INTERPRETER_SUB = "tcp://localhost:5561"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def check_port(port: int) -> bool:
    result = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
    return result.returncode == 0 and bool(result.stdout.strip())


def format_pressure(p) -> str:
    if isinstance(p, (int, float)):
        return f"{p:.1f}"
    return str(p)


# ---------------------------------------------------------------------------
# Observer
# ---------------------------------------------------------------------------
class PipelineObserver:
    def __init__(self, duration: int = 30, mode: str = "native"):
        self.duration = duration
        self.mode = mode
        self.telemetry_log: deque[dict] = deque(maxlen=100)
        self.harvester_log: deque[dict] = deque(maxlen=100)
        self.interpreter_log: deque[dict] = deque(maxlen=100)
        self.pressure_history: deque[tuple[float, float]] = deque(maxlen=50)

    def observe_telemetry(self, stop_event: list):
        """Thread: listen to C++ engine telemetry on 5555."""
        ctx = zmq.Context()
        sub = ctx.socket(zmq.SUB)
        sub.connect(TELEMETRY_SUB)
        sub.set(zmq.SUBSCRIBE, b"")
        sub.set(zmq.RCVTIMEO, 2000)

        while not stop_event:
            try:
                msg = sub.recv()
                data = json.loads(msg.decode("utf-8"))
                if isinstance(data, list):
                    for agent in data:
                        if isinstance(agent, dict):
                            self.telemetry_log.append({
                                "time": time.time(),
                                "agent": agent.get("entity_name", "?"),
                                "pressure": agent.get("adversarial_pressure", 0),
                                "mode": agent.get("mode", "?"),
                                "energy": agent.get("energy_pct", "?"),
                            })
            except zmq.error.Again:
                continue
            except Exception:
                continue

        sub.close()
        ctx.term()

    def observe_harvester(self, stop_event: list):
        """Thread: listen to harvester output on 5560."""
        ctx = zmq.Context()
        sub = ctx.socket(zmq.SUB)
        sub.connect(HARVESTER_SUB)
        sub.set(zmq.SUBSCRIBE, b"")
        sub.set(zmq.RCVTIMEO, 2000)

        while not stop_event:
            try:
                msg = sub.recv_string()
                data = json.loads(msg)
                self.harvester_log.append({
                    "time": time.time(),
                    "truck_id": data.get("truck_id", "?"),
                    "route": data.get("route", "?"),
                    "efficiency": data.get("efficiency_score", "?"),
                    "delay": data.get("delay_minutes", "?"),
                    "source": data.get("source", "?"),
                })
            except zmq.error.Again:
                continue
            except Exception:
                continue

        sub.close()
        ctx.term()

    def observe_interpreter(self, stop_event: list):
        """Thread: listen to interpreter output on 5561."""
        ctx = zmq.Context()
        sub = ctx.socket(zmq.SUB)
        sub.connect(INTERPRETER_SUB)
        sub.set(zmq.SUBSCRIBE, b"")
        sub.set(zmq.RCVTIMEO, 2000)

        while not stop_event:
            try:
                msg = sub.recv_string()
                data = json.loads(msg)
                self.interpreter_log.append({
                    "time": time.time(),
                    "agent": data.get("agent_uuid", "?"),
                    "delta": data.get("pressure_delta", "?"),
                    "source": data.get("source", "?"),
                })
            except zmq.error.Again:
                continue
            except Exception:
                continue

        sub.close()
        ctx.term()

    def check_docker_health(self):
        """Check Docker container health statuses."""
        print("🔍 Docker Container Health:")
        services = ["engine", "harvester", "interpreter", "fusion", "dashboard"]
        for svc in services:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}", f"ctt-{svc}"],
                capture_output=True, text=True
            )
            status = result.stdout.strip() if result.returncode == 0 else "not found"
            icon = "✅" if status == "healthy" else "⬜" if status in ("starting", "") else "❌"
            print(f"   {icon} ctt-{svc}: {status}")

    def run(self):
        import threading

        print("=" * 70)
        print("CTT Pipeline Observer — Passive Monitor")
        print("=" * 70)
        print(f"Monitoring for {self.duration}s...")
        print(f"   Telemetry:   {TELEMETRY_SUB}")
        print(f"   Harvester:   {HARVESTER_SUB}")
        print(f"   Interpreter: {INTERPRETER_SUB}")
        print()

        if self.mode == "docker":
            self.check_docker_health()
            print()

        # Check ports
        print("🔍 Port Health:")
        ports = [
            ("Engine Telemetry", 5555),
            ("Fusion", 5556),
            ("Harvester", 5560),
            ("Interpreter", 5561),
        ]
        for name, port in ports:
            status = "✅ UP" if check_port(port) else "⬜ DOWN"
            print(f"   {name:20s} | Port {port} | {status}")
        print()

        # Start listeners
        stop_event = []
        threads = [
            threading.Thread(target=self.observe_telemetry, args=(stop_event,)),
            threading.Thread(target=self.observe_harvester, args=(stop_event,)),
            threading.Thread(target=self.observe_interpreter, args=(stop_event,)),
        ]
        for t in threads:
            t.start()

        # Countdown
        start = time.time()
        try:
            while time.time() - start < self.duration:
                elapsed = int(time.time() - start)
                remaining = self.duration - elapsed

                # Live stats every 5s
                if elapsed % 5 == 0 and elapsed > 0:
                    t_count = len(self.telemetry_log)
                    h_count = len(self.harvester_log)
                    i_count = len(self.interpreter_log)
                    print(f"⏱️  {elapsed:3d}s | Telemetry: {t_count:3d} | Harvester: {h_count:3d} | Interpreter: {i_count:3d}")

                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Observer stopped by user.")

        stop_event.append(True)
        for t in threads:
            t.join(timeout=2)

        # Report
        self._report()

    def _report(self):
        print()
        print("=" * 70)
        print("OBSERVATION REPORT")
        print("=" * 70)

        # Telemetry summary
        if self.telemetry_log:
            latest = self.telemetry_log[-1]
            print(f"\n📡 Telemetry (5555)")
            print(f"   Total messages: {len(self.telemetry_log)}")
            print(f"   Latest agent: {latest['agent']}")
            print(f"   Latest pressure: {format_pressure(latest['pressure'])}")
            print(f"   Latest mode: {latest['mode']}")
        else:
            print(f"\n📡 Telemetry (5555): ❌ No data received")

        # Harvester summary
        if self.harvester_log:
            latest = self.harvester_log[-1]
            print(f"\n🌾 Harvester (5560)")
            print(f"   Total messages: {len(self.harvester_log)}")
            print(f"   Latest: {latest['truck_id']} | route={latest['route']} | delay={latest['delay']}m")
        else:
            print(f"\n🌾 Harvester (5560): ⬜ No data (harvester may not be running)")

        # Interpreter summary
        if self.interpreter_log:
            latest = self.interpreter_log[-1]
            print(f"\n🧠 Interpreter (5561)")
            print(f"   Total messages: {len(self.interpreter_log)}")
            print(f"   Latest: {latest['agent']} | delta={latest['delta']}")
        else:
            print(f"\n🧠 Interpreter (5561): ⬜ No data (interpreter may not be running)")

        # Pipeline flow analysis
        print(f"\n🔀 Pipeline Flow Analysis:")
        if self.harvester_log and self.interpreter_log:
            h_time = self.harvester_log[-1]["time"]
            i_time = self.interpreter_log[-1]["time"]
            lag = abs(i_time - h_time)
            print(f"   Harvester → Interpreter: ✅ Data flowing (lag ≈ {lag:.2f}s)")
        elif self.harvester_log and not self.interpreter_log:
            print(f"   Harvester → Interpreter: ❌ Harvester sending but interpreter not receiving")
        else:
            print(f"   Harvester → Interpreter: ⬜ No harvester data to analyze")

        if self.interpreter_log and self.telemetry_log:
            i_time = self.interpreter_log[-1]["time"]
            t_time = self.telemetry_log[-1]["time"]
            lag = abs(t_time - i_time)
            print(f"   Interpreter → Engine → Telemetry: ✅ Data flowing (lag ≈ {lag:.2f}s)")
        elif self.interpreter_log and not self.telemetry_log:
            print(f"   Interpreter → Engine: ❌ Interpreter sending but no telemetry")
        else:
            print(f"   Interpreter → Engine: ⬜ No interpreter data to analyze")

        print()
        print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CTT Pipeline Observer")
    parser.add_argument("--duration", type=int, default=30, help="Observation duration in seconds")
    parser.add_argument("--mode", choices=["native", "docker"], default="native", help="Observer mode")
    args = parser.parse_args()

    observer = PipelineObserver(duration=args.duration, mode=args.mode)
    observer.run()
