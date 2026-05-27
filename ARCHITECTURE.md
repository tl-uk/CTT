# CTT Architectural Mapping

This document maps the conceptual 5-layer architecture (Mermaid diagram)
to the physical repository structure.

## Conceptual vs Physical

| Layer | Name | Physical Location | Rationale |
|:-----|:-----|:------------------|:----------|
| L1 | UI & Policy | `services/l2-bridge/dashboard.py`, Grafana | API Gateway serves the React/Deck.gl frontend. |
| L2 | Orchestration | `services/l2-bridge/`, `services/data-pipeline/` | Python orchestrator + ingestor adapters. |
| L3 | Cognitive Core | `services/l1-engine/` | C++ Flecs engine = L3's high-performance muscle. |
| L4 | Spatial | `services/l4-spatial/` (reserved) | SUMO/OSM integration (future). |
| L5 | Macro | `services/l3-analytics/`, `services/l5-macro/` | BPTK system dynamics + Kafka federation. |

## NOTE: `l1-engine` is L3

The directory `services/l1-engine/` predates the formal 5-layer model.
It is conceptually **Layer 3** (Cognitive-Reflexive Core). It contains:
- Flecs ECS (relational entity system)
- Energy/physics models
- BDI Schmitt Trigger logic
- ZMQ DataBridge for L2 integration

Renaming it would break Docker, CMake, and Python paths. The directory
name is legacy; the function is L3.

## Data Pipeline Layer Assignment

- **Harvester** (`data-pipeline/ingestor/`): L2 External Adapter
- **Interpreter** (`data-pipeline/interpreter/`): L2 Semantic Mapping
- **Fusion** (`data-pipeline/fusion/`): L2/L3 Boundary (Protobuf serialization)

## Security Bridge

The Security & Federation Bridge is **cross-cutting**, not a service:
- **CurveZMQ**: Inside `l1-engine/src/DataBridge.cpp`
- **mTLS 1.3**: Inside `l2-bridge/dashboard.py` (Flask/API Gateway)
- **Event Signing**: Planned for `l5-macro/federation_bridge.py`

## Phase 6 Scope

Phase 6 adds the first L5 physical component:
- `services/l5-macro/audit_logger.py` — ZMQ observer → Kafka (cold path)
- `services/l5-macro/federation_bridge.py` — L5 → L2 policy feedback loop
- KRaft Kafka in `deploy/docker-compose.yml`
- No changes to L1-L4 hot paths.