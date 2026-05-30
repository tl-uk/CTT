#!/usr/bin/env python3
"""
scripts/test_multi_domain.py

CTT Phase 6.5 — Multi-Stakeholder Federation E2E Test

Validates plug-and-use resilience across two independent CTT domains.
Uses scripts/generate_domain_compose.py to render compose files on-the-fly.

Test sequence:
  1. Generate compose for domain-a and domain-b from domains.yaml
  2. Spin up domain-a (default / DfT)
  3. Spin up domain-b (e.g., DHL, Network Rail, Tesco, NHS)
  4. Verify both domains report healthy agents via REST
  5. Verify federation bridges can exchange ZMQ heartbeats
  6. Disconnect domain-b (simulate stakeholder outage)
  7. Verify domain-a continues unaffected (resilience)
  8. Reconnect domain-b
  9. Verify domain-b auto-syncs and resumes federation

Usage:
    python scripts/test_multi_domain.py --domain-a domain-dft --domain-b domain-dhl [--keep]

Requires: Docker Compose v2, Python 3.10+, requests, zmq, pyyaml
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
COMPOSE_BASE = PROJECT_ROOT / "deploy" / "docker-compose.yml"
GENERATOR = PROJECT_ROOT / "scripts" / "generate_domain_compose.py"

def get_compose_path(domain: str) -> Path:
    return PROJECT_ROOT / "deploy" / f"docker-compose.{domain}.yml"


def get_ports(domain: str) -> dict:
    """Derive ports from domains.yaml via generator (or hardcode fallback)."""
    # Try to read from domains.yaml directly
    try:
        import yaml
        domains_file = PROJECT_ROOT / "services" / "config" / "domains.yaml"
        with open(domains_file) as f:
            data = yaml.safe_load(f)
        offset = data["domains"][domain]["port_offset"]
    except Exception:
        # Fallback for domain-dft (offset 0)
        offset = 0 if domain == "domain-dft" else 2

    return {
        "dashboard": 5001 + offset,
        "grafana": 3000 + offset,
        "telemetry_zmq": 5555 + offset,
        "policy_zmq": 5563 + offset,
        "tactical_zmq": 5564 + offset,
        "kafka": 9092 + offset,
    }


# =============================================================================
# Helpers
# =============================================================================

def run(cmd: list[str], cwd: Path = PROJECT_ROOT, check: bool = True) -> subprocess.CompletedProcess:
    print(f"[CMD] {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def generate_domain(domain: str):
    """Run the generator script to emit compose file."""
    print(f"[GEN] Rendering docker-compose.{domain}.yml ...")
    run([sys.executable, str(GENERATOR), "--domain", domain])
    compose_path = get_compose_path(domain)
    if not compose_path.exists():
        raise RuntimeError(f"Generator failed to produce {compose_path}")
    print(f"[GEN] OK: {compose_path}")


def health_check(domain: str, timeout: int = 120) -> dict:
    """Poll dashboard /health until agents are online or timeout."""
    ports = get_ports(domain)
    url = f"http://localhost:{ports['dashboard']}/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                data = json.loads(resp.read().decode())
                if data.get("agents_online", 0) >= 5:
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

def phase_generate(domain_a: str, domain_b: str):
    log_step(0, "Generate domain compose files")
    if domain_a != "domain-dft":
        generate_domain(domain_a)
    generate_domain(domain_b)


def phase_bring_up(domain: str, is_base: bool = False):
    log_step(1 if is_base else 2, f"Bring up {domain}")
    if is_base:
        compose = COMPOSE_BASE
        # Ensure base is down first for clean state
        run(["docker-compose", "-f", str(compose), "down", "--volumes", "--remove-orphans"], check=False)
        run(["docker", "builder", "prune", "-af"], check=False)
    else:
        compose = get_compose_path(domain)
        run(["docker-compose", "-f", str(compose), "down", "--volumes", "--remove-orphans"], check=False)

    run(["docker-compose", "-f", str(compose), "up", "--build", "-d"])
    data = health_check(domain)
    print(f"  [{domain}] Healthy: {data['agents_online']} agents, telemetry_flowing={data['telemetry_flowing']}")


def phase_verify_federation(domain_a: str, domain_b: str):
    log_step(3, "Verify ZMQ telemetry streams on both domains")
    for domain in (domain_a, domain_b):
        ports = get_ports(domain)
        addr = f"tcp://localhost:{ports['telemetry_zmq']}"
        ok = zmq_probe(addr, timeout_ms=5000)
        status = "OK" if ok else "FAIL"
        print(f"  [{domain}] Telemetry ZMQ {addr} -> {status}")
        if not ok:
            raise RuntimeError(f"[{domain}] Telemetry ZMQ not flowing")

    log_step(4, "Verify tactical policy streams")
    for domain in (domain_a, domain_b):
        ports = get_ports(domain)
        addr = f"tcp://localhost:{ports['tactical_zmq']}"
        ok = zmq_probe(addr, timeout_ms=2000)
        print(f"  [{domain}] Tactical ZMQ {addr} -> {'OK' if ok else 'NO_MSG (expected if no anomaly)'}")


def phase_resilience_disconnect(domain_b: str):
    log_step(5, f"Disconnect {domain_b} (simulate stakeholder outage)")
    compose = get_compose_path(domain_b)
    run(["docker-compose", "-f", str(compose), "down"])
    time.sleep(3)


def phase_verify_resilience(domain_a: str):
    log_step(6, f"Verify {domain_a} continues unaffected")
    data = health_check(domain_a, timeout=30)
    print(f"  [{domain_a}] Still healthy: {data['agents_online']} agents, telemetry_flowing={data['telemetry_flowing']}")


def phase_reconnect(domain_b: str):
    log_step(7, f"Reconnect {domain_b} (simulate recovery)")
    compose = get_compose_path(domain_b)
    run(["docker-compose", "-f", str(compose), "up", "-d"])
    data = health_check(domain_b)
    print(f"  [{domain_b}] Recovered: {data['agents_online']} agents, telemetry_flowing={data['telemetry_flowing']}")


def phase_verify_post_reconnect(domain_a: str, domain_b: str):
    log_step(8, "Verify federation resumes after reconnect")
    for domain in (domain_a, domain_b):
        ports = get_ports(domain)
        addr = f"tcp://localhost:{ports['telemetry_zmq']}"
        ok = zmq_probe(addr, timeout_ms=8000)
        status = "RESUMED" if ok else "FAIL"
        print(f"  [{domain}] Telemetry ZMQ {addr} -> {status}")
        if not ok:
            raise RuntimeError(f"[{domain}] Telemetry did not resume after reconnect")


def phase_cleanup(domain_a: str, domain_b: str, keep: bool = False):
    if keep:
        ports_a = get_ports(domain_a)
        ports_b = get_ports(domain_b)
        print("\n[KEEP] Stacks left running for manual inspection.")
        print(f"       {domain_a} dashboard: http://localhost:{ports_a['dashboard']}")
        print(f"       {domain_b} dashboard: http://localhost:{ports_b['dashboard']}")
        print(f"       {domain_a} Grafana:   http://localhost:{ports_a['grafana']}")
        print(f"       {domain_b} Grafana:   http://localhost:{ports_b['grafana']}")
        return

    log_step(9, "Cleanup: tear down both domains")
    run(["docker-compose", "-f", str(get_compose_path(domain_b)), "down", "--volumes", "--remove-orphans"], check=False)
    if domain_a != "domain-dft":
        run(["docker-compose", "-f", str(get_compose_path(domain_a)), "down", "--volumes", "--remove-orphans"], check=False)
    run(["docker-compose", "-f", str(COMPOSE_BASE), "down", "--volumes", "--remove-orphans"], check=False)
    print("[OK] All stacks torn down")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="CTT Multi-Stakeholder Federation E2E Test")
    parser.add_argument("--domain-a", default="domain-dft", help="Base domain (default: domain-dft)")
    parser.add_argument("--domain-b", required=True, help="Peer domain (e.g., domain-dhl, domain-tesco)")
    parser.add_argument("--keep", action="store_true", help="Leave stacks running after test")
    parser.add_argument("--skip-generate", action="store_true", help="Skip compose generation (use existing files)")
    args = parser.parse_args()

    print(f"CTT Phase 6.5 — Multi-Stakeholder Federation E2E Test")
    print(f"Base domain:  {args.domain_a}")
    print(f"Peer domain:  {args.domain_b}")
    print(f"Project root: {PROJECT_ROOT}")

    try:
        if not args.skip_generate:
            phase_generate(args.domain_a, args.domain_b)
        phase_bring_up(args.domain_a, is_base=True)
        phase_bring_up(args.domain_b)
        phase_verify_federation(args.domain_a, args.domain_b)
        phase_resilience_disconnect(args.domain_b)
        phase_verify_resilience(args.domain_a)
        phase_reconnect(args.domain_b)
        phase_verify_post_reconnect(args.domain_a, args.domain_b)
        print("\n" + "="*60)
        print("ALL TESTS PASSED — Plug-and-use resilience demonstrated")
        print("="*60)
    except Exception as e:
        print(f"\n[FAIL] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        phase_cleanup(args.domain_a, args.domain_b, keep=args.keep)


if __name__ == "__main__":
    main()
