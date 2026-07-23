#!/usr/bin/env python3
"""
scripts/generate_m20_network.py

Phase 14b: Generate SUMO network for M20 corridor (Dover → London)

Bounding box: 51.05°N–51.45°N, 0.05°E–1.45°E
Covers: Dover (Eastern Docks) → Folkestone → Ashford → Maidstone → M25

Usage:
    python scripts/generate_m20_network.py

Requires: osmnx, netconvert (from SUMO)
"""
import sys
import os

# Add services to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "l4-spatial"))

from osm_importer import generate_sumo_network

if __name__ == "__main__":
    print("=" * 60)
    print("CTT Phase 14b: M20 Corridor OSM → SUMO Network")
    print("=" * 60)

    # M20 corridor bounding box
    # North: 51.45° (near M25/M20 junction)
    # South: 51.05° (Dover Eastern Docks)
    # East: 1.45° (Dover coast)
    # West: 0.05° (near Sevenoaks)
    NORTH = 51.45
    SOUTH = 51.05
    EAST = 1.45
    WEST = 0.05

    print(f"\nCorridor: m20_corridor")
    print(f"Bounding box: {NORTH}°N–{SOUTH}°N, {EAST}°E–{WEST}°E")
    print(f"Coverage: Dover → Folkestone → Ashford → Maidstone → M25")
    print(f"Output: deploy/osm-networks/m20_corridor/")
    print()

    generate_sumo_network(
        corridor_id="m20_corridor",
        north=NORTH,
        south=SOUTH,
        east=EAST,
        west=WEST,
        output_dir="deploy/osm-networks"
    )

    print("\n" + "=" * 60)
    print("Next steps:")
    print("  1. Verify network: sumo-gui -c deploy/osm-networks/m20_corridor/m20_corridor.sumocfg")
    print("  2. Test with SUMO bridge: make compose-up-sumo")
    print("  3. Add demand routes from traffic data")
    print("=" * 60)
