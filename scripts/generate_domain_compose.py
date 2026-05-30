# =============================================================================
# FIXED generate_domain_compose.py — No PyYAML dependency, pure Python parser
# =============================================================================
#!/usr/bin/env python3
"""
scripts/generate_domain_compose.py

CTT Multi-Stakeholder Domain Compose Generator
Reads services/config/domains.yaml and emits docker-compose.<domain>.yml
Pure Python — no PyYAML required.

Usage:
    python scripts/generate_domain_compose.py --domain domain-dhl
    docker-compose -f deploy/docker-compose.domain-dhl.yml up -d

Design rationale:
    - One template, N domain configs = framework, not file explosion
    - Port offsets guarantee no collisions across domains on the same host
    - Federation peers are declarative: who subscribes to whom, on what topic
"""
import argparse
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DOMAINS_YAML = PROJECT_ROOT / "services" / "config" / "domains.yaml"
OUTPUT_DIR = PROJECT_ROOT / "deploy"

BASE_PORTS = {
    "engine_telemetry": 5555,
    "fusion_pub": 5556,
    "harvester_pub": 5560,
    "interpreter_pub": 5561,
    "policy_pub": 5563,
    "tactical_pub": 5564,
    "kafka_broker": 9092,
    "dashboard_rest": 5001,
    "grafana": 3000,
}


def parse_yaml_simple(path: Path) -> dict:
    """Minimal YAML parser for domains.yaml structure — no PyYAML needed."""
    text = path.read_text()
    data = {"domains": {}}
    current_domain = None
    current_key = None
    current_list = None
    in_peers = False
    peer_obj = None

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.strip().startswith("#"):
            continue
        
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        
        # Top-level domain start: "  domain-xxx:"
        if indent == 2 and stripped.endswith(":") and not stripped.startswith("-"):
            current_domain = stripped[:-1]
            data["domains"][current_domain] = {}
            current_key = None
            current_list = None
            in_peers = False
            continue
        
        if current_domain is None:
            continue
        
        # Key-value pairs
        if indent == 4 and ":" in stripped and not stripped.startswith("-"):
            key, val = stripped.split(":", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val == "":
                # Could be a list start
                data["domains"][current_domain][key] = []
                current_list = key
                current_key = None
                if key == "federation_peers":
                    in_peers = True
                else:
                    in_peers = False
            else:
                data["domains"][current_domain][key] = val
                current_key = key
                current_list = None
            continue
        
        # List items under federation_peers
        if in_peers and indent >= 6 and stripped.startswith("-"):
            item = stripped[1:].strip()
            if indent == 6:
                # New peer object
                peer_obj = {}
                data["domains"][current_domain]["federation_peers"].append(peer_obj)
                if ":" in item:
                    k, v = item.split(":", 1)
                    peer_obj[k.strip()] = v.strip().strip('"').strip("'")
            elif indent >= 8 and peer_obj is not None and ":" in item:
                k, v = item.split(":", 1)
                peer_obj[k.strip()] = v.strip().strip('"').strip("'")
            continue
        
        # Simple list items (not peers)
        if current_list is not None and not in_peers and indent == 6 and stripped.startswith("-"):
            item = stripped[1:].strip().strip('"').strip("'")
            data["domains"][current_domain][current_list].append(item)
            continue
    
    return data


def shifted_ports(offset: int) -> dict:
    return {k: v + offset for k, v in BASE_PORTS.items()}


def generate_compose(domain_id: str, domains_data: dict) -> str:
    domain = domains_data["domains"].get(domain_id)
    if not domain:
        raise ValueError(f"Domain '{domain_id}' not found in {DOMAINS_YAML}")

    offset = int(domain.get("port_offset", 0))
    ports = shifted_ports(offset)
    network = domain.get("network", f"ctt-{domain_id}")
    city_id = domain.get("city_id", domain_id)
    region = domain.get("region", "uk")
    description = domain.get("description", "")
    peers = domain.get("federation_peers", [])

    peer_envs = []
    for peer in peers:
        target = peer.get("target", "unknown")
        addr = peer.get("address", "")
        env_name = f"CTT_FEDERATION_PEER_{target.replace('-', '_').upper()}"
        peer_envs.append(f"      - {env_name}={addr}")
    peer_env_block = "\\n".join(peer_envs) if peer_envs else "      # No federation peers configured"

    extra_networks = ""
    if peers:
        extra_networks = f"""
      # Shared cross-domain federation backbone
      - ctt-federation"""

    compose = f"""# =============================================================================
# CTT Multi-Stakeholder Domain: {domain_id}
# {description}
# Generated by scripts/generate_domain_compose.py
# DO NOT EDIT MANUALLY — regenerate from domains.yaml
# =============================================================================

services:
  engine-{domain_id}:
    build:
      context: ..
      dockerfile: services/l1-engine/Dockerfile
    container_name: ctt-engine-{domain_id}
    ports:
      - "{ports['engine_telemetry']}:{ports['engine_telemetry']}"
      - "{27750 + offset}:27750"
    environment:
      - CTT_L1_ENGINE_HOST=engine-{domain_id}
      - CTT_FUSION_HOST=fusion-{domain_id}
      - CTT_DOMAIN_ID={domain_id}
    networks:
      - {network}
    healthcheck:
      test: ["CMD", "nc", "-z", "localhost", "{ports['engine_telemetry']}"]
      interval: 5s
      timeout: 2s
      start_period: 15s
      retries: 5
    restart: unless-stopped

  harvester-{domain_id}:
    build:
      context: ..
      dockerfile: services/data-pipeline/ingestor/Dockerfile
    container_name: ctt-harvester-{domain_id}
    environment:
      - HARVESTER_MODE=mock
      - HARVESTER_POLL_INTERVAL=5
      - CTT_HARVESTER_HOST=harvester-{domain_id}
      - CTT_INTERPRETER_HOST=interpreter-{domain_id}
      - CTT_DOMAIN_ID={domain_id}
    networks:
      - {network}
    healthcheck:
      test: ["CMD", "nc", "-z", "localhost", "{ports['harvester_pub']}"]
      interval: 10s
      timeout: 3s
      retries: 3
    restart: unless-stopped

  interpreter-{domain_id}:
    build:
      context: ..
      dockerfile: services/data-pipeline/interpreter/Dockerfile
    container_name: ctt-interpreter-{domain_id}
    environment:
      - CTT_HARVESTER_HOST=harvester-{domain_id}
      - CTT_INTERPRETER_HOST=interpreter-{domain_id}
      - CTT_FUSION_HOST=fusion-{domain_id}
      - CTT_DOMAIN_ID={domain_id}
    networks:
      - {network}
    healthcheck:
      test: ["CMD", "nc", "-z", "localhost", "{ports['interpreter_pub']}"]
      interval: 10s
      timeout: 3s
      retries: 3
    restart: unless-stopped

  fusion-{domain_id}:
    build:
      context: ..
      dockerfile: services/data-pipeline/fusion/Dockerfile
    container_name: ctt-fusion-{domain_id}
    ports:
      - "{ports['fusion_pub']}:{ports['fusion_pub']}"
    environment:
      - CTT_INTERPRETER_HOST=interpreter-{domain_id}
      - CTT_FUSION_HOST=fusion-{domain_id}
      - CTT_L1_ENGINE_HOST=engine-{domain_id}
      - CTT_DOMAIN_ID={domain_id}
    networks:
      - {network}
    healthcheck:
      test: ["CMD", "nc", "-z", "localhost", "{ports['fusion_pub']}"]
      interval: 10s
      timeout: 3s
      retries: 3
    restart: unless-stopped

  dashboard-{domain_id}:
    build:
      context: ..
      dockerfile: services/l2-bridge/Dockerfile
    container_name: ctt-dashboard-{domain_id}
    ports:
      - "{ports['dashboard_rest']}:5001"
    environment:
      - CTT_L1_ENGINE_HOST=engine-{domain_id}
      - CTT_FUSION_HOST=fusion-{domain_id}
      - CTT_POLICY_HOST=federation-bridge-{domain_id}
      - CTT_TACTICAL_HOST=orchestrator-{domain_id}
      - PYTHONPATH=/app/services/config:/app/services/l2-bridge
      - CTT_DOMAIN_ID={domain_id}
    networks:
      - {network}
    healthcheck:
      test:
        - CMD-SHELL
        - python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:5001/health', timeout=2)" || exit 1
      interval: 10s
      timeout: 3s
      start_period: 5s
      retries: 5
    restart: unless-stopped

  orchestrator-{domain_id}:
    build:
      context: ..
      dockerfile: services/l2-orchestrator/Dockerfile
    container_name: ctt-orchestrator-{domain_id}
    ports:
      - "{ports['tactical_pub']}:{ports['tactical_pub']}"
    environment:
      - CTT_L1_ENGINE_HOST=engine-{domain_id}
      - CTT_FUSION_HOST=fusion-{domain_id}
      - CTT_POLICY_HOST=federation-bridge-{domain_id}
      - CTT_TACTICAL_HOST=orchestrator-{domain_id}
      - PYTHONPATH=/app/services/config:/app/services/l2-orchestrator
      - CTT_DOMAIN_ID={domain_id}
    networks:
      - {network}
    depends_on:
      engine-{domain_id}:
        condition: service_healthy
      fusion-{domain_id}:
        condition: service_healthy
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 128M

  grafana-{domain_id}:
    image: grafana/grafana:latest
    container_name: ctt-grafana-{domain_id}
    ports:
      - "{ports['grafana']}:3000"
    environment:
      - GF_INSTALL_PLUGINS=marcusolsson-json-datasource
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=ctt-admin-2026
      - GF_SERVER_ROOT_URL=http://localhost:{ports['grafana']}
    volumes:
      - grafana_storage_{domain_id}:/var/lib/grafana
      - ../deploy/grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
      - ../deploy/grafana/datasources:/etc/grafana/provisioning/datasources:ro
    networks:
      - {network}
    depends_on:
      dashboard-{domain_id}:
        condition: service_healthy
    restart: unless-stopped

  zookeeper-{domain_id}:
    image: confluentinc/cp-zookeeper:latest
    container_name: ctt-zookeeper-{domain_id}
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
      ZOOKEEPER_TICK_TIME: 2000
    networks:
      - {network}
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 256M

  kafka-{domain_id}:
    image: confluentinc/cp-kafka:7.5.0
    container_name: ctt-kafka-{domain_id}
    depends_on:
      - zookeeper-{domain_id}
    ports:
      - "{ports['kafka_broker']}:9092"
    environment:
      KAFKA_BROKER_ID: {1 + offset}
      KAFKA_ZOOKEEPER_CONNECT: zookeeper-{domain_id}:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka-{domain_id}:29092,PLAINTEXT_HOST://localhost:{ports['kafka_broker']}
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT
      KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"
      KAFKA_HEAP_OPTS: -Xmx384M -Xms384M
    networks:
      - {network}
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 512M

  audit-logger-{domain_id}:
    build:
      context: ..
      dockerfile: services/l5-macro/Dockerfile
    container_name: ctt-audit-logger-{domain_id}
    command: python audit_logger.py
    environment:
      - CTT_L1_ENGINE_HOST=engine-{domain_id}
      - CTT_FUSION_HOST=fusion-{domain_id}
      - CTT_CITY_ID={city_id}
      - CTT_REGION={region}
      - CTT_DOMAIN_ID={domain_id}
      - KAFKA_BOOTSTRAP_SERVERS=kafka-{domain_id}:29092
      - KAFKA_TELEMETRY_TOPIC=ctt.telemetry.raw
      - KAFKA_PERTURBATION_TOPIC=ctt.perturbation.applied
      - KAFKA_CONSUMER_GROUP=ctt-l5-macro-{domain_id}
      - PYTHONPATH=/app/services/config:/app/services/l5-macro
    networks:
      - {network}
    depends_on:
      kafka-{domain_id}:
        condition: service_started
      engine-{domain_id}:
        condition: service_healthy
      fusion-{domain_id}:
        condition: service_healthy
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 128M

  federation-bridge-{domain_id}:
    build:
      context: ..
      dockerfile: services/l5-macro/Dockerfile
    container_name: ctt-federation-bridge-{domain_id}
    command: python federation_bridge.py
    ports:
      - "{ports['policy_pub']}:{ports['policy_pub']}"
    environment:
      - CTT_L1_ENGINE_HOST=engine-{domain_id}
      - CTT_FUSION_HOST=fusion-{domain_id}
      - CTT_CITY_ID={city_id}
      - CTT_REGION={region}
      - CTT_DOMAIN_ID={domain_id}
{peer_env_block}
      - KAFKA_BOOTSTRAP_SERVERS=kafka-{domain_id}:29092
      - KAFKA_TELEMETRY_TOPIC=ctt.telemetry.raw
      - KAFKA_POLICY_TOPIC=ctt.policy.structural
      - KAFKA_CONSUMER_GROUP=ctt-l5-macro-{domain_id}
      - PYTHONPATH=/app/services/config:/app/services/l5-macro
    networks:
      - {network}{extra_networks}
    depends_on:
      kafka-{domain_id}:
        condition: service_started
      engine-{domain_id}:
        condition: service_healthy
      fusion-{domain_id}:
        condition: service_healthy
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 128M

networks:
  {network}:
    driver: bridge
  ctt-federation:
    driver: bridge
    name: ctt-federation

volumes:
  grafana_storage_{domain_id}:
    driver: local
"""
    return compose


def main():
    parser = argparse.ArgumentParser(
        description="Generate docker-compose.<domain>.yml from domains.yaml registry"
    )
    parser.add_argument("--domain", required=True, help="Domain ID (e.g., domain-dhl)")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="Output directory")
    args = parser.parse_args()

    if not DOMAINS_YAML.exists():
        print(f"[ERR] Domain registry not found: {DOMAINS_YAML}")
        sys.exit(1)

    data = parse_yaml_simple(DOMAINS_YAML)
    compose_text = generate_compose(args.domain, data)

    out_path = Path(args.output_dir) / f"docker-compose.{args.domain}.yml"
    out_path.write_text(compose_text)
    print(f"[OK] Generated {out_path}")
    print(f"     Ports shifted by offset {data['domains'][args.domain].get('port_offset', 0)}")
    print(f"     Network: {data['domains'][args.domain].get('network', 'ctt-' + args.domain)}")
    if data['domains'][args.domain].get('federation_peers'):
        peers = [p.get('target', '?') for p in data['domains'][args.domain]['federation_peers']]
        print(f"     Federation peers: {', '.join(peers)}")
    print(f"\\nTo deploy:")
    print(f"    docker-compose -f deploy/docker-compose.{args.domain}.yml up --build -d")


if __name__ == "__main__":
    main()