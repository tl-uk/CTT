# CTT Architectural Mapping
# Phase 12d: Updated with L7 Knowledge Graph and Docker service mapping

This document maps the conceptual 5-layer architecture (Mermaid diagram)
to the physical repository structure.

---

## Conceptual vs Physical

| Layer | Name | Physical Location | Docker Image | Rationale |
|:------|:-----|:------------------|:-------------|:----------|
| L1 | UI & Policy | `services/l2-bridge/dashboard.py` | `ctt-dashboard` | Flask API Gateway serves frontend |
| L1 | UI & Policy | `deploy/grafana/` | `grafana/grafana` | Metrics visualization |
| L2 | Orchestration | `services/l2-bridge/` | `ctt-dashboard` | Python telemetry bridge |
| L2 | Orchestration | `services/l2-orchestrator/` | `ctt-orchestrator` | Asyncio orchestrator with Swarm Guard |
| L2 | Orchestration | `services/data-pipeline/ingestor/` | `ctt-harvester` | External data adapters |
| L2 | Orchestration | `services/data-pipeline/interpreter/` | `ctt-interpreter` | Semantic mapping agent |
| L2 | Orchestration | `services/data-pipeline/fusion/` | `ctt-fusion` | L2/L3 boundary, Protobuf serialization |
| L3 | Cognitive Core | `services/l1-engine/` | `ctt-engine` | **Legacy name** — see below |
| L4 | Spatial | `services/l4-spatial/` | — | Reserved for SUMO/OSM integration |
| L5 | Macro | `services/l5-macro/` | `ctt-audit-logger`, `ctt-federation-bridge` | Kafka federation, BPTK dynamics |
| L5 | Macro | `services/l3-analytics/` | — | System dynamics models |
| L6 | Security | Cross-cutting | — | CurveZMQ, mTLS, event signing |
| L7 | Knowledge Graph | `services/l7-kg/` | `ctt-kg` | SSN KG, semantic signatures, emergent learning |

---

## NOTE: `l1-engine` is L3

The directory `services/l1-engine/` predates the formal 5-layer model.
It is conceptually **Layer 3** (Cognitive-Reflexive Core). It contains:
- Flecs ECS (relational entity system)
- Energy/physics models
- BDI Schmitt Trigger logic
- ZMQ DataBridge for L2 integration
- 10ms deterministic tick loop

**Renaming it would break Docker, CMake, and Python paths.** The directory
name is legacy; the function is L3.

---

## Data Pipeline Layer Assignment

- **Harvester** (`data-pipeline/ingestor/`): L2 External Adapter
- **Interpreter** (`data-pipeline/interpreter/`): L2 Semantic Mapping
- **Fusion** (`data-pipeline/fusion/`): L2/L3 Boundary (Protobuf serialization)

---

## Security Bridge (Cross-Cutting)

The Security & Federation Bridge is **not a standalone service**:
- **CurveZMQ**: Inside `l1-engine/src/DataBridge.cpp`
- **mTLS 1.3**: Inside `l2-bridge/dashboard.py` (Flask/API Gateway)
- **Event Signing**: Planned for `l5-macro/federation_bridge.py`
- **Gaia-X / ODRL**: `services/l6-gaiax/` (EDC gateway, policy enforcer)

---

## L7 Knowledge Graph (Phase 12)

The L7 layer provides:
- **SSN Knowledge Graph** (`kg_bridge.py`): RDF/OWL store per agent
- **Semantic Signature Compressor** (`sig_compressor.py`): SSN → vector embedding
- **SSN_Experience_Component** (`include/ssn_experience_component.h`): C++ Flecs component for compressed vectors
- **Emergent Learning Module** (`learn_mod.py`): Population pattern mining, tipping point detection

The L7 service (`ctt-kg`) exposes:
- ZMQ PUB on 5565 (telemetry)
- ZMQ SUB on 5566 (perturbations)

---

## Infrastructure Services

| Service | Image | Purpose | Port |
|---------|-------|---------|------|
| Kafka | `confluentinc/cp-kafka:7.5.0` | Federated event backbone | 9092 |
| Zookeeper | `confluentinc/cp-zookeeper:latest` | Kafka coordination | 2181 |
| Grafana | `grafana/grafana:latest` | Metrics dashboard | 3000 |

---

## Docker Compose Architecture

All CTT services are orchestrated via `deploy/docker-compose.yml`:
- **Build**: Docker Bake (`docker-bake.hcl`) builds images tagged `ctt-*:GIT_SHA`
- **Deploy**: Docker Compose uses `image: ctt-*:${CTT_IMAGE_TAG}` to reference pre-built images
- **Network**: All services share `ctt` bridge network
- **Healthchecks**: Engine (5555), Fusion (5556), Dashboard (5001), Harvester (5560), Interpreter (5561), KG (5565/5566)

---

## Build System

| Target | Command | Purpose |
|--------|---------|---------|
| Native engine | `make build-engine` | CMake + Ninja, produces `CTT_Engine` |
| Docker all | `make compose-up-kg` | Bake build + Compose deploy |
| Force rebuild | `make bake-build-force` | No cache, no export, single pass |
| Stop stack | `make compose-down` | Stops containers, prunes images + cache |

---

*Phase 12d — Updated with L7 Knowledge Graph and Docker service mapping*
