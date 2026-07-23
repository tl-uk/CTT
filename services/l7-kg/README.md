# CTT Layer 7 — Knowledge Graph, BDI & Emergent Learning

## Overview

Layer 7 implements the SSN-KG-Learning-BDI loop where agents remember their One-Shot
Successes as searchable autobiographies, recognise favourable contexts instead of
recalculating, and trigger tipping points no central planner can predict.

**Phase 13b Update:** BDI (Belief-Desire-Intention) engine now integrated with
calibrated thresholds from Fleet RFP TCO analysis.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  SSN Knowledge Graph (RDF/OWL)                              │
│  • System, Deployment, Observation triples                  │
│  • Searchable Autobiography per agent                       │
├─────────────────────────────────────────────────────────────┤
│  Semantic Signature Compressor (Python)                     │
│  • SSN observation → 128-dim vector                       │
│  • Hash of {Stimulus, Procedure, Result}                    │
├─────────────────────────────────────────────────────────────┤
│  BDI Engine (Phase 13b)                                     │
│  • Schmitt Trigger with hysteresis (prevents flip-flop)   │
│  • Habit resistance (exponential decay)                     │
│  • Dynamic thresholds: conservative|balanced|aggressive     │
│  • Calibrated from Fleet RFP 5-year TCO data              │
├─────────────────────────────────────────────────────────────┤
│  Coalition Engine (Phase 13c)                               │
│  • Guild/party formation for collective action              │
│  • Commitment threshold: 60% for collective action        │
├─────────────────────────────────────────────────────────────┤
│  Emergent Learning Module                                   │
│  • DBSCAN + Hawkes process for emergence detection          │
│  • Population habit resonance heatmap                       │
│  • Policy blind spot warnings                               │
├─────────────────────────────────────────────────────────────┤
│  KG Bridge (ZMQ)                                            │
│  • Bidirectional C++ ↔ Python                               │
│  • SSN_Experience_Component in Flecs ECS                    │
└─────────────────────────────────────────────────────────────┘
```

## Components

| File | Purpose | Phase |
|------|---------|-------|
| `sig_compressor.py` | SSN → semantic vector embedding | 9 |
| `learn_mod.py` | Emergence detection & pattern mining | 9 |
| `kg_bridge.py` | ZMQ bridge between C++ engine and Python KG | 9 |
| `bdi_engine.py` | BDI core: Belief→Desire→Intention→Action | 13a |
| `coalition_engine.py` | Coalition formation (guild system) | 13c |
| `abdt_agent_cache_v2.py` | Agent cache + BDI cycle at 1Hz | 13a |
| `ssn_schema.ttl` | RDF/OWL ontology for SSN records | 9 |
| `ssn_experience_component.h` | C++ Flecs component (compressed vector) | 9 |

## BDI Calibration (Phase 13b)

Thresholds derived from Fleet RFP TCO analysis:

| Policy Mode | Schmitt ON | Schmitt OFF | Hysteresis | Use Case |
|-------------|-----------|------------|-----------|----------|
| Conservative | £5,000 | -£2,000 | £1,000 | Wait for clear EV advantage |
| **Balanced** | **£0** | **-£5,000** | **£2,000** | **Switch at breakeven (default)** |
| Aggressive | -£5,000 | -£10,000 | £3,000 | Switch with policy support |

**Environment Variables:**
- `CTT_BDI_POLICY_MODE=balanced` — Select threshold profile
- `CTT_BDI_CYCLE_MS=1000` — BDI cycle interval (1Hz)
- `CTT_TCO_HORIZON_YEARS=5` — TCO calculation horizon
- `CTT_ENABLE_BDI=1` — Enable BDI reasoning

## Integration Points

- **L3 Cognitive Core**: BDI queries KG for successful procedures under similar stimuli
- **L4 Spatial**: SUMO corridor metrics feed into BDI belief updates
- **L5 Macro**: Population SSN mining feeds BPTK system dynamics
- **L6 Gaia-X**: KG triples can be federated via Dataspace Connector

## Status

🚧 Phase 13b — BDI thresholds calibrated, SUMO integration scaffolded
