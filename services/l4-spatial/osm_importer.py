#!/usr/bin/env python3
"""
services/l4-spatial/osm_importer.py

Phase 14b: OSM → SUMO Network Generation

Generates SUMO road networks from OpenStreetMap data for UK corridors.
Uses osmnx for network extraction and netconvert for SUMO format conversion.

Usage:
    python osm_importer.py --corridor m20_corridor --bbox 51.1,1.3,51.2,1.4
"""
import os
import argparse
import subprocess
from pathlib import Path

try:
    import osmnx as ox
    HAS_OSMNX = True
except ImportError:
    HAS_OSMNX = False
    print("[OSMImporter] osmnx not available — install with: pip install osmnx")


def generate_sumo_network(corridor_id: str, north: float, south: float, 
                          east: float, west: float, output_dir: str = "deploy/osm-networks"):
    """Generate SUMO network files from OSM bounding box."""

    out_path = Path(output_dir) / corridor_id
    out_path.mkdir(parents=True, exist_ok=True)

    if not HAS_OSMNX:
        print(f"[OSMImporter] Skipping OSM download — osmnx not installed")
        return

    print(f"[OSMImporter] Downloading OSM for {corridor_id}...")

    # Download drivable network
    G = ox.graph_from_bbox(north, south, east, west, network_type="drive")

    # Save as OSM XML
    osm_file = out_path / f"{corridor_id}.osm.xml"
    ox.save_graph_xml(G, filepath=str(osm_file))

    print(f"[OSMImporter] OSM saved to {osm_file}")

    # Convert to SUMO network using netconvert
    net_file = out_path / f"{corridor_id}.net.xml"

    cmd = [
        "netconvert",
        "--osm-files", str(osm_file),
        "--output-file", str(net_file),
        "--geometry.remove",
        "--roundabouts.guess",
        "--ramps.guess",
        "--junctions.join",
        "--tls.guess-signals",
        "--tls.discard-simple",
        "--no-turnarounds",
        "--typemap", "/usr/share/sumo/data/typemap/osmNetconvert.typ.xml"
    ]

    print(f"[OSMImporter] Running netconvert...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"[OSMImporter] SUMO network created: {net_file}")
    else:
        print(f"[OSMImporter] netconvert failed: {result.stderr}")

    # Generate basic routes (placeholder — real routes from demand data)
    rou_file = out_path / f"{corridor_id}.rou.xml"
    with open(rou_file, "w") as f:
        f.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
        f.write("<routes>\n")
        f.write("    <vType id=\"truck\" vClass=\"truck\" maxSpeed=\"25\"/>\n")
        f.write("    <vType id=\"evehicle\" vClass=\"passenger\" maxSpeed=\"25\" emissionClass=\"Energy/unknown\"/>\n")
        f.write("</routes>\n")

    # Generate sumocfg
    cfg_file = out_path / f"{corridor_id}.sumocfg"
    with open(cfg_file, "w") as f:
        f.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
        f.write("<configuration>\n")
        f.write("    <input>\n")
        f.write(f"        <net-file value=\"{corridor_id}.net.xml\"/>\n")
        f.write(f"        <route-files value=\"{corridor_id}.rou.xml\"/>\n")
        f.write("    </input>\n")
        f.write("    <time>\n")
        f.write("        <step-length value=\"0.1\"/>\n")
        f.write("    </time>\n")
        f.write("</configuration>\n")

    print(f"[OSMImporter] Config written: {cfg_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate SUMO networks from OSM")
    parser.add_argument("--corridor", required=True, help="Corridor ID")
    parser.add_argument("--bbox", required=True, help="Bounding box: north,south,east,west")
    parser.add_argument("--output", default="deploy/osm-networks", help="Output directory")

    args = parser.parse_args()
    north, south, east, west = map(float, args.bbox.split(","))
    generate_sumo_network(args.corridor, north, south, east, west, args.output)
