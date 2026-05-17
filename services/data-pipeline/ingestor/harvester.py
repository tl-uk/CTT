"""
services/data-pipeline/ingestor/harvester.py

CTT Data Ingestor — Mode-switchable harvester.

Modes:
  mock        → Simulated SME data (development / CI)
  gtfs        → Direct GTFS-RT protobuf feed
  transitland → Transitland REST API discovery + fetch

Usage:
  python harvester.py --mode mock
  python harvester.py --mode gtfs
  python harvester.py --mode transitland

Environment:
  Set HARVESTER_MODE in .env, or override with --mode CLI flag.
"""
import argparse
import sys
import os

# Add config to path
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
        print("  gtfs        — Direct GTFS-RT protobuf feed")
        print("  transitland — Transitland REST API feed discovery")
        sys.exit(0)

    print(f"🌾 CTT Harvester Launcher | Mode: {args.mode.upper()}")

    if args.mode == "mock":
        # Import and run the mock generator
        from harvester_mock import run_harvester as run_mock
        run_mock()

    elif args.mode in ("gtfs", "transitland"):
        # Import and run the GTFS harvester
        from gtfs_harvester import run_gtfs_harvester
        run_gtfs_harvester(mode=args.mode)

    else:
        print(f"❌ Unknown mode: {args.mode}")
        sys.exit(1)

if __name__ == "__main__":
    main()