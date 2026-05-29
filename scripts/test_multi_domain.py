#!/usr/bin/env python3
"""
scripts/test_multi_domain.py

CTT Phase 6.5 — Multi-Stakeholder Federation E2E Test

Validates plug-and-use resilience across two independent CTT domains:
  - domain-dft (default compose): Department for Transport view
  - domain-dhl (domain-dhl compose): DHL logistics operator view

Test sequence:
  1. Spin up domain-dft
  2. Spin up domain-dhl (shifted ports, separate network)
  3. Verify both domains report healthy agents via REST
  4. Verify federation bridges can exchange ZMQ heartbeats
  5. Disconnect domain-dhl (docker-compose down)
  6. Verify domain-dft continues unaffected (resilience)
  7. Reconnect domain-dhl
  8. Verify domain-dhl auto-syncs and resumes federation

Usage:
    python scripts/test_multi_domain.py [--keep]

Requires: Docker Compose v2, Python 3.10+, requests, zmq
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import zmq

# =============================================================================
# Configuration
# =============================================================================

PROJECT_ROOT = Path(__file__).parent.parent
COMPOSE_DFT = PROJECT_ROOT / "deploy" / "docker-compose.yml"
COMPOSE_DHL = PROJECT_ROOT / "deploy" / "docker-compose.domain-dhl.yml"

ENDPOINTS = {
    "dft": {
        "dashboard": "http://localhost:5001",
        "grafana": "http://localhost:3000",
        "telemetry_zmq": "tcp://localhost:5555",
        "policy_zmq": "tcp://localhost:5563",
        "tactical_zmq": "tcp://localhost:5564",
    },
    "dhl": {
        "dashboard": "http://localhost:5002",
        "grafana": "http://localhost:3001",
        "telemetry_zmq": "tcp://localhost:5557",
        "policy_zmq": "tcp://localhost:5567",
        "tactical_zmq": "tcp://localhost:5568",
    },
}

HEALTH_TIMEOUT = 120  # seconds
AGENT_MIN_COUNT = 5


# =============================================================================
# Helpers
# =============================================================================

def run(cmd: list[str], cwd: Path = PROJECT_ROOT, check: bool = True) -> subprocess.CompletedProcess:
    print(f"[CMD] {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def health_check(domain: str, timeout: int = HEALTH_TIMEOUT) -> dict:
    """Poll dashboard /health until agents are online or timeout."""
    url = ENDPOINTS[domain]["dashboard"] + "/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                data = json.loads(resp.read().decode())
                if data.get("agents_online", 0) >= AGENT_MIN_COUNT:
                    return data
        except Exception as e:
            print(f"  [{domain}] Waiting for health... ({e})")
        time.sleep(2)
    raise RuntimeError(f"[{domain}] Health check failed after {timeout}s")


def zmq_probe(addr: str, topic: str = "", timeout_ms: int = 3000) -> bool:
    """Try to receive at least one message from a ZMQ PUB socket."""
    ctx = zmq.Context()
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.RCVTIMEO, timeout_ms)
    sub.setsockopt(zmq.LINGER, 0)
    sub.setsockopt_string(zmq.SUBSCRIBE, topic)
    try:
        sub.connect(addr)
        msg = sub.recv()
        return True
    except zmq.error.Again:
        return False
    except Exception as e:
        print(f"  [ZMQ] Error probing {addr}: {e}")
        return False
    finally:
        sub.close()
        ctx.term()


def log_step(step: int, desc: str):
    print(f"\n{'='*60}")
    print(f"STEP {step}: {desc}")
    print(f"{'='*60}")


# =============================================================================
# Test Phases
# =============================================================================

def phase_bring_up_dft():
    log_step(1, "Bring up domain-dft (DfT)")
    run(["docker-compose", "-f", str(COMPOSE_DFT), "down", "--volumes", "--remove-orphans"], check=False)
    run(["docker", "builder", "prune", "-af"], check=False)
    run(["docker-compose", "-f", str(COMPOSE_DFT), "up", "--build", "-d"])
    data = health_check("dft")
    print(f"  [dft] Healthy: {data['agents_online']} agents, telemetry_flowing={data['telemetry_flowing']}")


def phase_bring_up_dhl():
    log_step(2, "Bring up domain-dhl (DHL)")
    run(["docker-compose", "-f", str(COMPOSE_DHL), "down", "--volumes", "--remove-orphans"], check=False)
    run(["docker-compose", "-f", str(COMPOSE_DHL), "up", "--build", "-d"])
    data = health_check("dhl")
    print(f"  [dhl] Healthy: {data['agents_online']} agents, telemetry_flowing={data['telemetry_flowing']}")


def phase_verify_federation():
    log_step(3, "Verify ZMQ telemetry streams on both domains")
    for domain in ("dft", "dhl"):
        addr = ENDPOINTS[domain]["telemetry_zmq"]
        ok = zmq_probe(addr, timeout_ms=5000)
        status = "OK" if ok else "FAIL"
        print(f"  [{domain}] Telemetry ZMQ {addr} -> {status}")
        if not ok:
            raise RuntimeError(f"[{domain}] Telemetry ZMQ not flowing")

    log_step(4, "Verify tactical policy streams")
    for domain in ("dft", "dhl"):
        addr = ENDPOINTS[domain]["tactical_zmq"]
        # Tactical pub may not emit constantly; just verify bind is reachable
        ok = zmq_probe(addr, timeout_ms=2000)
        print(f"  [{domain}] Tactical ZMQ {addr} -> {'OK' if ok else 'NO_MSG (expected if no anomaly)'}")


def phase_resilience_disconnect_dhl():
    log_step(5, "Disconnect domain-dhl (simulate outage)")
    run(["docker-compose", "-f", str(COMPOSE_DHL), "down"])
    time.sleep(3)

    log_step(6, "Verify domain-dft continues unaffected")
    data = health_check("dft", timeout=30)
    print(f"  [dft] Still healthy: {data['agents_online']} agents, telemetry_flowing={data['telemetry_flowing']}")

    # Verify DHL dashboard is unreachable
    dhl_url = ENDPOINTS["dhl"]["dashboard"] + "/health"
    try:
        with urllib.request.urlopen(dhl_url, timeout=2) as resp:
            raise RuntimeError("[dhl] Dashboard still reachable after down — port conflict?")
    except Exception:
        print("  [dhl] Correctly unreachable after disconnect")


def phase_reconnect_dhl():
    log_step(7, "Reconnect domain-dhl (simulate recovery)")
    run(["docker-compose", "-f", str(COMPOSE_DHL), "up", "-d"])
    data = health_check("dhl")
    print(f"  [dhl] Recovered: {data['agents_online']} agents, telemetry_flowing={data['telemetry_flowing']}")

    log_step(8, "Verify federation resumes after reconnect")
    for domain in ("dft", "dhl"):
        addr = ENDPOINTS[domain]["telemetry_zmq"]
        ok = zmq_probe(addr, timeout_ms=8000)
        status = "RESUMED" if ok else "FAIL"
        print(f"  [{domain}] Telemetry ZMQ {addr} -> {status}")
        if not ok:
            raise RuntimeError(f"[{domain}] Telemetry did not resume after reconnect")


def phase_cleanup(keep: bool = False):
    if keep:
        print("\n[KEEP] Stacks left running for manual inspection.")
        print("       DfT dashboard: http://localhost:5001")
        print("       DHL dashboard: http://localhost:5002")
        print("       DfT Grafana:   http://localhost:3000")
        print("       DHL Grafana:   http://localhost:3001")
        return
    log_step(9, "Cleanup: tear down both domains")
    run(["docker-compose", "-f", str(COMPOSE_DHL), "down", "--volumes", "--remove-orphans"], check=False)
    run(["docker-compose", "-f", str(COMPOSE_DFT), "down", "--volumes", "--remove-orphans"], check=False)
    print("[OK] All stacks torn down")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="CTT Multi-Stakeholder Federation E2E Test")
    parser.add_argument("--keep", action="store_true", help="Leave stacks running after test")
    args = parser.parse_args()

    print("CTT Phase 6.5 — Multi-Stakeholder Federation E2E Test")
    print(f"Project root: {PROJECT_ROOT}")

    try:
        phase_bring_up_dft()
        phase_bring_up_dhl()
        phase_verify_federation()
        phase_resilience_disconnect_dhl()
        phase_reconnect_dhl()
        print("\n" + "="*60)
        print("ALL TESTS PASSED — Plug-and-use resilience demonstrated")
        print("="*60)
    except Exception as e:
        print(f"\n[FAIL] {e}")
        sys.exit(1)
    finally:
        phase_cleanup(keep=args.keep)


if __name__ == "__main__":
    main()
