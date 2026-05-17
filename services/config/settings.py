"""
services/config/settings.py

Central configuration loader for CTT.
Reads .env from project root and provides typed access to all settings.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Find project root (where .env lives)
PROJECT_ROOT = Path(__file__).parent.parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()

class Config:
    """Immutable configuration container."""

    # --- API Keys ---
    TRANSITLAND_API_KEY = os.getenv("TRANSITLAND_API_KEY", "")
    BODS_API_KEY = os.getenv("BODS_API_KEY", "")
    OSM_EXTRACTS_KEY = os.getenv("OSM_EXTRACTS_KEY", "")
    MAPTILER_API_KEY = os.getenv("MAPTILER_API_KEY", "")
    OPENAIP_API_KEY = os.getenv("OPENAIP_API_KEY", "")

    # --- Base URLs ---
    TRANSITLAND_BASE_URL = os.getenv("TRANSITLAND_BASE_URL", "https://transit.land/api/v2")
    BODS_BASE_URL = os.getenv("BODS_BASE_URL", "https://data.bus-data.dft.gov.uk/api/v1")
    TFL_BASE_URL = os.getenv("TFL_BASE_URL", "https://api.tfl.gov.uk")
    OSM_EXTRACTS_BASE_URL = os.getenv("OSM_EXTRACTS_BASE_URL", "https://app.osmextracts.com/api/v1")
    MAPTILER_BASE_URL = os.getenv("MAPTILER_BASE_URL", "https://api.maptiler.com")
    OPENAIP_BASE_URL = os.getenv("OPENAIP_BASE_URL", "https://api.core.openaip.net/api")

    # --- Harvester Settings ---
    HARVESTER_MODE = os.getenv("HARVESTER_MODE", "mock")
    HARVESTER_POLL_INTERVAL = int(os.getenv("HARVESTER_POLL_INTERVAL", "30"))
    GTFS_RT_FEED_URL = os.getenv("GTFS_RT_FEED_URL", "")
    GTFS_OPERATOR_FILTER = os.getenv("GTFS_OPERATOR_FILTER", "")
    GTFS_BBOX = os.getenv("GTFS_BBOX", "")

    # --- ZMQ Overrides ---
    ZMQ_HARVESTER_PUB = os.getenv("ZMQ_HARVESTER_PUB", "")

    @classmethod
    def validate(cls) -> list[str]:
        """Return list of missing required keys for the current mode."""
        errors = []

        if cls.HARVESTER_MODE == "transitland" and not cls.TRANSITLAND_API_KEY:
            errors.append("TRANSITLAND_API_KEY is required for transitland mode")

        if cls.HARVESTER_MODE == "gtfs" and not cls.GTFS_RT_FEED_URL:
            errors.append("GTFS_RT_FEED_URL is required for gtfs mode")

        if cls.HARVESTER_MODE == "bods" and not cls.BODS_API_KEY:
            errors.append("BODS_API_KEY is required for bods mode. Register at https://data.bus-data.dft.gov.uk")

        return errors

    @classmethod
    def is_valid(cls) -> bool:
        return len(cls.validate()) == 0

config = Config()