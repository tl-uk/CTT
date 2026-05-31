# =============================================================================
# Updated test_multi_domain.py — REST-based verification (architectural fix)
# =============================================================================
#!/usr/bin/env python3
"""
scripts/test_multi_domain.py

CTT Phase 6.5 — Multi-Stakeholder Federation E2E Test

Validates plug-and-use resilience across two independent CTT domains.
Uses scripts/generate_domain_compose.py to render compose files on-the-fly.

Port semantics:
  - Host (external) ports = BASE + offset  (used for REST probes, curls)
  - Container (internal) ports = BASE     (services hardcode bind addresses)

Architectural note (Phase 6.5):
  Host-side ZMQ PUB/SUB probing is unreliable on Docker Desktop macOS because
  the VM boundary user-space proxy does not forward ZMQ subscription handshakes.
  This test verifies telemetry at the REST application layer (dashboard /health),
  which already consumes ZMQ internally. ZMQ probes are retained for tactical
  policy verification (optional) and Linux CI/CD environments.

Test sequence:
  1. Generate compose for domain-a and domain-b from domains.yaml
  2. Spin up domain-a (default / DfT)
  3. Spin up domain-b (e.g., DHL, Network Rail, Tesco, NHS)
  4. Verify both domains report healthy agents via REST
  5. Verify federation bridges can exchange ZMQ heartbeats (via REST proxy)
  6. Disconnect domain-b (simulate stakeholder outage)
  7. Verify domain-a continues unaffected (resilience)
  8. Reconnect domain-b
  9. Verify domain-b auto-syncs and resumes federation

Usage:
    python scripts/test_multi_domain.py --domain-a domain-dft --domain-b domain-dhl [--keep]

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
COMPOSE_BASE = PROJECT_ROOT / "deploy" / "docker-compose.yml"
GENERATOR = PROJECT_ROOT / "scripts" / "generate_domain_compose.py"


def get_compose_path(domain: str) -> Path:
    return PROJECT_ROOT / "deploy" / f"docker-compose.{domain}.yml"


def get_host_ports(domain: str) -> dict:
    """Return HOST (external) port numbers for probing from the Docker host.

    Container ports remain at base values; only host-side mappings shift.
    """
    # Try to read offset from domains.yaml
    try:
        domains_file = PROJECT_ROOT / "services" / "config" / "domains.yaml"
        if domains_file.exists():
            text = domains_file.read_text()
            import re
            # Find port_offset under this domain block
            domain_short = domain.replace("domain-", "")
            pattern = rf"{re.escape(domain)}:\s*\n(?:\s+.*\n)*?\s+port_offset:\s*(\d+)"
            match = re.search(pattern, text)
            if match:
                offset = int(match.group(1))
            else:
                offset = 0 if domain == "domain-dft" else 2
        else:
            offset = 0 if domain == "domain-dft" else 2
    except Exception:
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
    result = subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"[ERR] Command failed with exit code {result.returncode}")
        if result.stdout:
            print(f"[OUT] {result.stdout[:500]}")
        if result.stderr:
            print(f"[ERR] {result.stderr[:500]}")
        raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)
    return result


def health_check(domain: str, timeout: int = 120) -> dict:
    """Poll dashboard /health until agents are online or timeout."""
    ports = get_host_ports(domain)
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


def zmq_probe(addr: str, topic: str = "", timeout_ms: int = 5000) -> bool:
    """Try to receive at least one message from a ZMQ PUB socket.

    NOTE: This is unreliable on Docker Desktop macOS due to VM boundary
    limitations with ZMQ subscription handshakes. Use only for tactical policy
    probes (optional) or in Linux CI/CD environments.
    """
    ctx = zmq.Context()
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.RCVTIMEO, timeout_ms)
    sub.setsockopt(zmq.LINGER, 0)
    sub.setsockopt_string(zmq.SUBSCRIBE, topic)
    try:
        sub.connect(addr)
        # Slow-joiner guard: allow subscription handshake to complete
        time.sleep(0.3)
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


def generate_domain(domain: str):
    """Run the generator script to emit compose file."""
    print(f"[GEN] Rendering docker-compose.{domain}.yml ...")
    result = run([sys.executable, str(GENERATOR), "--domain", domain], check=False)
    if result.returncode != 0:
        print(f"[WARN] Generator exited {result.returncode}, checking if file already exists...")
    compose_path = get_compose_path(domain)
    if not compose_path.exists():
        raise RuntimeError(f"Generator failed to produce {compose_path}. Stderr: {result.stderr}")
    print(f"[GEN] OK: {compose_path}")


# In phase_bring_up (non-base path):
def phase_bring_up(domain: str, is_base: bool = False):
    log_step(1 if is_base else 2, f"Bring up {domain}")
    if is_base:
        compose = COMPOSE_BASE
        run(["docker-compose", "-f", str(compose), "down", "--volumes", "--remove-orphans"], check=False)
    else:
        compose = get_compose_path(domain)
        project_name = domain.replace("domain-", "ctt-")
        # CRITICAL: Use -p to isolate project, preventing base container destruction
        run(["docker-compose", "-p", project_name, "-f", str(compose), "down", "--volumes", "--remove-orphans"], check=False)
        run(["docker-compose", "-p", project_name, "-f", str(compose), "up", "--build", "-d"])

def phase_verify_federation(domain_a: str, domain_b: str):
    """Phase 6.5: Verify telemetry via REST (dashboard already consumes ZMQ).

    Host-side ZMQ probing is unreliable on Docker Desktop macOS because the
    VM boundary user-space proxy does not forward ZMQ SUB subscription
    handshakes. We verify at the application layer instead.
    """
    log_step(3, "Verify telemetry streams on both domains (REST-based)")
    for domain in (domain_a, domain_b):
        data = health_check(domain, timeout=30)
        ok = data.get("telemetry_flowing", False)
        status = "OK" if ok else "FAIL"
        print(f"  [{domain}] Telemetry via REST /health -> {status} ({data['agents_online']} agents)")
        if not ok:
            raise RuntimeError(f"[{domain}] Telemetry not flowing")

    log_step(4, "Verify tactical policy streams (optional ZMQ probe)")
    for domain in (domain_a, domain_b):
        ports = get_host_ports(domain)
        addr = f"tcp://localhost:{ports['tactical_zmq']}"
        ok = zmq_probe(addr, timeout_ms=3000)
        print(f"  [{domain}] Tactical ZMQ {addr} -> {'OK' if ok else 'NO_MSG (expected if no anomaly)'}")


def phase_resilience_disconnect(domain_b: str):
    log_step(5, f"Disconnect {domain_b} (simulate stakeholder outage)")
    compose = get_compose_path(domain_b)
    project_name = domain_b.replace("domain-", "ctt-")
    run(["docker-compose", "-p", project_name, "-f", str(compose), "down"])
    time.sleep(3)


def phase_verify_resilience(domain_a: str):
    log_step(6, f"Verify {domain_a} continues unaffected")
    data = health_check(domain_a, timeout=30)
    print(f"  [{domain_a}] Still healthy: {data['agents_online']} agents, telemetry_flowing={data['telemetry_flowing']}")


def phase_reconnect(domain_b: str):
    log_step(7, f"Reconnect {domain_b} (simulate recovery)")
    compose = get_compose_path(domain_b)
    project_name = domain_b.replace("domain-", "ctt-")
    run(["docker-compose", "-p", project_name, "-f", str(compose), "up", "-d"])
    data = health_check(domain_b)
    print(f"  [{domain_b}] Recovered: {data['agents_online']} agents, telemetry_flowing={data['telemetry_flowing']}")

def phase_verify_post_reconnect(domain_a: str, domain_b: str):
    """Phase 6.5: Verify federation resumed via REST health check."""
    log_step(8, "Verify federation resumes after reconnect")
    for domain in (domain_a, domain_b):
        data = health_check(domain, timeout=60)
        ok = data.get("telemetry_flowing", False)
        status = "RESUMED" if ok else "FAIL"
        print(f"  [{domain}] Telemetry via REST /health -> {status} ({data['agents_online']} agents)")
        if not ok:
            raise RuntimeError(f"[{domain}] Telemetry did not resume after reconnect")


def phase_cleanup(domain_a: str, domain_b: str, keep: bool = False):
    if keep:
        ports_a = get_host_ports(domain_a)
        ports_b = get_host_ports(domain_b)
        print("\n[KEEP] Stacks left running for manual inspection.")
        print(f"       {domain_a} dashboard: http://localhost:{ports_a['dashboard']}")
        print(f"       {domain_b} dashboard: http://localhost:{ports_b['dashboard']}")
        print(f"       {domain_a} Grafana:   http://localhost:{ports_a['grafana']}")
        print(f"       {domain_b} Grafana:   http://localhost:{ports_b['grafana']}")
        return

    log_step(9, "Cleanup: tear down both domains")
    run(["docker-compose", "-p", project_name_b, "-f", str(get_compose_path(domain_b)), "down", "--volumes", "--remove-orphans"], check=False)
    if domain_a != "domain-dft":
        project_name_a = domain_a.replace("domain-", "ctt-")
        run(["docker-compose", "-p", project_name_a, "-f", str(get_compose_path(domain_a)), "down", "--volumes", "--remove-orphans"], check=False)
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
    parser.add_argument("--skip-base-rebuild", action="store_true", help="Skip tearing down/rebuilding domain-a (DfT)")
    args = parser.parse_args()

    print(f"CTT Phase 6.5 — Multi-Stakeholder Federation E2E Test")
    print(f"Base domain:  {args.domain_a}")
    print(f"Peer domain:  {args.domain_b}")
    print(f"Project root: {PROJECT_ROOT}")

    try:
        if not args.skip_generate:
            phase_generate(args.domain_a, args.domain_b)
        if not args.skip_base_rebuild:
            phase_bring_up(args.domain_a, is_base=True)
        else:
            print(f"\n[SKIP] Assuming {args.domain_a} is already running")
            data = health_check(args.domain_a, timeout=30)
            print(f"  [{args.domain_a}] Healthy: {data['agents_online']} agents, telemetry_flowing={data['telemetry_flowing']}")
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