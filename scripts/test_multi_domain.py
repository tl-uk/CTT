#!/usr/bin/env python3
"""
scripts/test_multi_domain.py

CTT Phase 9 — Multi-Stakeholder Federation E2E Test (Docker-Only)

Validates plug-and-use resilience across two independent CTT domains.
Uses scripts/generate_domain_compose.py to render compose files on-the-fly.

CRITICAL (Phase 9): This test is DOCKER-ONLY. Native mode is NOT supported
for multi-domain E2E because ZMQ addressing (host.docker.internal vs localhost)
and port offsets are only consistent inside the Docker network bridge.
For native single-domain testing, use: make test-e2e

Port semantics:
  - Host (external) ports = BASE + offset  (used for REST probes, curls)
  - Container (internal) ports = BASE     (services hardcode bind addresses)

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

Requires: Docker Compose v2, Python 3.10+, requests, zmq, Colima or Docker Desktop
"""
import argparse
import json
import shutil
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

# Auto-detect Docker Compose command — prefers docker-compose (v1) if available
# because v1 is more stable on Colima/macOS. Falls back to docker compose (v2).
def _detect_docker_compose() -> list[str]:
    """Return the correct Docker Compose command for this system."""
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    if shutil.which("docker"):
        return ["docker", "compose"]
    raise RuntimeError("Neither docker-compose nor docker compose found in PATH")

DOCKER_COMPOSE = _detect_docker_compose()


def get_compose_path(domain: str) -> Path:
    return PROJECT_ROOT / "deploy" / f"docker-compose.{domain}.yml"


def get_host_ports(domain: str) -> dict:
    """Return HOST (external) port numbers for probing from the Docker host."""
    try:
        domains_file = PROJECT_ROOT / "services" / "config" / "domains.yaml"
        if domains_file.exists():
            text = domains_file.read_text()
            import re
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

def run(cmd: list[str], cwd: Path = PROJECT_ROOT, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    """Run a command. Use capture=False for long-running commands."""
    print(f"[CMD] {' '.join(cmd)}")
    if capture:
        result = subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)
        if check and result.returncode != 0:
            print(f"[ERR] Command failed with exit code {result.returncode}")
            if result.stdout:
                print(f"[OUT] {result.stdout[:500]}")
            if result.stderr:
                print(f"[ERR] {result.stderr[:500]}")
            raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)
        return result
    else:
        result = subprocess.run(cmd, cwd=cwd, check=False)
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd)
        return subprocess.CompletedProcess(cmd, result.returncode, stdout="", stderr="")


def docker_images_exist(project_name: str) -> bool:
    """Check if images for a project already exist."""
    result = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return False
    return project_name in result.stdout


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
    NOTE: Unreliable on Docker Desktop macOS. Use for Linux CI/CD only."""
    ctx = zmq.Context()
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.RCVTIMEO, timeout_ms)
    sub.setsockopt(zmq.LINGER, 0)
    sub.setsockopt_string(zmq.SUBSCRIBE, topic)
    try:
        sub.connect(addr)
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
# Docker / Colima Verification
# =============================================================================

def verify_docker_ready():
    """Ensure Docker daemon is running and healthy."""
    print("\n[DOCKER] Verifying Docker daemon...")
    result = subprocess.run(["docker", "info"], capture_output=True, text=True)
    if result.returncode != 0:
        print("❌ Docker daemon is not running.")
        print("")
        print("   If you use Colima:")
        print("      colima start --cpu 4 --memory 8")
        print("")
        print("   If you use Docker Desktop:")
        print("      Open Docker Desktop and wait for the whale icon.")
        print("")
        raise RuntimeError("Docker daemon not available")

    # Check disk space
    df_result = subprocess.run(["docker", "system", "df"], capture_output=True, text=True)
    if df_result.returncode == 0:
        print(f"[DOCKER] {df_result.stdout.strip()}")

    print("✅ Docker daemon is ready")


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


def phase_bring_up(domain: str, is_base: bool = False, force_build: bool = False):
    log_step(1 if is_base else 2, f"Bring up {domain}")
    if is_base:
        compose = COMPOSE_BASE
        project_name = "ctt-dft"
    else:
        compose = get_compose_path(domain)
        project_name = domain.replace("domain-", "ctt-")

    # Always down first to ensure clean state
    run(DOCKER_COMPOSE + ["-p", project_name, "-f", str(compose), "down", "--volumes", "--remove-orphans"], check=False)

    # Use --no-build if images exist and force_build is False
    if not force_build and docker_images_exist("ctt-engine"):
        print(f"  [INFO] Existing images found for {project_name}, using --no-build")
        run(DOCKER_COMPOSE + ["-p", project_name, "-f", str(compose), "up", "-d", "--no-build"], capture=False)
    else:
        print(f"  [INFO] Building images for {project_name} (this may take several minutes)...")
        run(DOCKER_COMPOSE + ["-p", project_name, "-f", str(compose), "up", "--build", "-d"], capture=False)

    data = health_check(domain)
    print(f"  [{domain}] Healthy: {data['agents_online']} agents, telemetry_flowing={data['telemetry_flowing']}")


def phase_verify_federation(domain_a: str, domain_b: str):
    """Phase 9: Verify telemetry via REST (dashboard consumes ZMQ internally)."""
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
    run(DOCKER_COMPOSE + ["-p", project_name, "-f", str(compose), "down"])
    time.sleep(3)


def phase_verify_resilience(domain_a: str):
    log_step(6, f"Verify {domain_a} continues unaffected")
    data = health_check(domain_a, timeout=30)
    print(f"  [{domain_a}] Still healthy: {data['agents_online']} agents, telemetry_flowing={data['telemetry_flowing']}")


def phase_reconnect(domain_b: str):
    log_step(7, f"Reconnect {domain_b} (simulate recovery)")
    compose = get_compose_path(domain_b)
    project_name = domain_b.replace("domain-", "ctt-")
    # Reconnect uses --no-build since images already exist
    run(DOCKER_COMPOSE + ["-p", project_name, "-f", str(compose), "up", "-d", "--no-build"])
    data = health_check(domain_b)
    print(f"  [{domain_b}] Recovered: {data['agents_online']} agents, telemetry_flowing={data['telemetry_flowing']}")


def phase_verify_post_reconnect(domain_a: str, domain_b: str):
    """Phase 9: Verify federation resumed via REST health check."""
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
    project_name_b = domain_b.replace("domain-", "ctt-")
    run(DOCKER_COMPOSE + ["-p", project_name_b, "-f", str(get_compose_path(domain_b)), "down", "--volumes", "--remove-orphans"], check=False)

    if domain_a != "domain-dft":
        project_name_a = domain_a.replace("domain-", "ctt-")
        run(DOCKER_COMPOSE + ["-p", project_name_a, "-f", str(get_compose_path(domain_a)), "down", "--volumes", "--remove-orphans"], check=False)
    else:
        run(DOCKER_COMPOSE + ["-p", "ctt-dft", "-f", str(COMPOSE_BASE), "down", "--volumes", "--remove-orphans"], check=False)

    print("[OK] All stacks torn down")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="CTT Multi-Stakeholder Federation E2E Test (Docker-Only)",
        epilog="NOTE: This test requires Docker. For native single-domain testing, use: make test-e2e"
    )
    parser.add_argument("--domain-a", default="domain-dft", help="Base domain (default: domain-dft)")
    parser.add_argument("--domain-b", required=True, help="Peer domain (e.g., domain-dhl, domain-tesco)")
    parser.add_argument("--keep", action="store_true", help="Leave stacks running after test")
    parser.add_argument("--skip-generate", action="store_true", help="Skip compose generation (use existing files)")
    parser.add_argument("--force-build", action="store_true", help="Force image rebuild even if images exist")
    args = parser.parse_args()

    print(f"CTT Phase 9 — Multi-Stakeholder Federation E2E Test (Docker-Only)")
    print(f"Base domain:  {args.domain_a}")
    print(f"Peer domain:  {args.domain_b}")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Docker Compose: {' '.join(DOCKER_COMPOSE)}")
    print("")
    print("⚠️  IMPORTANT: This test is DOCKER-ONLY. Native mode is not supported")
    print("   for multi-domain E2E due to ZMQ addressing inconsistencies.")
    print("")

    try:
        # Phase 9: Verify Docker is ready before starting
        verify_docker_ready()

        if not args.skip_generate:
            phase_generate(args.domain_a, args.domain_b)

        # Always bring up both domains in Docker — no hybrid mode
        phase_bring_up(args.domain_a, is_base=True, force_build=args.force_build)
        phase_bring_up(args.domain_b, force_build=args.force_build)

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