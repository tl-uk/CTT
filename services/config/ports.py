"""
services/config/ports.py
Single source of truth for all ZMQ endpoints.
Keep in sync with services/l1-engine/include/PortConfig.hpp
"""

# CTT ZMQ Topology
# Pattern: PUB binds, SUB connects (standard) except where noted.

ZMQ_PORTS = {
    # L1 Engine
    "L1_TELEMETRY_PUB": "tcp://*:5555",      # C++ engine broadcasts state
    "L1_TELEMETRY_SUB": "tcp://localhost:5555",  # Dashboard / tests listen

    "L1_PERTURBATION_PUB": "tcp://*:5556",   # Fusion binds here; C++ SUB connects
    "L1_PERTURBATION_SUB": "tcp://localhost:5556", # C++ engine connects

    # Data Pipeline
    "HARVESTER_PUB": "tcp://*:5560",         # Harvester binds; Interpreter connects
    "HARVESTER_SUB": "tcp://localhost:5560", # Interpreter input

    "INTERPRETER_PUB": "tcp://*:5561",       # Interpreter binds; Fusion connects
    "INTERPRETER_SUB": "tcp://localhost:5561", # Fusion input

    # Legacy / Direct (deprecated, non-conflicting)
    "LEGACY_INGESTOR_PUB": "tcp://*:5562",   # Old main.py direct-to-engine port
}

def get_bind_address(role: str) -> str:
    """Address for a PUB socket to bind."""
    key = f"{role}_PUB"
    return ZMQ_PORTS[key]

def get_connect_address(role: str) -> str:
    """Address for a SUB socket to connect."""
    key = f"{role}_SUB"
    return ZMQ_PORTS[key]
