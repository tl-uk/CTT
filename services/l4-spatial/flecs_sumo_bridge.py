#!/usr/bin/env python3
"""
services/l4-spatial/flecs_sumo_bridge.py

Phase 14c: Flecs ↔ SUMO Entity Synchronization

Purpose: Bidirectional entity mapping between Flecs ECS and SUMO vehicles.
Handles coordinate transforms, vehicle lifecycle, and mode transitions.

MMOG Analogy: This is the "entity interpolation" layer — ensuring the physics
engine (SUMO) and the game state (Flecs) stay synchronized.
"""
import math
from typing import Dict, Optional, Tuple

# =============================================================================
# Coordinate Transforms
# =============================================================================

class CoordinateTransform:
    """Simple lat/lon ↔ SUMO x/y transform (simplified — use proper UTM in production)."""

    def __init__(self, origin_lat: float = 51.0, origin_lon: float = 1.0):
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        # Approximate: 1 degree lat ≈ 111km, 1 degree lon ≈ 111km * cos(lat)
        self.m_per_deg_lat = 111_320.0
        self.m_per_deg_lon = 111_320.0 * math.cos(math.radians(origin_lat))

    def latlon_to_xy(self, lat: float, lon: float) -> Tuple[float, float]:
        x = (lon - self.origin_lon) * self.m_per_deg_lon
        y = (lat - self.origin_lat) * self.m_per_deg_lat
        return x, y

    def xy_to_latlon(self, x: float, y: float) -> Tuple[float, float]:
        lon = self.origin_lon + (x / self.m_per_deg_lon)
        lat = self.origin_lat + (y / self.m_per_deg_lat)
        return lat, lon


# =============================================================================
# Entity Lifecycle Manager
# =============================================================================

class EntityLifecycleManager:
    """
    Manages the mapping between Flecs entities and SUMO vehicles.
    MMOG analogy: "Spawn manager" — controls when entities enter/exit the zone.
    """

    def __init__(self, corridor_id: str):
        self.corridor_id = corridor_id
        self.entity_map: Dict[str, str] = {}  # agent_id → SUMO vehicle ID
        self.transform = CoordinateTransform()

    def register_entity(self, agent_id: str, mode: str, lat: float, lon: float) -> str:
        """Register a new Flecs entity and return SUMO vehicle ID."""
        veh_id = f"{self.corridor_id}_{agent_id}"
        self.entity_map[agent_id] = veh_id
        return veh_id

    def unregister_entity(self, agent_id: str) -> Optional[str]:
        """Remove entity mapping. Returns SUMO vehicle ID if existed."""
        return self.entity_map.pop(agent_id, None)

    def get_vehicle_id(self, agent_id: str) -> Optional[str]:
        return self.entity_map.get(agent_id)

    def is_registered(self, agent_id: str) -> bool:
        return agent_id in self.entity_map

    def get_all_mappings(self) -> Dict[str, str]:
        return dict(self.entity_map)


# =============================================================================
# Mode Transition Handler
# =============================================================================

class ModeTransitionHandler:
    """
    Handles vehicle mode transitions in SUMO.
    When BDI decides to switch from diesel → BEV, this updates SUMO vehicle class.
    """

    MODE_TO_VCLASS = {
        "diesel": "truck",
        "bev": "evehicle",
        "h2": "truck",
        "rail": "rail",
        "ship": "ship"
    }

    MODE_TO_EMISSION = {
        "diesel": "HBEFA4/PC_D_EU6",
        "bev": "Energy/unknown",
        "h2": "HBEFA4/PC_D_EU6"
    }

    @classmethod
    def get_vclass(cls, mode: str) -> str:
        return cls.MODE_TO_VCLASS.get(mode, "truck")

    @classmethod
    def get_emission_class(cls, mode: str) -> str:
        return cls.MODE_TO_EMISSION.get(mode, "HBEFA4/PC_D_EU6")

    @classmethod
    def is_valid_transition(cls, from_mode: str, to_mode: str) -> bool:
        """Check if mode transition is physically possible."""
        # Cannot switch from ship to rail mid-route, etc.
        incompatible = {
            "ship": {"rail", "truck"},
            "rail": {"ship"}
        }
        return to_mode not in incompatible.get(from_mode, set())


# =============================================================================
# Corridor Grid Load Calculator
# =============================================================================

class GridLoadCalculator:
    """
    Calculates electricity grid load from BEV charging demand.
    MMOG analogy: "Resource node" — tracks how much power a zone consumes.
    """

    # Charging power per vehicle type (MW)
    CHARGING_POWER = {
        "bev_hgv": 0.35,      # 350kW ultra-fast
        "bev_van": 0.075,     # 75kW fast
        "bev_car": 0.05       # 50kW
    }

    @classmethod
    def calculate_load(cls, bev_count: int, vehicle_type: str = "bev_hgv") -> float:
        power_per_vehicle = cls.CHARGING_POWER.get(vehicle_type, 0.35)
        return bev_count * power_per_vehicle

    @classmethod
    def check_constraint(cls, current_load_mw: float, max_capacity_mw: float) -> Tuple[bool, float]:
        """Returns (is_violated, headroom_ratio)."""
        headroom = max_capacity_mw - current_load_mw
        ratio = headroom / max_capacity_mw if max_capacity_mw > 0 else 0.0
        return headroom < 0, ratio
