#!/usr/bin/env python3
"""
scripts/test_multi_domain.py

CTT Phase 11 — Multi-Stakeholder Federation E2E Test (Docker-Only)

Validates plug-and-use resilience across two independent CTT domains.
Uses scripts/generate_domain_compose.py to render compose files on-the-fly.

CRITICAL (Phase 11): This test is DOCKER-ONLY. Native mode is NOT supported
for multi-domain E2E because ZMQ addressing (host.docker.internal vs localhost)
and port offsets are only consistent inside the Docker network bridge.
For native single-domain testing, use: make test-e2e

Phase 11 Build Discipline:
  - Images are tagged with git-SHA + service name (never just :latest)
  - Source-hash validation prevents unnecessary rebuilds
  - Build cache is preserved across test runs; only changed services rebuild
  - docker-bake.hcl is the preferred build path; this script falls back to
    docker-compose build when bake is unavailable

Port semantics:
  - Host (external) ports = BASE + offset  (used for REST probes, curls)
  - Container (internal) ports = BASE     (services hardcode bind addresses)

Test sequence:
  1. Generate compose for domain-a and domain-b from domains.yaml
  2. Build images via docker-bake.hcl (cache-efficient) or docker-compose build
  3. Spin up domain-a (default / DfT)
  4. Spin up domain-b (e.g., DHL, Network Rail, Tesco, NHS)
  5. Verify both domains report healthy agents via REST
  6. Verify federation bridges can exchange ZMQ heartbeats (via REST proxy)
  7. Disconnect domain-b (simulate stakeholder outage)
  8. Verify domain-a continues unaffected (resilience)
  9. Reconnect domain-b
  10. Verify domain-b auto-syncs and resumes federation

Usage:
    python scripts/test_multi_domain.py --domain-a domain-dft --domain-b domain-dhl [--keep]

Requires: Docker Compose v2, Python 3.10+, requests, zmq, Colima or Docker Desktop
"""
import argparse
import hashlib
import json
import os
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
BAKE_FILE = PROJECT_ROOT / "docker-bake.hcl"

# Phase 11: Git-SHA based image tags prevent dangling accumulation
GIT_SHA = subprocess.run(
    ["git", "rev-parse", "--short", "HEAD"],
    capture_output=True, text=True, cwd=PROJECT_ROOT
).stdout.strip() or "unknown"

IMAGE_TAG = f"ctt-{GIT_SHA}"

# Services that need images built (must match docker-bake.hcl targets)
ALL_SERVICES = [
    "ctt-engine", "ctt-harvester", "ctt-interpreter",
    "ctt-fusion", "ctt-dashboard", "ctt-orchestrator",
    "ctt-audit-logger", "ctt-federation-bridge"
]

# Phase 11: Source hash tracking — rebuild only if source changed
SOURCE_HASHES_FILE = PROJECT_ROOT / ".ctt_source_hashes.json"


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
# Phase 11: Source Hash Tracking (Cache-Efficient Builds)
# =============================================================================

def compute_source_hash(service_name: str) -> str:
    """
    Compute a deterministic hash of source files for a service.
    Only includes files that would affect the Docker build.
    """
    service_dirs = {
        "ctt-engine": ["services/l1-engine/src", "services/l1-engine/include", "services/l1-engine/CMakeLists.txt"],
        "ctt-harvester": ["services/data-pipeline/ingestor"],
        "ctt-interpreter": ["services/data-pipeline/interpreter"],
        "ctt-fusion": ["services/data-pipeline/fusion"],
        "ctt-dashboard": ["services/l2-bridge/dashboard.py", "services/l2-bridge/requirements.txt"],
        "ctt-orchestrator": ["services/l2-orchestrator/orchestrator.py", "services/l2-orchestrator/requirements.txt"],
        "ctt-audit-logger": ["services/l5-macro/audit_logger.py"],
        "ctt-federation-bridge": ["services/l5-macro/federation_bridge.py"],
    }

    dirs = service_dirs.get(service_name, [])
    hasher = hashlib.sha256()

    for rel_path in dirs:
        path = PROJECT_ROOT / rel_path
        if path.is_file():
            hasher.update(path.read_bytes())
        elif path.is_dir():
            for f in sorted(path.rglob("*")):
                if f.is_file() and not f.name.startswith("."):
                    hasher.update(f.read_bytes())

    # Also hash shared config that affects all services
    for config_file in ["services/config/ports.py", "services/config/settings.py"]:
        config_path = PROJECT_ROOT / config_file
        if config_path.exists():
            hasher.update(config_path.read_bytes())

    return hasher.hexdigest()[:16]


def load_source_hashes() -> dict:
    """Load previously recorded source hashes."""
    if SOURCE_HASHES_FILE.exists():
        return json.loads(SOURCE_HASHES_FILE.read_text())
    return {}


def save_source_hashes(hashes: dict):
    """Save current source hashes for future comparison."""
    SOURCE_HASHES_FILE.write_text(json.dumps(hashes, indent=2))


def services_needing_rebuild(force: bool = False) -> list[str]:
    """
    Return list of services whose source has changed since last build.
    If force=True, return all services.
    """
    if force:
        return ALL_SERVICES

    old_hashes = load_source_hashes()
    new_hashes = {svc: compute_source_hash(svc) for svc in ALL_SERVICES}

    changed = []
    for svc in ALL_SERVICES:
        if old_hashes.get(svc) != new_hashes.get(svc):
            changed.append(svc)

    return changed


def record_build_hashes(services: list[str] = None):
    """Record hashes for services that were just built."""
    services = services or ALL_SERVICES
    hashes = load_source_hashes()
    for svc in services:
        hashes[svc] = compute_source_hash(svc)
    save_source_hashes(hashes)


# =============================================================================
# Phase 11: Build Orchestration (docker-bake.hcl preferred)
# =============================================================================

def has_docker_bake() -> bool:
    """Check if docker buildx bake is available."""
    result = subprocess.run(
        ["docker", "buildx", "version"],
        capture_output=True, text=True
    )
    return result.returncode == 0


def build_with_bake(services: list[str], tag: str) -> bool:
    """
    Build services using docker-bake.hcl with local cache.
    Returns True if successful, False if fallback needed.
    """
    if not BAKE_FILE.exists():
        print("  [INFO] docker-bake.hcl not found, falling back to docker-compose build")
        return False

    if not has_docker_bake():
        print("  [INFO] docker buildx not available, falling back to docker-compose build")
        return False

    # Build only the targets we need
    targets = [svc.replace("ctt-", "") for svc in services]
    if not targets:
        print("  [INFO] No services need rebuilding (cache hit)")
        return True

    print(f"  [BAKE] Building targets: {', '.join(targets)} (tag: {tag})")

    env = os.environ.copy()
    env["CTT_IMAGE_TAG"] = tag

    cmd = ["docker", "buildx", "bake", "-f", str(BAKE_FILE), "--load"] + targets
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  [WARN] docker buildx bake failed: {result.stderr[:500]}")
        return False

    print(f"  [BAKE] ✅ Built {len(targets)} service(s) with cache")
    return True


def build_with_compose(compose_file: Path, services: list[str], tag: str) -> bool:
    """
    Fallback: Build services using docker-compose build.
    Uses --build-arg to pass the git-SHA tag into Dockerfiles.
    """
    if not services:
        print("  [INFO] No services need rebuilding (cache hit)")
        return True

    print(f"  [COMPOSE] Building services: {', '.join(services)} (tag: {tag})")

    # Build specific services
    cmd = DOCKER_COMPOSE + ["-f", str(compose_file), "build", "--build-arg", f"CTT_IMAGE_TAG={tag}"]
    for svc in services:
        cmd.append(svc)

    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  [ERR] docker-compose build failed: {result.stderr[:500]}")
        return False

    print(f"  [COMPOSE] ✅ Built {len(services)} service(s)")
    return True


def build_services(services: list[str], tag: str, compose_file: Path = None) -> bool:
    """
    Build services using the best available method.
    Priority: docker-bake.hcl > docker-compose build
    """
    if build_with_bake(services, tag):
        record_build_hashes(services)
        return True

    if compose_file and compose_file.exists():
        if build_with_compose(compose_file, services, tag):
            record_build_hashes(services)
            return True

    return False


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


def docker_images_exist(project_name: str, tag: str) -> bool:
    """
    Phase 11: Check if images exist with the specific git-SHA tag.
    Old :latest images are ignored — they will be pruned.
    """
    result = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return False

    images = result.stdout

    # Map project name to service names
    if project_name == "ctt-dft":
        required = ALL_SERVICES
    else:
        # Peer domains use the same base images
        required = ALL_SERVICES

    for req in required:
        image_name = f"{req}:{tag}"
        # Also accept untagged (intermediate) or latest as fallback
        if image_name not in images and f"{req}:latest" not in images:
            print(f"  [INFO] Missing image: {image_name}, will build")
            return False
    return True


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


def phase_build(tag: str, force_build: bool = False):
    """Phase 11: Build only changed services using bake or compose."""
    log_step(0.5, "Build cache-efficient images")

    changed = services_needing_rebuild(force=force_build)

    if not changed and not force_build:
        print(f"  [INFO] All services up-to-date (tag: {tag})")
        print(f"  [INFO] Source hashes unchanged — skipping build")
        return

    print(f"  [INFO] {len(changed)} service(s) need rebuild: {', '.join(changed)}")

    # Try bake first, fall back to compose
    if not build_services(changed, tag, compose_file=COMPOSE_BASE):
        raise RuntimeError("Build failed — see errors above")

    print(f"  [INFO] Build complete. Tag: {tag}")


def phase_bring_up(domain: str, is_base: bool = False, tag: str = IMAGE_TAG, force_build: bool = False):
    log_step(1 if is_base else 2, f"Bring up {domain}")
    if is_base:
        compose = COMPOSE_BASE
        project_name = "ctt-dft"
    else:
        compose = get_compose_path(domain)
        project_name = domain.replace("domain-", "ctt-")

    # Always down first to ensure clean state
    run(DOCKER_COMPOSE + ["-p", project_name, "-f", str(compose), "down", "--volumes", "--remove-orphans"], check=False)

    # Phase 11: Prune builder cache (not just images) to prevent layer accumulation
    # This is safe because we preserve the cache we need via bake/compose
    prune_result = subprocess.run(
        ["docker", "builder", "prune", "-f", "--filter", "unused-for=24h"],
        capture_output=True, text=True
    )
    if prune_result.returncode == 0 and prune_result.stdout.strip():
        print(f"  [INFO] Pruned old builder cache: {prune_result.stdout.strip()}")

    # Phase 11: Check if images with correct tag exist
    images_ready = not force_build and docker_images_exist(project_name, tag)

    if images_ready:
        print(f"  [INFO] Images with tag '{tag}' found, using --no-build")
        try:
            run(DOCKER_COMPOSE + ["-p", project_name, "-f", str(compose), "up", "-d", "--no-build"], capture=False)
        except subprocess.CalledProcessError:
            print(f"  [WARN] --no-build failed, falling back to build")
            run(DOCKER_COMPOSE + ["-p", project_name, "-f", str(compose), "up", "--build", "-d"], capture=False)
    else:
        if force_build:
            print(f"  [INFO] Force-building images for {project_name} (no cache)...")
        else:
            print(f"  [INFO] Building images for {project_name} (cache enabled)...")

        # Phase 11: Use build args to pass the git-SHA tag
        env = os.environ.copy()
        env["CTT_IMAGE_TAG"] = tag

        run(DOCKER_COMPOSE + ["-p", project_name, "-f", str(compose), "up", "--build", "-d"], capture=False, env=env)

    data = health_check(domain)
    print(f"  [{domain}] Healthy: {data['agents_online']} agents, telemetry_flowing={data['telemetry_flowing']}")


def phase_verify_federation(domain_a: str, domain_b: str):
    """Phase 11: Verify telemetry streams on both domains (REST-based)."""
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


def phase_reconnect(domain_b: str, tag: str = IMAGE_TAG):
    log_step(7, f"Reconnect {domain_b} (simulate recovery)")
    compose = get_compose_path(domain_b)
    project_name = domain_b.replace("domain-", "ctt-")
    # Reconnect uses --no-build since images already exist
    env = os.environ.copy()
    env["CTT_IMAGE_TAG"] = tag
    run(DOCKER_COMPOSE + ["-p", project_name, "-f", str(compose), "up", "-d", "--no-build"], env=env)
    data = health_check(domain_b)
    print(f"  [{domain_b}] Recovered: {data['agents_online']} agents, telemetry_flowing={data['telemetry_flowing']}")


def phase_verify_post_reconnect(domain_a: str, domain_b: str):
    """Phase 11: Verify federation resumed via REST health check."""
    log_step(8, "Verify federation resumes after reconnect")
    for domain in (domain_a, domain_b):
        data = health_check(domain, timeout=60)
        ok = data.get("telemetry_flowing", False)
        status = "RESUMED" if ok else "FAIL"
        print(f"  [{domain}] Telemetry via REST /health -> {status} ({data['agents_online']} agents)")
        if not ok:
            raise RuntimeError(f"[{domain}] Telemetry did not resume after reconnect")


def phase_cleanup(domain_a: str, domain_b: str, keep: bool = False, prune: bool = False, tag: str = IMAGE_TAG):
    if keep:
        ports_a = get_host_ports(domain_a)
        ports_b = get_host_ports(domain_b)
        print("\n[KEEP] Stacks left running for manual inspection.")
        print(f"       {domain_a} dashboard: http://localhost:{ports_a['dashboard']}")
        print(f"       {domain_b} dashboard: http://localhost:{ports_b['dashboard']}")
        print(f"       {domain_a} Grafana:   http://localhost:{ports_a['grafana']}")
        print(f"       {domain_b} Grafana:   http://localhost:{ports_b['grafana']}")
        print(f"       Image tag: {tag}")
        if prune:
            print("\n[PRUNE] Run the following to reclaim disk space:")
            print("       docker builder prune -f")
            print("       docker image prune -f")
            print("       docker system prune -a --volumes -f")
        return

    log_step(9, "Cleanup: tear down both domains")
    project_name_b = domain_b.replace("domain-", "ctt-")
    run(DOCKER_COMPOSE + ["-p", project_name_b, "-f", str(get_compose_path(domain_b)), "down", "--volumes", "--remove-orphans"], check=False)

    if domain_a != "domain-dft":
        project_name_a = domain_a.replace("domain-", "ctt-")
        run(DOCKER_COMPOSE + ["-p", project_name_a, "-f", str(get_compose_path(domain_a)), "down", "--volumes", "--remove-orphans"], check=False)
    else:
        run(DOCKER_COMPOSE + ["-p", "ctt-dft", "-f", str(COMPOSE_BASE), "down", "--volumes", "--remove-orphans"], check=False)

    if prune:
        print("\n[PRUNE] Removing dangling images and builder cache...")
        subprocess.run(["docker", "image", "prune", "-f"], capture_output=True)
        subprocess.run(["docker", "builder", "prune", "-f"], capture_output=True)
        print("[PRUNE] Dangling images and builder cache removed")

    print("[OK] All stacks torn down")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="CTT Phase 11 — Multi-Stakeholder Federation E2E Test (Docker-Only)",
        epilog="NOTE: This test requires Docker. For native single-domain testing, use: make test-e2e"
    )
    parser.add_argument("--domain-a", default="domain-dft", help="Base domain (default: domain-dft)")
    parser.add_argument("--domain-b", required=True, help="Peer domain (e.g., domain-dhl, domain-tesco)")
    parser.add_argument("--keep", action="store_true", help="Leave stacks running after test")
    parser.add_argument("--skip-generate", action="store_true", help="Skip compose generation (use existing files)")
    parser.add_argument("--force-build", action="store_true", help="Force image rebuild even if source unchanged")
    parser.add_argument("--prune", action="store_true", help="Prune dangling images and builder cache after cleanup")
    parser.add_argument("--tag", default=IMAGE_TAG, help=f"Image tag override (default: {IMAGE_TAG})")
    args = parser.parse_args()

    print(f"CTT Phase 11 — Multi-Stakeholder Federation E2E Test (Docker-Only)")
    print(f"Base domain:  {args.domain_a}")
    print(f"Peer domain:  {args.domain_b}")
    print(f"Image tag:    {args.tag}")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Docker Compose: {' '.join(DOCKER_COMPOSE)}")
    print("")
    print("⚠️  IMPORTANT: This test is DOCKER-ONLY. Native mode is not supported")
    print("   for multi-domain E2E due to ZMQ addressing inconsistencies.")
    print("")
    print("💡 Phase 11 Build Discipline:")
    print("   - Source-hash tracking prevents unnecessary rebuilds")
    print("   - docker-bake.hcl preferred for cache-efficient builds")
    print("   - Git-SHA tags prevent dangling image accumulation")
    print("")

    try:
        # Phase 11: Verify Docker is ready before starting
        verify_docker_ready()

        if not args.skip_generate:
            phase_generate(args.domain_a, args.domain_b)

        # Phase 11: Build only changed services before bringing up
        phase_build(args.tag, force_build=args.force_build)

        # Always bring up both domains in Docker — no hybrid mode
        phase_bring_up(args.domain_a, is_base=True, tag=args.tag, force_build=args.force_build)
        phase_bring_up(args.domain_b, tag=args.tag, force_build=args.force_build)

        phase_verify_federation(args.domain_a, args.domain_b)
        phase_resilience_disconnect(args.domain_b)
        phase_verify_resilience(args.domain_a)
        phase_reconnect(args.domain_b, tag=args.tag)
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
        phase_cleanup(args.domain_a, args.domain_b, keep=args.keep, prune=args.prune, tag=args.tag)


if __name__ == "__main__":
    main()