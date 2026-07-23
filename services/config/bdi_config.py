#!/usr/bin/env python3
"""
services/config/bdi_config.py

Phase 13b: Externalized BDI Configuration

All BDI thresholds, TCO parameters, and policy profiles are defined here.
No hardcoded values in bdi_engine.py — everything reads from this config.

Usage:
    from bdi_config import get_policy_profile, TCO_PROFILES
    profile = get_policy_profile(os.environ.get("CTT_BDI_POLICY_MODE", "balanced"))
"""
import os
from dataclasses import dataclass
from typing import Dict, Any

# =============================================================================
# TCO Reference Profiles (Fleet RFP derived)
# =============================================================================

@dataclass
class TCOProfile:
    """Configurable TCO parameters per fleet/asset type."""
    capex_ice: float
    capex_ev: float
    opex_ice_annual: float
    opex_ev_annual: float
    carbon_tax_gbp_tonne: float
    diesel_price_ppl: float
    electricity_price_ppkwh: float
    years_in_service: float
    tco_horizon_years: int
    description: str

# Pre-defined TCO scenarios (editable via env or API)
TCO_PROFILES: Dict[str, TCOProfile] = {
    "base": TCOProfile(
        capex_ice=50000.0,
        capex_ev=80000.0,
        opex_ice_annual=15000.0,
        opex_ev_annual=8000.0,
        carbon_tax_gbp_tonne=0.0,
        diesel_price_ppl=150.0,
        electricity_price_ppkwh=30.0,
        years_in_service=0.0,
        tco_horizon_years=5,
        description="Fleet RFP base case: ICE £50k+£15k/yr vs EV £80k+£8k/yr"
    ),
    "high_diesel": TCOProfile(
        capex_ice=50000.0,
        capex_ev=80000.0,
        opex_ice_annual=19500.0,  # +30% diesel
        opex_ev_annual=8000.0,
        carbon_tax_gbp_tonne=0.0,
        diesel_price_ppl=195.0,
        electricity_price_ppkwh=30.0,
        years_in_service=0.0,
        tco_horizon_years=5,
        description="High diesel price scenario (+30%)"
    ),
    "ev_subsidy": TCOProfile(
        capex_ice=50000.0,
        capex_ev=65000.0,  # £15k subsidy
        opex_ice_annual=15000.0,
        opex_ev_annual=8000.0,
        carbon_tax_gbp_tonne=0.0,
        diesel_price_ppl=150.0,
        electricity_price_ppkwh=30.0,
        years_in_service=0.0,
        tco_horizon_years=5,
        description="EV purchase subsidy £15k"
    ),
    "carbon_tax_100": TCOProfile(
        capex_ice=50000.0,
        capex_ev=80000.0,
        opex_ice_annual=18000.0,  # +£3k/yr carbon cost
        opex_ev_annual=8000.0,
        carbon_tax_gbp_tonne=100.0,
        diesel_price_ppl=150.0,
        electricity_price_ppkwh=30.0,
        years_in_service=0.0,
        tco_horizon_years=5,
        description="Carbon tax £100/tonne (RFP trigger threshold)"
    ),
    "combined_policy": TCOProfile(
        capex_ice=50000.0,
        capex_ev=65000.0,
        opex_ice_annual=18000.0,
        opex_ev_annual=8000.0,
        carbon_tax_gbp_tonne=100.0,
        diesel_price_ppl=150.0,
        electricity_price_ppkwh=30.0,
        years_in_service=0.0,
        tco_horizon_years=5,
        description="Subsidy + carbon tax combined (aggressive decarbonisation)"
    ),
}

# Allow override via env var: CTT_TCO_PROFILE=base|high_diesel|ev_subsidy|...
def get_tco_profile(name: str = None) -> TCOProfile:
    """Get TCO profile by name. Falls back to env var or 'base'."""
    if name is None:
        name = os.environ.get("CTT_TCO_PROFILE", "base")
    return TCO_PROFILES.get(name, TCO_PROFILES["base"])


# =============================================================================
# BDI Policy Profiles (Schmitt Thresholds)
# =============================================================================

@dataclass
class BDIProfile:
    """Configurable BDI thresholds per policy intensity."""
    schmitt_threshold_on: float
    schmitt_threshold_off: float
    schmitt_hysteresis: float
    habit_decay_lambda: float
    infrastructure_min: float
    social_influence_min: float
    intention_ttl_ms: int
    coalition_cooldown_ms: int
    description: str

BDI_PROFILES: Dict[str, BDIProfile] = {
    "conservative": BDIProfile(
        schmitt_threshold_on=5000.0,
        schmitt_threshold_off=-2000.0,
        schmitt_hysteresis=1000.0,
        habit_decay_lambda=0.15,
        infrastructure_min=0.5,
        social_influence_min=0.3,
        intention_ttl_ms=300_000,
        coalition_cooldown_ms=600_000,
        description="Wait for clear EV advantage (Year 5 breakeven)"
    ),
    "balanced": BDIProfile(
        schmitt_threshold_on=0.0,
        schmitt_threshold_off=-5000.0,
        schmitt_hysteresis=2000.0,
        habit_decay_lambda=0.12,
        infrastructure_min=0.3,
        social_influence_min=0.2,
        intention_ttl_ms=300_000,
        coalition_cooldown_ms=600_000,
        description="Switch at breakeven (Year 3 with moderate policy)"
    ),
    "aggressive": BDIProfile(
        schmitt_threshold_on=-5000.0,
        schmitt_threshold_off=-10000.0,
        schmitt_hysteresis=3000.0,
        habit_decay_lambda=0.08,
        infrastructure_min=0.2,
        social_influence_min=0.1,
        intention_ttl_ms=300_000,
        coalition_cooldown_ms=600_000,
        description="Switch with policy support (Year 2-3 strong policy)"
    ),
}

def get_bdi_profile(name: str = None) -> BDIProfile:
    """Get BDI profile by name. Falls back to env var or 'balanced'."""
    if name is None:
        name = os.environ.get("CTT_BDI_POLICY_MODE", "balanced")
    return BDI_PROFILES.get(name, BDI_PROFILES["balanced"])


# =============================================================================
# Individual Env Var Overrides (highest priority)
# =============================================================================

def get_effective_thresholds() -> Dict[str, Any]:
    """
    Build effective thresholds from profile + env overrides.
    Env vars take highest priority, then profile, then defaults.
    """
    profile = get_bdi_profile()
    tco = get_tco_profile()

    return {
        # BDI thresholds
        "SCHMITT_THRESHOLD_ON": float(os.environ.get("CTT_SCHMITT_ON", profile.schmitt_threshold_on)),
        "SCHMITT_THRESHOLD_OFF": float(os.environ.get("CTT_SCHMITT_OFF", profile.schmitt_threshold_off)),
        "SCHMITT_HYSTERESIS": float(os.environ.get("CTT_SCHMITT_HYST", profile.schmitt_hysteresis)),
        "HABIT_DECAY_LAMBDA": float(os.environ.get("CTT_HABIT_LAMBDA", profile.habit_decay_lambda)),
        "INFRASTRUCTURE_MIN": float(os.environ.get("CTT_INFRA_MIN", profile.infrastructure_min)),
        "SOCIAL_INFLUENCE_MIN": float(os.environ.get("CTT_SOCIAL_MIN", profile.social_influence_min)),
        "INTENTION_TTL_MS": int(os.environ.get("CTT_INTENTION_TTL", profile.intention_ttl_ms)),
        "COALITION_COOLDOWN_MS": int(os.environ.get("CTT_COALITION_COOLDOWN", profile.coalition_cooldown_ms)),

        # TCO parameters
        "TCO_CAPEX_ICE": float(os.environ.get("CTT_TCO_CAPEX_ICE", tco.capex_ice)),
        "TCO_CAPEX_EV": float(os.environ.get("CTT_TCO_CAPEX_EV", tco.capex_ev)),
        "TCO_OPEX_ICE": float(os.environ.get("CTT_TCO_OPEX_ICE", tco.opex_ice_annual)),
        "TCO_OPEX_EV": float(os.environ.get("CTT_TCO_OPEX_EV", tco.opex_ev_annual)),
        "TCO_CARBON_TAX": float(os.environ.get("CTT_TCO_CARBON_TAX", tco.carbon_tax_gbp_tonne)),
        "TCO_DIESEL_PPL": float(os.environ.get("CTT_TCO_DIESEL_PPL", tco.diesel_price_ppl)),
        "TCO_ELECTRICITY_PPKWH": float(os.environ.get("CTT_TCO_ELEC_PPKWH", tco.electricity_price_ppkwh)),
        "TCO_HORIZON_YEARS": int(os.environ.get("CTT_TCO_HORIZON", tco.tco_horizon_years)),

        # Metadata
        "POLICY_MODE": os.environ.get("CTT_BDI_POLICY_MODE", "balanced"),
        "TCO_PROFILE": os.environ.get("CTT_TCO_PROFILE", "base"),
    }


# =============================================================================
# Corridor Configuration
# =============================================================================

@dataclass
class CorridorConfig:
    corridor_id: str
    north: float
    south: float
    east: float
    west: float
    description: str

CORRIDORS: Dict[str, CorridorConfig] = {
    "m20_corridor": CorridorConfig(
        corridor_id="m20_corridor",
        north=51.45, south=51.05, east=1.45, west=0.05,
        description="Dover Eastern Docks → Folkestone → Ashford → Maidstone → M25"
    ),
    "a20_charging": CorridorConfig(
        corridor_id="a20_charging",
        north=51.20, south=51.05, east=1.45, west=1.15,
        description="Dover → Folkestone charging corridor"
    ),
    "m25_ring": CorridorConfig(
        corridor_id="m25_ring",
        north=51.75, south=51.25, east=0.55, west=-0.55,
        description="London orbital M25"
    ),
}

def get_corridor_config(corridor_id: str = None) -> CorridorConfig:
    if corridor_id is None:
        corridor_id = os.environ.get("CTT_CORRIDOR_ID", "m20_corridor")
    return CORRIDORS.get(corridor_id, CORRIDORS["m20_corridor"])


def list_corridors() -> Dict[str, str]:
    """Return corridor IDs and descriptions for UI/API."""
    return {k: v.description for k, v in CORRIDORS.items()}


def list_tco_profiles() -> Dict[str, str]:
    """Return TCO profile names and descriptions for UI/API."""
    return {k: v.description for k, v in TCO_PROFILES.items()}


def list_bdi_profiles() -> Dict[str, str]:
    """Return BDI policy mode names and descriptions for UI/API."""
    return {k: v.description for k, v in BDI_PROFILES.items()}
