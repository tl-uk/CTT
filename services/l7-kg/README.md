# CTT Layer 7 — Knowledge Graph & Emergent Learning

## Overview

Layer 7 implements the SSN-KG-Learning loop where agents remember their One-Shot
Successes as searchable autobiographies, recognise favourable contexts instead of
recalculating, and trigger tipping points no central planner can predict.

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

| File | Purpose |
|------|---------|
| `sig_compressor.py` | SSN → semantic vector embedding |
| `learn_mod.py` | Emergence detection & pattern mining |
| `kg_bridge.py` | ZMQ bridge between C++ engine and Python KG |
| `ssn_schema.ttl` | RDF/OWL ontology for SSN records |
| `ssn_experience_component.h` | C++ Flecs component (compressed vector) |

## Integration Points

- **L3 Cognitive Core**: BDI queries KG for successful procedures under similar stimuli
- **L5 Macro**: Population SSN mining feeds BPTK system dynamics
- **L6 Gaia-X**: KG triples can be federated via Dataspace Connector

## Status

🚧 Phase 9 starter — implementation pending Phase 10
