"""
services/data-pipeline/ingestor/harvester.py

CTT Data Ingestor — Mode-switchable harvester launcher.

Modes:
  mock        → Simulated SME data (development / CI)
  transitland → GTFS static feed discovery & download (offline simulation)
  gtfs        → Generic direct GTFS-RT protobuf feed
  bods        → UK Bus Open Data Service (real-time bus, requires API key)
  tfl         → Transport for London JSON API (no key, London only)

Usage:
  python harvester.py --mode mock
  python harvester.py --mode bods
  python harvester.py --mode tfl
  python harvester.py --mode transitland
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "config"))
from settings import config

def main():
    parser = argparse.ArgumentParser(description="CTT Data Harvester")
    parser.add_argument(
        "--mode",
        choices=["mock", "gtfs", "transitland", "bods", "tfl"],
        default=config.HARVESTER_MODE,
        help="Harvesting backend to use"
    )
    parser.add_argument(
        "--list-modes",
        action="store_true",
        help="Show available modes and exit"
    )
    args = parser.parse_args()

    if args.list_modes:
        print("Available harvester modes:")
        print("  mock        — Simulated fleet data (no external APIs)")
        print("  transitland — GTFS static feed discovery & download (offline simulation)")
        print("  gtfs        — Direct GTFS-RT protobuf feed (generic)")
        print("  bods        — UK Bus Open Data Service (real-time, requires BODS_API_KEY)")
        print("  tfl         — Transport for London JSON API (no key, London only)")
        sys.exit(0)

    print(f"🌾 CTT Harvester Launcher | Mode: {args.mode.upper()}")

    if args.mode == "mock":
        from harvester_mock import run_harvester as run_mock
        run_mock()
    elif args.mode in ("gtfs", "transitland", "bods", "tfl"):
        from gtfs_harvester import run_gtfs_harvester
        run_gtfs_harvester(mode=args.mode)
    else:
        print(f"❌ Unknown mode: {args.mode}")
        sys.exit(1)

if __name__ == "__main__":
    main()
