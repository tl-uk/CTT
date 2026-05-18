"""
services/config/ports.py
Single source of truth for all ZMQ endpoints.
Keep in sync with services/l1-engine/include/PortConfig.h
"""

import os

# =============================================================================
# Docker / Container Networking Overrides
# =============================================================================
# In Docker Compose, subscribers must connect to the PUBLISHER's service name,
# not localhost. Set these env vars in docker-compose.yml or .env.
# =============================================================================

_HARVESTER_HOST = os.getenv("CTT_HARVESTER_HOST", "localhost")
_INTERPRETER_HOST = os.getenv("CTT_INTERPRETER_HOST", "localhost")
_FUSION_HOST = os.getenv("CTT_FUSION_HOST", "localhost")
_L1_ENGINE_HOST = os.getenv("CTT_L1_ENGINE_HOST", "localhost")

ZMQ_PORTS = {
    # L1 Engine
    "L1_TELEMETRY_PUB": "tcp://*:5555",
    "L1_TELEMETRY_SUB": f"tcp://{_L1_ENGINE_HOST}:5555",

    "L1_PERTURBATION_PUB": "tcp://*:5556",
    "L1_PERTURBATION_SUB": f"tcp://{_FUSION_HOST}:5556",

    # Data Pipeline
    "HARVESTER_PUB": "tcp://*:5560",
    "HARVESTER_SUB": f"tcp://{_HARVESTER_HOST}:5560",

    "INTERPRETER_PUB": "tcp://*:5561",
    "INTERPRETER_SUB": f"tcp://{_INTERPRETER_HOST}:5561",

    # Legacy / Direct (deprecated, non-conflicting)
    "LEGACY_INGESTOR_PUB": "tcp://*:5562",
}

def get_bind_address(role: str) -> str:
    """Address for a PUB socket to bind."""
    key = f"{role}_PUB"
    return ZMQ_PORTS[key]

def get_connect_address(role: str) -> str:
    """Address for a SUB socket to connect."""
    key = f"{role}_SUB"
    return ZMQ_PORTS[key]