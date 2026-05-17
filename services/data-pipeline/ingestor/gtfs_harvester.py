"""
services/data-pipeline/ingestor/gtfs_harvester.py

Multi-mode GTFS harvester for CTT.
"""
import json
import time
import os
import sys
import requests
import random
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

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
                    if attempt < max_attempts:
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
        url = f"{self.base_url}/rest/feeds"
        params = {"limit": 20}
        if bbox:
            params["bbox"] = bbox
        if operator:
            params["operator_onestop_id"] = operator
        resp = self.session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("feeds", [])

    @with_retries(max_attempts=3, backoff_base=2.0)
    def download_latest_feed(self, feed_onestop_id: str, output_path: Path) -> Path:
        url = f"{self.base_url}/rest/feeds/{feed_onestop_id}/download_latest_feed_version"
        resp = self.session.get(url, timeout=120, stream=True)
        if resp.status_code == 404:
            versions_url = f"{self.base_url}/rest/feed_versions"
            v_resp = self.session.get(versions_url, params={"feed_onestop_id": feed_onestop_id, "limit": 1}, timeout=15)
            v_resp.raise_for_status()
            versions = v_resp.json().get("feed_versions", [])
            if not versions:
                raise RetryExhaustedError(f"No versions for {feed_onestop_id}")
            dl_url = versions[0].get("url") or versions[0].get("download_url")
            if not dl_url:
                raise RetryExhaustedError(f"No download URL for {feed_onestop_id}")
            resp = self.session.get(dl_url, timeout=120, stream=True)
            resp.raise_for_status()
        else:
            resp.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(65536):
                f.write(chunk)
        return output_path

    def is_uk_feed(self, feed: dict) -> bool:
        feed_id = feed.get("onestop_id", "").lower()
        name = feed.get("name", "").lower()
        uk_patterns = ["dft", "tfl", "stagecoach", " arriva", "firstbus", "gov~uk", "nationalrail", "scotrail"]
        return any(p in feed_id or p in name for p in uk_patterns)

# ---------------------------------------------------------------------------
# BODS API Client
# ---------------------------------------------------------------------------
class BodsClient:
    def __init__(self, api_key: str, base_url: str = "https://data.bus-data.dft.gov.uk/api/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "x-api-key": api_key,
            "Accept": "application/octet-stream",
        })

    @with_retries(max_attempts=3, backoff_base=2.0)
    def fetch_trip_updates(self) -> list[dict]:
        url = f"{self.base_url}/gtfsrt/"
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return self._parse_protobuf(resp.content)

    @with_retries(max_attempts=3, backoff_base=2.0)
    def fetch_vehicle_positions(self) -> list[dict]:
        url = f"{self.base_url}/gtfsrt/vehiclepositions"
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return self._parse_vehicle_protobuf(resp.content)

    def _parse_protobuf(self, data: bytes) -> list[dict]:
        try:
            from google.transit import gtfs_realtime_pb2 as gtfsrt
            feed = gtfsrt.FeedMessage()
            feed.ParseFromString(data)
            delays = []
            for entity in feed.entity:
                if not entity.HasField("trip_update"):
                    continue
                tu = entity.trip_update
                route_id = tu.trip.route_id
                for stop_time in tu.stop_time_update:
                    delay_sec = 0
                    if stop_time.HasField("departure"):
                        delay_sec = stop_time.departure.delay
                    elif stop_time.HasField("arrival"):
                        delay_sec = stop_time.arrival.delay
                    if delay_sec <= 0:
                        continue
                    delays.append({
                        "route_id": route_id,
                        "delay_seconds": delay_sec,
                        "delay_minutes": round(delay_sec / 60, 1),
                        "stop_sequence": stop_time.stop_sequence,
                        "source": "bods_tripupdate"
                    })
            return delays
        except ImportError:
            print("   ⚠️  google.transit not installed. Run: pip install gtfs-realtime-bindings")
            return []
        except Exception as e:
            print(f"   ⚠️  Protobuf parse error: {e}")
            return []

    def _parse_vehicle_protobuf(self, data: bytes) -> list[dict]:
        try:
            from google.transit import gtfs_realtime_pb2 as gtfsrt
            feed = gtfsrt.FeedMessage()
            feed.ParseFromString(data)
            positions = []
            for entity in feed.entity:
                if not entity.HasField("vehicle"):
                    continue
                v = entity.vehicle
                positions.append({
                    "route_id": v.trip.route_id,
                    "vehicle_id": v.vehicle.id,
                    "lat": v.position.latitude,
                    "lon": v.position.longitude,
                    "timestamp": v.timestamp,
                    "source": "bods_vehicleposition"
                })
            return positions
        except ImportError:
            return []
        except Exception as e:
            print(f"   ⚠️  Vehicle protobuf parse error: {e}")
            return []

# ---------------------------------------------------------------------------
# BAT API Client — Buses & Trains (UK JSON API)
# ---------------------------------------------------------------------------
class BatClient:
    def __init__(self, api_key: str, base_url: str = "https://api.busesandtrains.co.uk"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        })

    @with_retries(max_attempts=2, backoff_base=1.5)
    def search_stops(self, lat: float, lon: float, radius: int = 2000, limit: int = 10) -> list[dict]:
        url = f"{self.base_url}/v1/stops"
        params = {"lat": lat, "lon": lon, "radius": radius, "limit": limit}
        resp = self.session.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json().get("stops", [])

    @with_retries(max_attempts=2, backoff_base=1.5)
    def fetch_bus_departures(self, atco_code: str) -> list[dict]:
        url = f"{self.base_url}/v1/stops/{atco_code}/departures"
        resp = self.session.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        delays = []
        for dep in data.get("departures", []):
            scheduled = dep.get("scheduled")
            expected = dep.get("expected")
            if not scheduled or not expected:
                continue
            try:
                from datetime import datetime as dt
                sched_dt = dt.fromisoformat(scheduled.replace("Z", "+00:00"))
                exp_dt = dt.fromisoformat(expected.replace("Z", "+00:00"))
                delay_sec = (exp_dt - sched_dt).total_seconds()
                if delay_sec <= 0:
                    continue
                delay_min = round(delay_sec / 60, 1)
                delays.append({
                    "route_id": dep.get("line", "unknown"),
                    "route_name": f"{dep.get('line', '?')} to {dep.get('destination', '?')}",
                    "delay_minutes": delay_min,
                    "operator": dep.get("operator", ""),
                    "stop_name": data.get("stop_name", ""),
                    "source": "bat_bus",
                })
            except Exception:
                continue
        return delays

    @with_retries(max_attempts=2, backoff_base=1.5)
    def fetch_rail_departures(self, crs: str) -> list[dict]:
        url = f"{self.base_url}/v1/rail/stations/{crs}/departures"
        resp = self.session.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        delays = []
        for dep in data.get("departures", []):
            scheduled = dep.get("scheduled")
            expected = dep.get("expected")
            if not scheduled or not expected:
                continue
            try:
                from datetime import datetime as dt
                sched_dt = dt.fromisoformat(scheduled.replace("Z", "+00:00"))
                exp_dt = dt.fromisoformat(expected.replace("Z", "+00:00"))
                delay_sec = (exp_dt - sched_dt).total_seconds()
                if delay_sec <= 60:
                    continue
                delay_min = round(delay_sec / 60, 1)
                is_cancelled = dep.get("is_cancelled", False)
                if is_cancelled:
                    delay_min = 60
                delays.append({
                    "route_id": dep.get("line", crs),
                    "route_name": f"{dep.get('origin', '?')} → {dep.get('destination', '?')}",
                    "delay_minutes": delay_min,
                    "operator": dep.get("operator", ""),
                    "station": data.get("stop_name", ""),
                    "platform": dep.get("platform", ""),
                    "is_cancelled": is_cancelled,
                    "source": "bat_rail",
                })
            except Exception:
                continue
        return delays

    def fetch_all_delays(self, bus_stops: list[str] = None, rail_stations: list[str] = None) -> list[dict]:
        delays = []
        bus_stops = bus_stops or []
        rail_stations = rail_stations or ["PAD", "EUS", "KGX", "MYB", "BHM", "MAN", "EDB", "GLQ"]
        for atco in bus_stops:
            try:
                delays.extend(self.fetch_bus_departures(atco))
            except Exception as e:
                print(f"   ⚠️  Bus stop {atco} failed: {e}")
        for crs in rail_stations:
            try:
                delays.extend(self.fetch_rail_departures(crs))
            except Exception as e:
                print(f"   ⚠️  Rail station {crs} failed: {e}")
        return delays

# ---------------------------------------------------------------------------
# TfL API Client
# ---------------------------------------------------------------------------
class TflClient:
    def __init__(self, base_url: str = "https://api.tfl.gov.uk"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    @with_retries(max_attempts=3, backoff_base=1.5)
    def fetch_line_status(self, modes: str = "bus,tube,dlr,overground,tram") -> list[dict]:
        url = f"{self.base_url}/line/mode/{modes}/status"
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        return self._parse_status_json(resp.json())

    def _parse_status_json(self, data: list) -> list[dict]:
        delays = []
        for item in data:
            line_id = item.get("id", "unknown")
            line_name = item.get("name", line_id)
            for status in item.get("lineStatuses", []):
                reason = status.get("statusSeverityDescription", "")
                severity = status.get("statusSeverity", 10)
                if severity >= 9:
                    continue
                delay_map = {8: 8, 7: 12, 6: 20, 5: 30, 4: 40, 3: 50, 2: 55, 1: 60, 0: 60}
                delay_min = delay_map.get(severity, 10)
                delays.append({
                    "route_id": line_id,
                    "route_name": line_name,
                    "delay_minutes": delay_min,
                    "reason": reason,
                    "severity": severity,
                    "source": "tfl_status"
                })
        return delays

# ---------------------------------------------------------------------------
# GTFS-RT Direct Client
# ---------------------------------------------------------------------------
class GtfsRtClient:
    def __init__(self, feed_url: str):
        self.feed_url = feed_url
        self.session = requests.Session()

    @with_retries(max_attempts=3, backoff_base=2.0)
    def fetch_trip_updates(self) -> list[dict]:
        resp = self.session.get(self.feed_url, timeout=20)
        resp.raise_for_status()
        try:
            from google.transit import gtfs_realtime_pb2 as gtfsrt
            feed = gtfsrt.FeedMessage()
            feed.ParseFromString(resp.content)
            delays = []
            for entity in feed.entity:
                if not entity.HasField("trip_update"):
                    continue
                tu = entity.trip_update
                route_id = tu.trip.route_id
                for stop_time in tu.stop_time_update:
                    delay_sec = 0
                    if stop_time.HasField("departure"):
                        delay_sec = stop_time.departure.delay
                    elif stop_time.HasField("arrival"):
                        delay_sec = stop_time.arrival.delay
                    if delay_sec > 0:
                        delays.append({
                            "route_id": route_id,
                            "delay_seconds": delay_sec,
                            "delay_minutes": round(delay_sec / 60, 1),
                            "source": "gtfs_rt_direct"
                        })
            return delays
        except ImportError:
            print("   ⚠️  google.transit not installed. Run: pip install gtfs-realtime-bindings")
            return []
        except Exception as e:
            print(f"   ⚠️  Protobuf parse error: {e}")
            return []

# ---------------------------------------------------------------------------
# GTFS Static Parser
# ---------------------------------------------------------------------------
class GtfsStaticParser:
    def __init__(self, feed_path: Path, service_date: Optional[str] = None, bbox: Optional[tuple] = None):
        self.feed_path = feed_path
        self.service_date = service_date
        self.bbox = bbox
        self._loader = None

    def load(self):
        if self._loader is not None:
            return self._loader
        try:
            from gtfs_loader import GTFSLoader
            self._loader = GTFSLoader(
                feed_path=self.feed_path,
                service_date=self.service_date,
                bbox=self.bbox,
            )
            self._loader.load()
            return self._loader
        except ImportError:
            print("   ⚠️  gtfs_loader.py not available — using basic CSV parsing")
            return None

    def extract_delays_from_headways(self) -> list[dict]:
        loader = self.load()
        if loader is None:
            return []
        headways = loader.compute_headways(time_window=(25200, 34200))
        delays = []
        for (route_id, stop_id), headway_sec in headways.items():
            route = loader.routes.get(route_id, {})
            if headway_sec >= 3600:
                delay_min = 15
            elif headway_sec >= 1800:
                delay_min = 8
            elif headway_sec >= 900:
                delay_min = 4
            else:
                continue
            delays.append({
                "route_id": route_id,
                "route_name": route.get("short_name", route_id),
                "mode": route.get("mode", "bus"),
                "fuel_type": route.get("fuel_type", "diesel"),
                "delay_minutes": delay_min,
                "headway_seconds": headway_sec,
                "source": "gtfs_static_headway",
            })
        return delays

    def get_summary(self) -> dict:
        loader = self.load()
        if loader:
            return loader.summary()
        return {}

# ---------------------------------------------------------------------------
# CTT Schema Normalizer
# ---------------------------------------------------------------------------
def normalize_to_ctt(raw_delay: dict, fleet_pool: list[dict]) -> dict:
    delay_min = raw_delay.get("delay_minutes", 0)
    route = raw_delay.get("route_id", raw_delay.get("route", "unknown"))
    route_name = raw_delay.get("route_name", route)
    mode = raw_delay.get("mode", "bus")
    fuel = raw_delay.get("fuel_type", "diesel")
    efficiency = max(0.15, 0.85 - (delay_min * 0.02))
    agent = random.choice(fleet_pool) if fleet_pool else {
        "truck_id": "CTT_HGV_001",
        "fuel_type": fuel,
        "base_efficiency": 0.72
    }
    return {
        "truck_id": agent["truck_id"],
        "fuel_type": agent["fuel_type"],
        "efficiency_score": round(efficiency, 2),
        "route": route_name,
        "delay_minutes": delay_min,
        "mode": mode,
        "source": raw_delay.get("source", "gtfs"),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# ---------------------------------------------------------------------------
# Main Harvester Loop
# ---------------------------------------------------------------------------
def run_gtfs_harvester(mode: str = "mock"):
    import zmq

    errors = config.validate()
    if errors:
        print("❌ Configuration errors:")
        for e in errors:
            print(f"   • {e}")
        sys.exit(1)

    context = zmq.Context()
    pub = context.socket(zmq.PUB)
    bind_addr = config.ZMQ_HARVESTER_PUB or ZMQ_PORTS["HARVESTER_PUB"]
    pub.bind(bind_addr)

    fleet_pool = [
        {"truck_id": "SME_Volvo_01", "fuel_type": "Diesel", "base_efficiency": 0.72},
        {"truck_id": "Haulier_T-100", "fuel_type": "Diesel", "base_efficiency": 0.65},
        {"truck_id": "Unregistered_HGV_X7", "fuel_type": "Diesel", "base_efficiency": 0.58},
        {"truck_id": "GreenFleet_BEV_09", "fuel_type": "Electric", "base_efficiency": 0.91},
    ]

    print(f"📡 GTFS Harvester Online | Mode: {mode.upper()}")
    print(f"   Binding: {bind_addr}")
    print(f"   Poll interval: {config.HARVESTER_POLL_INTERVAL}s")

    # Mode-specific client initialization — each branch creates a NARROWED local variable
    # Pylance can now infer the exact type within each branch
    parser: Optional[GtfsStaticParser] = None

    if mode == "transitland":
        # ------------------------------------------------------------------
        # Transitland mode: discover/download static feeds, parse headways
        # ------------------------------------------------------------------
        tl_client = TransitlandClient(api_key=config.TRANSITLAND_API_KEY, base_url=config.TRANSITLAND_BASE_URL)
        print(f"   Backend: Transitland ({config.TRANSITLAND_BASE_URL})")
        dl_dir = Path(__file__).parent.parent.parent.parent / "data" / "gtfs"
        dl_dir.mkdir(parents=True, exist_ok=True)
        cached_feeds = list(dl_dir.glob("f-bus~dft~gov~uk*.zip"))
        if cached_feeds:
            cached_feed = cached_feeds[0]
            print(f"   ✅ Using cached UK feed: {cached_feed.name}")
            parser = GtfsStaticParser(feed_path=cached_feed, service_date=None, bbox=None)
            summary = parser.get_summary()
            if summary:
                print(f"   📊 Feed summary: {summary}")
        else:
            bbox_str = None
            if config.GTFS_BBOX:
                parts = config.GTFS_BBOX.split(",")
                if len(parts) == 4:
                    try:
                        a, b, c, d = float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
                        if a > 20 and b > -20 and b < 20:
                            bbox_str = f"{b},{a},{d},{c}"
                        else:
                            bbox_str = config.GTFS_BBOX
                    except ValueError:
                        bbox_str = config.GTFS_BBOX
            try:
                feeds = tl_client.get_feeds(bbox=bbox_str)
                uk_feeds = [f for f in feeds if tl_client.is_uk_feed(f)]
                feeds_to_use = uk_feeds if uk_feeds else feeds
                print(f"   Discovered {len(feeds_to_use)} feed(s)")
                for f in feeds_to_use[:5]:
                    print(f"      • {f.get('onestop_id', 'unknown')} — {f.get('name', 'unnamed')}")
            except Exception as e:
                print(f"   ⚠️  Feed discovery failed: {e}")
                feeds_to_use = []
            if feeds_to_use:
                feed = feeds_to_use[0]
                feed_id = feed.get("onestop_id")
                if feed_id:
                    downloaded_feed_path = dl_dir / f"{feed_id}.zip"
                    if downloaded_feed_path.exists():
                        print(f"   Using cached feed: {downloaded_feed_path}")
                    else:
                        print(f"   Downloading feed {feed_id}...")
                        try:
                            tl_client.download_latest_feed(feed_id, downloaded_feed_path)
                            print(f"   ✅ Downloaded to {downloaded_feed_path}")
                        except Exception as e:
                            print(f"   ❌ Download failed: {e}")
                            downloaded_feed_path = None
                    if downloaded_feed_path and downloaded_feed_path.exists():
                        bbox_tuple = None
                        if config.GTFS_BBOX:
                            parts = [float(p) for p in config.GTFS_BBOX.split(",")]
                            if len(parts) == 4:
                                bbox_tuple = (parts[1], parts[0], parts[3], parts[2])
                        parser = GtfsStaticParser(feed_path=downloaded_feed_path, service_date=None, bbox=bbox_tuple)
                        summary = parser.get_summary()
                        if summary:
                            print(f"   📊 Feed summary: {summary}")

        # Transitland main loop — uses parser, not a client
        cycle = 0
        try:
            while True:
                cycle += 1
                print(f"\n🔄 Poll cycle {cycle}")
                raw_delays: list[dict] = []
                try:
                    if parser is not None:
                        raw_delays = parser.extract_delays_from_headways()
                except Exception as e:
                    print(f"   ❌ Unexpected error: {e}")
                if raw_delays:
                    print(f"   📊 {len(raw_delays)} delay event(s) detected")
                    for delay in raw_delays[:5]:
                        ctt_payload = normalize_to_ctt(delay, fleet_pool)
                        pub.send_string(json.dumps(ctt_payload))
                        print(f"   → {ctt_payload['truck_id']:20s} | route={ctt_payload['route']:20s} | "
                              f"efficiency={ctt_payload['efficiency_score']:.2f} | delay={ctt_payload['delay_minutes']}m")
                        time.sleep(0.3)
                else:
                    print("   ℹ️  No delays detected this cycle")
                time.sleep(config.HARVESTER_POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\n🛑 GTFS Harvester stopped by user.")
        finally:
            pub.close()
            context.term()
        return  # <-- Exit early; other modes handled below

    elif mode == "bods":
        # ------------------------------------------------------------------
        # BODS mode: GTFS-RT protobuf feed
        # ------------------------------------------------------------------
        bods_client = BodsClient(api_key=config.BODS_API_KEY, base_url=config.BODS_BASE_URL)
        print(f"   Backend: BODS ({config.BODS_BASE_URL})")
        print(f"   Coverage: UK-wide bus (England, Scotland, Wales)")

        cycle = 0
        try:
            while True:
                cycle += 1
                print(f"\n🔄 Poll cycle {cycle}")
                raw_delays: list[dict] = []
                try:
                    raw_delays = bods_client.fetch_trip_updates()
                except RetryExhaustedError as e:
                    print(f"   ❌ Data fetch failed after retries: {e}")
                except Exception as e:
                    print(f"   ❌ Unexpected error: {e}")
                if raw_delays:
                    print(f"   📊 {len(raw_delays)} delay event(s) detected")
                    for delay in raw_delays[:5]:
                        ctt_payload = normalize_to_ctt(delay, fleet_pool)
                        pub.send_string(json.dumps(ctt_payload))
                        print(f"   → {ctt_payload['truck_id']:20s} | route={ctt_payload['route']:20s} | "
                              f"efficiency={ctt_payload['efficiency_score']:.2f} | delay={ctt_payload['delay_minutes']}m")
                        time.sleep(0.3)
                else:
                    print("   ℹ️  No delays detected this cycle")
                time.sleep(config.HARVESTER_POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\n🛑 GTFS Harvester stopped by user.")
        finally:
            pub.close()
            context.term()
        return

    elif mode == "bat":
        # ------------------------------------------------------------------
        # BAT mode: Buses & Trains JSON API
        # ------------------------------------------------------------------
        bat_client = BatClient(api_key=config.BAT_API_KEY, base_url=config.BAT_BASE_URL)
        print(f"   Backend: BAT ({config.BAT_BASE_URL})")
        print(f"   Coverage: UK bus + rail (JSON API)")
        print(f"   Rate limit: 300 req/day")

        bus_stops_str = getattr(config, 'BAT_BUS_STOPS', '') or ''
        bus_stops = [s.strip() for s in bus_stops_str.split(',') if s.strip()]
        rail_stations_str = getattr(config, 'BAT_RAIL_STATIONS', '') or ''
        rail_stations = [s.strip() for s in rail_stations_str.split(',') if s.strip()]
        if not bus_stops and not rail_stations:
            rail_stations = ["PAD", "EUS", "KGX", "MYB", "BHM", "MAN", "EDB", "GLQ"]

        cycle = 0
        try:
            while True:
                cycle += 1
                print(f"\n🔄 Poll cycle {cycle}")
                raw_delays: list[dict] = []
                try:
                    raw_delays = bat_client.fetch_all_delays(bus_stops=bus_stops, rail_stations=rail_stations)
                except RetryExhaustedError as e:
                    print(f"   ❌ Data fetch failed after retries: {e}")
                except Exception as e:
                    print(f"   ❌ Unexpected error: {e}")
                if raw_delays:
                    print(f"   📊 {len(raw_delays)} delay event(s) detected")
                    for delay in raw_delays[:5]:
                        ctt_payload = normalize_to_ctt(delay, fleet_pool)
                        pub.send_string(json.dumps(ctt_payload))
                        print(f"   → {ctt_payload['truck_id']:20s} | route={ctt_payload['route']:20s} | "
                              f"efficiency={ctt_payload['efficiency_score']:.2f} | delay={ctt_payload['delay_minutes']}m")
                        time.sleep(0.3)
                else:
                    print("   ℹ️  No delays detected this cycle")
                time.sleep(config.HARVESTER_POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\n🛑 GTFS Harvester stopped by user.")
        finally:
            pub.close()
            context.term()
        return

    elif mode == "tfl":
        # ------------------------------------------------------------------
        # TfL mode: London line status
        # ------------------------------------------------------------------
        tfl_client = TflClient(base_url=config.TFL_BASE_URL)
        print(f"   Backend: TfL ({config.TFL_BASE_URL})")
        print(f"   Coverage: London only (bus, tube, DLR, Overground, Tram)")
        print(f"   Format: JSON (no API key required)")

        cycle = 0
        try:
            while True:
                cycle += 1
                print(f"\n🔄 Poll cycle {cycle}")
                raw_delays: list[dict] = []
                try:
                    raw_delays = tfl_client.fetch_line_status()
                except RetryExhaustedError as e:
                    print(f"   ❌ Data fetch failed after retries: {e}")
                except Exception as e:
                    print(f"   ❌ Unexpected error: {e}")
                if raw_delays:
                    print(f"   📊 {len(raw_delays)} delay event(s) detected")
                    for delay in raw_delays[:5]:
                        ctt_payload = normalize_to_ctt(delay, fleet_pool)
                        pub.send_string(json.dumps(ctt_payload))
                        print(f"   → {ctt_payload['truck_id']:20s} | route={ctt_payload['route']:20s} | "
                              f"efficiency={ctt_payload['efficiency_score']:.2f} | delay={ctt_payload['delay_minutes']}m")
                        time.sleep(0.3)
                else:
                    print("   ℹ️  No delays detected this cycle")
                time.sleep(config.HARVESTER_POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\n🛑 GTFS Harvester stopped by user.")
        finally:
            pub.close()
            context.term()
        return

    elif mode == "gtfs":
        # ------------------------------------------------------------------
        # Generic GTFS-RT mode
        # ------------------------------------------------------------------
        gtfs_client = GtfsRtClient(feed_url=config.GTFS_RT_FEED_URL)
        print(f"   Backend: Direct GTFS-RT ({config.GTFS_RT_FEED_URL})")

        cycle = 0
        try:
            while True:
                cycle += 1
                print(f"\n🔄 Poll cycle {cycle}")
                raw_delays: list[dict] = []
                try:
                    raw_delays = gtfs_client.fetch_trip_updates()
                except RetryExhaustedError as e:
                    print(f"   ❌ Data fetch failed after retries: {e}")
                except Exception as e:
                    print(f"   ❌ Unexpected error: {e}")
                if raw_delays:
                    print(f"   📊 {len(raw_delays)} delay event(s) detected")
                    for delay in raw_delays[:5]:
                        ctt_payload = normalize_to_ctt(delay, fleet_pool)
                        pub.send_string(json.dumps(ctt_payload))
                        print(f"   → {ctt_payload['truck_id']:20s} | route={ctt_payload['route']:20s} | "
                              f"efficiency={ctt_payload['efficiency_score']:.2f} | delay={ctt_payload['delay_minutes']}m")
                        time.sleep(0.3)
                else:
                    print("   ℹ️  No delays detected this cycle")
                time.sleep(config.HARVESTER_POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\n🛑 GTFS Harvester stopped by user.")
        finally:
            pub.close()
            context.term()
        return

    else:
        print(f"❌ Unknown mode: {mode}")
        sys.exit(1)

if __name__ == "__main__":
    mode = config.HARVESTER_MODE
    if len(sys.argv) > 1:
        mode = sys.argv[1]
    run_gtfs_harvester(mode=mode)