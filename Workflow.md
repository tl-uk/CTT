# CTT Working Layers — Terminal Workflow
# Phase 12d: Updated with start/stop discipline and disk management

---

## Daily Development Workflow

### 1. Start Colima (if not running)
```bash
colima status
# If "colima is not running":
colima start --cpu 4 --memory 8
```

### 2. Build and Deploy Full Stack
```bash
make compose-up-kg
```
This single command:
- Builds all 9 services via docker-bake (no cache export, no bloat)
- Tags images as `ctt-*:GIT_SHA`
- Starts all 13 containers via docker-compose

### 3. Verify Stack
```bash
# Quick health check
make healthcheck

# Or check individual components
curl -s http://localhost:5001/health | python -m json.tool
curl -s http://localhost:5001/api/v1/externality/summary | python -m json.tool

# View running containers
docker ps --format "table {{.Names}}\t{{.Status}}"
```

### 4. Stop Stack (CRITICAL — Do Not Skip)
```bash
make compose-down
```
This now:
- Stops all containers
- Removes old `ctt-*` images (prevents cross-session bloat)
- Prunes builder cache
- Clears `/tmp/ctt-docker-cache/*`

### 5. Stop Colima VM (Optional — Reclaims RAM)
```bash
colima stop
```

---

## Native Development (No Docker)

For debugging individual services without the full stack:

### Terminal 1: C++ Engine
```bash
make run-engine-bg
# Or foreground: make run-engine
```

### Terminal 2: Dashboard
```bash
cd services/l2-bridge
source .venv/bin/activate
export PYTHONPATH="$(pwd)/../config:$(pwd)"
python dashboard.py
```

### Terminal 3: Data Pipeline
```bash
make run-harvester-bg
make run-interpreter-bg
make run-fusion-bg
```

### Terminal 4: Verify
```bash
curl -s http://localhost:5001/health | python -m json.tool
curl -s http://localhost:5001/api/v1/externality/summary | python -m json.tool
```

### Stop Native Stack
```bash
make stop-native
```

---

## Disk Management

### Check disk usage
```bash
docker system df
```

### Clean up (safe)
```bash
make compose-down
make docker-prune-soft
```

### Nuclear reset (destructive, reclaims everything)
```bash
make colima-nuke
# Then rebuild:
make compose-up-kg
```

### Weekly maintenance
```bash
make colima-nuke && make bake-build-force && make compose-up-kg
```

---

## Multi-Domain E2E Test

### Normal run (uses existing images)
```bash
python scripts/test_multi_domain.py   --domain-a domain-dft   --domain-b domain-dhl   --keep
```

### With cleanup after test
```bash
python scripts/test_multi_domain.py   --domain-a domain-dft   --domain-b domain-dhl   --prune
```

### Force rebuild from scratch
```bash
python scripts/test_multi_domain.py   --domain-a domain-dft   --domain-b domain-dhl   --force-build --prune
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| High CPU / heat | Stack running 24h+ | `make compose-down` |
| `No such image: deploy-*` | Compose looking for old image names | Apply updated `docker-compose.yml` with `image:` fields |
| Build cache growing | Old images holding cache references | `make compose-down` (now prunes images) |
| Port already in use | Native engine still running | `make stop-native` |
| Colima not responding | VM stuck | `colima stop && colima start` |
| Engine unhealthy | Missing `nc` in image | Verify Dockerfile has `netcat-openbsd` |

---

## Service Quick Reference

| Service | Port | Docker Image | Native Command |
|---------|------|--------------|----------------|
| Engine (L3) | 5555, 27750 | `ctt-engine` | `make run-engine` |
| Dashboard (L1) | 5001 | `ctt-dashboard` | `python dashboard.py` |
| Orchestrator (L2) | 5564 | `ctt-orchestrator` | `python orchestrator.py` |
| Harvester (L2) | 5560 | `ctt-harvester` | `python harvester.py` |
| Interpreter (L2) | 5561 | `ctt-interpreter` | `python semantic_agent.py` |
| Fusion (L2) | 5556 | `ctt-fusion` | `python fusion_engine.py` |
| Audit Logger (L5) | — | `ctt-audit-logger` | `python audit_logger.py` |
| Federation Bridge (L5) | 5563 | `ctt-federation-bridge` | `python federation_bridge.py` |
| Knowledge Graph (L7) | 5565, 5566 | `ctt-kg` | `python kg_bridge.py` |
| Kafka | 9092 | `cp-kafka` | — |
| Zookeeper | 2181 | `cp-zookeeper` | — |
| Grafana | 3000 | `grafana/grafana` | — |

---

*Phase 12d — Updated with disk management and start/stop discipline*
