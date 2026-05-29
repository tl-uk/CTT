# services/l6-gaiax/

## CTT Layer 6 — Gaia-X Trust Overlay (Phase 7)

### Purpose
Gaia-X is not a transport technology; it is a **trust overlay** that sits above
Kubernetes and enforces data sovereignty, identity federation, and usage policies
between international stakeholders (UK DfT, EU ports, DHL, Tesco).

CTT implements Gaia-X as an **optional sidecar layer**. The core ZMQ/Kafka
pipeline is policy-agnostic. Gaia-X components govern only the *external* data
sharing boundary.

### Architecture

```
┌─────────────────────────────────────────────┐
│           Gaia-X Trust Overlay               │
│  ┌─────────────┐ ┌─────────────┐           │
│  │ Eclipse Dataspace Connector │           │ ← Policy negotiation
│  │    (EDC) Gateway Pod        │           │
│  └──────┬──────┘ └──────┬──────┘           │
│         └────────┬──────┘                   │
│                  ▼                            │
│  ┌─────────────────────────────┐           │
│  │  Self-Description Registry   │           │ ← Identity
│  │  (JSON-LD + DID + VC)        │           │
│  └─────────────────────────────┘           │
│  ┌─────────────────────────────┐           │
│  │  ODRL Policy Enforcer        │           │ ← Usage constraints
│  │  (e.g., "Tesco data: carbon  │           │
│  │   calc only, no competitors") │           │
│  └─────────────────────────────┘           │
└─────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│         CTT Core (L1-L5)                     │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  │ Engine  │ │Dashboard│ │ Kafka   │       │
│  │ (ZMQ)   │ │ (REST)  │ │ (Audit) │       │
│  └─────────┘ └─────────┘ └─────────┘       │
└─────────────────────────────────────────────┘
```

### Key Components

#### 1. Eclipse Dataspace Connector (EDC)
- **Location:** `edc_gateway.py` — runs as a K8s sidecar.
- **Function:** When an EU freight operator wants to stream telemetry into CTT,
  the data passes through EDC first. EDC verifies that exchange terms match both
  parties' ODRL policy definitions before allowing the packet into the ingestor.
- **CTT Integration:** EDC output writes to the same ZMQ/Kafka topics as domestic
  sources. CTT does not know if data is Gaia-X mediated or local.

#### 2. Self-Description (JSON-LD + Verifiable Credentials)
- **Location:** `self_description.json` — example file for a UK freight terminal.
- **Function:** Every CTT edge node (terminal, ingestor, twin) publishes a
  machine-readable identity file. Uses W3C Decentralized Identifiers (DIDs) and
  Verifiable Credentials (VCs) to prove origin without managing the agency's IT.
- **CTT Integration:** The `federation_bridge.py` `meta` block already includes
  `city_id`, `region`, `source_host`. Extending this to include a Gaia-X DID is trivial.

#### 3. ODRL Policy Enforcement
- **Location:** `policy_enforcer.py` — attaches usage constraints to data streams.
- **Function:** Tesco can share HGV telemetry with a strict ODRL policy:
  *"This telemetry may only be used by the TransiT Hub for carbon emission
  calculations and cannot be shared with competing commercial logistics providers."*
- **CTT Integration:** Enforced programmatically before the ingestor processes the
  packet. Can be implemented as Kafka headers or topic naming conventions
  (`ctt.telemetry.raw.tesco.carbon_only`) without changing the payload schema.

### EU Interoperability

Aligning with Gaia-X means the UK can seamlessly hook into:
- **Catena-X** (automotive supply chains)
- **EuroTube** (logistics data spaces)
- **Port of Rotterdam / Hamburg** (maritime twins)

### Current Status

- **Phase 6:** Architecture hooks designed. No implementation.
- **Phase 7:** Deploy EDC gateway as K8s sidecar. Generate Self-Description files
  for `city-01` and `city-02` nodes.
- **Phase 8:** ODRL policy enforcement on Kafka topics.

### Files

| File | Purpose |
|------|---------|
| `README.md` | This document |
| `Dockerfile` | EDC gateway container (Java-based or lightweight proxy) |
| `self_description.json` | Example JSON-LD for a UK freight terminal |
| `policy_enforcer.py` | ODRL validation stub |
| `edc_gateway.py` | Eclipse Dataspace Connector proxy stub |
