"""
services/data-pipeline/ingestor/gtfs_harvester.py

Production-grade GTFS-Realtime harvester for CTT.
Supports two backends:
  1. Direct GTFS-RT Protobuf feeds (mode=gtfs)
  2. Transitland REST API (mode=transitland)

All backends normalize to the CTT internal schema:
  {"truck_id": "...", "fuel_type": "Diesel", "efficiency_score": 0.x,
   "route": "...", "delay_minutes": N, "source": "...", "timestamp": ...}
"""
import json
import time
import os
import sys
import requests
import random
from pathlib import Path
from typing import Optional, Iterator
from datetime import datetime, timezone

# Add project config to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "config"))
from ports import ZMQ_PORTS
from settings import config

# ---------------------------------------------------------------------------
# Retry Decorator
# ---------------------------------------------------------------------------
class RetryExhaustedError(Exception):
    pass

def with_retries(max_attempts: int = 3, backoff_base: float = 1.5):
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except (requests.RequestException, ConnectionError) as e:
                    last_exc = e
                    sleep_time = backoff_base ** attempt
                    print(f"   ⚠️  {func.__name__} attempt {attempt}/{max_attempts} failed: {e}")
                    print(f"      Retrying in {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
            raise RetryExhaustedError(f"{func.__name__} failed after {max_attempts} attempts") from last_exc
        return wrapper
    return decorator

# ---------------------------------------------------------------------------
# Transitland API Client
# ---------------------------------------------------------------------------
class TransitlandClient:
    def __init__(self, api_key: str, base_url: str = "https://transit.land/api/v2"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"apikey": api_key})

    @with_retries(max_attempts=3, backoff_base=1.5)
    def get_feeds(self, bbox: Optional[str] = None, operator: Optional[str] = None) -> list[dict]:
        """Discover GTFS feeds in a geographic area."""
        url = f"{self.base_url}/rest/feeds"
        params = {"limit": 20}
        if bbox:
            params["bbox"] = bbox
        if operator:
            params["operator_onestop_id"] = operator

        resp = self.session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("feeds", [])

    @with_retries(max_attempts=3, backoff_base=1.5)
    def get_stop_times(self, feed_id: str, route_id: Optional[str] = None) -> list[dict]:
        """Fetch stop times with delay information."""
        url = f"{self.base_url}/rest/stop_times"
        params = {
            "feed_onestop_id": feed_id,
            "limit": 50,
            "include": "trip,stop"
        }
        if route_id:
            params["route_id"] = route_id

        resp = self.session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("stop_times", [])

    @with_retries(max_attempts=3, backoff_base=1.5)
    def get_routes(self, feed_id: str) -> list[dict]:
        """Fetch routes for a feed."""
        url = f"{self.base_url}/rest/routes"
        params = {"feed_onestop_id": feed_id, "limit": 50}

        resp = self.session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("routes", [])

# ---------------------------------------------------------------------------
# Direct GTFS-RT Protobuf Parser
# ---------------------------------------------------------------------------
class GtfsRtClient:
    def __init__(self, feed_url: str):
        self.feed_url = feed_url
        self.session = requests.Session()

    @with_retries(max_attempts=3, backoff_base=2.0)
    def fetch_trip_updates(self) -> list[dict]:
        """
        Fetch GTFS-RT TripUpdates feed and parse delays.
        Returns list of delay dicts in CTT schema.
        """
        resp = self.session.get(self.feed_url, timeout=20)
        resp.raise_for_status()

        # Try to parse as GTFS-RT protobuf
        try:
            from google.transit import gtfs_realtime_pb2
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(resp.content)

            delays = []
            for entity in feed.entity:
                if not entity.HasField("trip_update"):
                    continue

                tu = entity.trip_update
                route_id = tu.trip.route_id

                for stop_time in tu.stop_time_update:
                    delay_sec = stop_time.departure.delay if stop_time.HasField("departure") else 0
                    if delay_sec <= 0:
                        continue

                    delays.append({
                        "route_id": route_id,
                        "stop_sequence": stop_time.stop_sequence,
                        "delay_seconds": delay_sec,
                        "delay_minutes": round(delay_sec / 60, 1),
                        "source": "gtfs_rt_direct"
                    })
            return delays

        except ImportError:
            print("   ⚠️  google.transit not installed. Install: pip install gtfs-realtime-bindings")
            # Fallback: try JSON (some feeds offer JSON variant)
            try:
                data = resp.json()
                return self._parse_json_feed(data)
            except (json.JSONDecodeError, ValueError):
                print("   ⚠️  Feed is neither protobuf nor JSON. Check URL.")
                return []
        except Exception as e:
            print(f"   ⚠️  Protobuf parse error: {e}")
            return []

    def _parse_json_feed(self, data: dict) -> list[dict]:
        """Parse JSON-format GTFS-RT (e.g., TfL API)."""
        delays = []

        # Handle TfL-style line status
        if isinstance(data, list):
            for item in data:
                line = item.get("id", "unknown")
                for status in item.get("lineStatuses", []):
                    reason = status.get("statusSeverityDescription", "")
                    if "Delay" in reason or "Suspended" in reason:
                        # Map severity to synthetic delay minutes
                        severity = status.get("statusSeverity", 10)
                        delay_min = max(5, (10 - severity) * 8)
                        delays.append({
                            "route_id": line,
                            "delay_minutes": delay_min,
                            "reason": reason,
                            "source": "tfl_json"
                        })

        # Handle GTFS-RT JSON
        elif isinstance(data, dict) and "entity" in data:
            for entity in data["entity"]:
                tu = entity.get("tripUpdate", {})
                route_id = tu.get("trip", {}).get("routeId", "unknown")
                for stu in tu.get("stopTimeUpdate", []):
                    delay_sec = stu.get("departure", {}).get("delay", 0)
                    if delay_sec > 0:
                        delays.append({
                            "route_id": route_id,
                            "delay_minutes": round(delay_sec / 60, 1),
                            "source": "gtfs_rt_json"
                        })

        return delays

# ---------------------------------------------------------------------------
# CTT Schema Normalizer
# ---------------------------------------------------------------------------
def normalize_to_ctt(raw_delay: dict, fleet_pool: list[dict]) -> dict:
    """
    Convert a raw delay record into the CTT internal schema.

    Maps:
      - route_id → route name
      - delay_minutes → efficiency_score (inverse relationship)
      - Randomly assigns a truck from fleet_pool to this delay event
    """
    delay_min = raw_delay.get("delay_minutes", 0)
    route = raw_delay.get("route_id", raw_delay.get("route", "unknown"))

    # Efficiency decay model: each minute of delay reduces efficiency
    # Base 0.85, minus 0.02 per minute of delay, floor at 0.15
    efficiency = max(0.15, 0.85 - (delay_min * 0.02))

    # Assign to a random fleet vehicle (simulates which truck was affected)
    agent = random.choice(fleet_pool) if fleet_pool else {
        "truck_id": "CTT_HGV_001",
        "fuel_type": "Diesel",
        "base_efficiency": 0.72
    }

    return {
        "truck_id": agent["truck_id"],
        "fuel_type": agent["fuel_type"],
        "efficiency_score": round(efficiency, 2),
        "route": route,
        "delay_minutes": delay_min,
        "source": raw_delay.get("source", "gtfs"),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# ---------------------------------------------------------------------------
# Main Harvester Loop
# ---------------------------------------------------------------------------
def run_gtfs_harvester(mode: str = "transitland"):
    import zmq

    # Validate config
    errors = config.validate()
    if errors:
        print("❌ Configuration errors:")
        for e in errors:
            print(f"   • {e}")
        sys.exit(1)

    # Setup ZMQ
    context = zmq.Context()
    pub = context.socket(zmq.PUB)
    bind_addr = config.ZMQ_HARVESTER_PUB or ZMQ_PORTS["HARVESTER_PUB"]
    pub.bind(bind_addr)

    # Fleet registry (simulated — in production this comes from CTT agent DB)
    fleet_pool = [
        {"truck_id": "SME_Volvo_01", "fuel_type": "Diesel", "base_efficiency": 0.72},
        {"truck_id": "Haulier_T-100", "fuel_type": "Diesel", "base_efficiency": 0.65},
        {"truck_id": "GreenFleet_BEV_09", "fuel_type": "Electric", "base_efficiency": 0.91},
        {"truck_id": "CTT_HGV_001", "fuel_type": "Diesel", "base_efficiency": 0.68},
    ]

    print(f"📡 GTFS Harvester Online | Mode: {mode.upper()}")
    print(f"   Binding: {bind_addr}")
    print(f"   Poll interval: {config.HARVESTER_POLL_INTERVAL}s")

    # Initialize backend client
    if mode == "transitland":
        client = TransitlandClient(
            api_key=config.TRANSITLAND_API_KEY,
            base_url=config.TRANSITLAND_BASE_URL
        )
        print(f"   Backend: Transitland ({config.TRANSITLAND_BASE_URL})")

        # Discover feeds once
        try:
            feeds = client.get_feeds(bbox=config.GTFS_BBOX, operator=config.GTFS_OPERATOR_FILTER)
            print(f"   Discovered {len(feeds)} feed(s)")
            for f in feeds[:3]:
                print(f"      • {f.get('onestop_id', 'unknown')}")
        except Exception as e:
            print(f"   ⚠️  Feed discovery failed: {e}")
            feeds = []

    elif mode == "gtfs":
        client = GtfsRtClient(feed_url=config.GTFS_RT_FEED_URL)
        print(f"   Backend: Direct GTFS-RT ({config.GTFS_RT_FEED_URL})")
        feeds = []

    else:
        print(f"❌ Unknown mode: {mode}")
        sys.exit(1)

    # Slow-joiner guard
    time.sleep(0.5)

    # Main loop
    cycle = 0
    try:
        while True:
            cycle += 1
            print(f"\n🔄 Poll cycle {cycle}")

            raw_delays = []

            try:
                if mode == "transitland":
                    # Query each discovered feed for stop times with delays
                    for feed in feeds[:3]:  # Limit to top 3 feeds to avoid rate limits
                        feed_id = feed.get("onestop_id")
                        if not feed_id:
                            continue

                        stop_times = client.get_stop_times(feed_id=feed_id)
                        for st in stop_times:
                            # Transitland stop_times may not have explicit delay field;
                            # we synthesize from arrival/departure variance if available
                            delay = 0
                            if "arrival" in st and st["arrival"]:
                                scheduled = st["arrival"].get("scheduled_time")
                                estimated = st["arrival"].get("estimated_time")
                                if scheduled and estimated:
                                    delay = max(0, estimated - scheduled) / 60

                            if delay > 2:  # Only report meaningful delays
                                raw_delays.append({
                                    "route_id": st.get("route_id", feed_id),
                                    "delay_minutes": round(delay, 1),
                                    "source": "transitland"
                                })

                elif mode == "gtfs":
                    raw_delays = client.fetch_trip_updates()

            except RetryExhaustedError as e:
                print(f"   ❌ Data fetch failed after retries: {e}")
            except Exception as e:
                print(f"   ❌ Unexpected error: {e}")

            # Normalize and publish
            if raw_delays:
                print(f"   📊 {len(raw_delays)} delay event(s) detected")
                for delay in raw_delays[:5]:  # Publish top 5 per cycle
                    ctt_payload = normalize_to_ctt(delay, fleet_pool)
                    pub.send_string(json.dumps(ctt_payload))
                    print(f"   → {ctt_payload['truck_id']:20s} | route={ctt_payload['route']:15s} | "
                          f"efficiency={ctt_payload['efficiency_score']:.2f} | delay={ctt_payload['delay_minutes']}m")
                    time.sleep(0.3)  # Pace messages to avoid ZMQ drop
            else:
                print("   ℹ️  No delays detected this cycle")

            time.sleep(config.HARVESTER_POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n🛑 GTFS Harvester stopped by user.")
    finally:
        pub.close()
        context.term()

if __name__ == "__main__":
    mode = config.HARVESTER_MODE
    if len(sys.argv) > 1:
        mode = sys.argv[1]
    run_gtfs_harvester(mode=mode)