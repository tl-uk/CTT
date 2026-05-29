# services/l2-orchestrator/

## CTT Layer 2 Orchestrator — Federation Scheduler (Phase 7)

### Purpose
The L2 Orchestrator is the **federation scheduler** that decides when, what, and how
to orchestrate between real-time (ZMQ) and simulation (Kafka/REST) pipelines.
It is the brain that connects CTT to external agencies: BODS, Network Rail,
National Highways, Met Office, and EU freight operators via Gaia-X.

### Architecture

```
┌─────────────────────────────────────────┐
│         L2 Orchestrator                 │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐  │
│  │ ZMQ Rx  │ │Kafka Rx │ │REST Poll│  │  ← Ingestion
│  │ (fast)  │ │(batch)  │ │(agency) │  │
│  └────┬────┘ └────┬────┘ └────┬────┘  │
│       └─────────┬───────────┘         │
│                 ▼                     │
│       ┌─────────────────┐             │
│       │  Policy Engine   │             │  ← Decision
│       │  (BDI + Rules)   │             │
│       └────────┬────────┘             │
│                ▼                      │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐  │
│  │ ZMQ Tx  │ │Kafka Tx │ │REST Push│  │  ← Action
│  │(tactical)│ │(audit)  │ │(notify) │  │
│  └─────────┘ └─────────┘ └─────────┘  │
└─────────────────────────────────────────┘
```

### Protocol Adapters (Planned)

| Adapter | Protocol | Source | Phase |
|---------|----------|--------|-------|
| `bods_adapter.py` | REST polling | Bus Open Data Service (DfT) | 7 |
| `network_rail_adapter.py` | Kafka Connect | Network Rail / NaPTAN | 7 |
| `national_highways_adapter.py` | REST / WebSocket | Traffic England | 7 |
| `weather_adapter.py` | REST polling | Met Office DataPoint | 7 |
| `gaiax_adapter.py` | ODRL / EDC | EU freight operators | 7 |

### Design Principles

1. **Plug-and-use:** Each adapter is a standalone Python class. Disconnecting BODS
does not affect Network Rail ingestion.
2. **Graceful degradation:** If an agency API is down, the orchestrator falls back
to cached last-known-state and logs the outage.
3. **Deterministic scheduling:** The orchestrator runs on a 1-second cadence
(structural policies) and a 100-ms cadence (tactical policies), matching the
L3 engine tick rate.

### Current Status

- **Phase 6:** Swarm anomaly detection (ZMQ-only) implemented in `services/l2-bridge/orchestrator.py`.
- **Phase 7:** This directory will house the full multi-protocol scheduler.
