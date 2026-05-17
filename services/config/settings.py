"""
services/config/settings.py

Typed configuration loader for CTT.
Reads from .env file in project root.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root (CTT/.env)
PROJECT_ROOT = Path(__file__).parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

class CTTConfig:
    """Typed configuration with validation."""

    # ZMQ Ports
    ZMQ_HARVESTER_PUB = os.getenv("ZMQ_HARVESTER_PUB", "tcp://*:5560")
    ZMQ_INTERPRETER_PUB = os.getenv("ZMQ_INTERPRETER_PUB", "tcp://*:5561")
    ZMQ_FUSION_PUB = os.getenv("ZMQ_FUSION_PUB", "tcp://*:5556")
    ZMQ_TELEMETRY_SUB = os.getenv("ZMQ_TELEMETRY_SUB", "tcp://localhost:5555")

    # Harvester Mode
    HARVESTER_MODE = os.getenv("HARVESTER_MODE", "mock")
    HARVESTER_POLL_INTERVAL = int(os.getenv("HARVESTER_POLL_INTERVAL", "30"))

    # Transitland
    TRANSITLAND_API_KEY = os.getenv("TRANSITLAND_API_KEY", "")
    TRANSITLAND_BASE_URL = os.getenv("TRANSITLAND_BASE_URL", "https://transit.land/api/v2")
    GTFS_BBOX = os.getenv("GTFS_BBOX", "51.2,-0.6,51.8,0.4")

    # BODS (Bus Open Data Service)
    BODS_API_KEY = os.getenv("BODS_API_KEY", "")
    BODS_BASE_URL = os.getenv("BODS_BASE_URL", "https://data.bus-data.dft.gov.uk/api/v1")

    # BAT (Buses & Trains API)
    BAT_API_KEY = os.getenv("BAT_API_KEY", "")
    BAT_BASE_URL = os.getenv("BAT_BASE_URL", "https://api.busesandtrains.co.uk")
    BAT_BUS_STOPS = os.getenv("BAT_BUS_STOPS", "")       # Comma-separated ATCO codes
    BAT_RAIL_STATIONS = os.getenv("BAT_RAIL_STATIONS", "") # Comma-separated CRS codes

    # TfL
    TFL_BASE_URL = os.getenv("TFL_BASE_URL", "https://api.tfl.gov.uk")

    # Direct GTFS-RT
    GTFS_RT_FEED_URL = os.getenv("GTFS_RT_FEED_URL", "")

    # Other API Keys
    OSM_EXTRACTS_KEY = os.getenv("OSM_EXTRACTS_KEY", "")
    MAPTILER_API_KEY = os.getenv("MAPTILER_API_KEY", "")
    OPENAIP_API_KEY = os.getenv("OPENAIP_API_KEY", "")

    def validate(self) -> list[str]:
        """Return list of configuration errors."""
        errors = []

        if self.HARVESTER_MODE == "transitland" and not self.TRANSITLAND_API_KEY:
            errors.append("TRANSITLAND_API_KEY is required for transitland mode")

        if self.HARVESTER_MODE == "bods" and not self.BODS_API_KEY:
            errors.append("BODS_API_KEY is required for bods mode")

        if self.HARVESTER_MODE == "bat" and not self.BAT_API_KEY:
            errors.append("BAT_API_KEY is required for bat mode")

        if self.HARVESTER_MODE == "gtfs" and not self.GTFS_RT_FEED_URL:
            errors.append("GTFS_RT_FEED_URL is required for gtfs mode")

        return errors

# Singleton instance
config = CTTConfig()