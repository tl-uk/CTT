"""
services/config/ports.py
Single source of truth for all ZMQ endpoints.
Keep in sync with services/l1-engine/include/PortConfig.h
"""

import os
import zmq

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
_POLICY_HOST = os.getenv("CTT_POLICY_HOST", "localhost")
_TACTICAL_HOST = os.getenv("CTT_TACTICAL_HOST", "localhost")

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

    # Phase 6 — L5 Policy Bridge (structural feedback to L2/L3)
    "POLICY_PUB": "tcp://*:5563",
    "POLICY_SUB": f"tcp://{_POLICY_HOST}:5563",

    # Phase 6.5 — L2 Orchestrator (tactical policies, separate from structural L5)
    "TACTICAL_PUB": "tcp://*:5564",
    "TACTICAL_SUB": f"tcp://{_TACTICAL_HOST}:5564",

    # Phase 12 — L7 Knowledge Graph
    "KG_PUB": "tcp://*:5565",
    "KG_SUB": "tcp://localhost:5566",

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

def get_resilient_socket(ctx, sock_type, is_sub=False):
    """
    Create a ZMQ socket with CTT resilience profile.
    Plug-and-use: survives service restarts without blocking the caller.
    """
    sock = ctx.socket(sock_type)
    sock.setsockopt(zmq.LINGER, 0)  # Don't hang on close
    if is_sub:
        sock.setsockopt(zmq.RCVTIMEO, 2000)
        sock.setsockopt(zmq.RECONNECT_IVL, 500)
        sock.setsockopt(zmq.RECONNECT_IVL_MAX, 3000)
    else:
        # PUB / PUSH: prevent memory explosion if downstream dies
        sock.setsockopt(zmq.SNDHWM, 1000)
    return sock