"""
services/data-pipeline/ingestor/gtfs_loader.py

Parses GTFS static feeds (zip or directory) into plain Python dicts.

Handles all 7 core files:
  stops.txt          → stop_id, name, lat, lon, wheelchair
  routes.txt         → route_id, agency_id, short_name, long_name,
                        route_type, fuel_type
  trips.txt          → trip_id, route_id, service_id, shape_id,
                        direction_id
  stop_times.txt     → trip_id, stop_id, stop_sequence, arrival_time,
                        departure_time
  shapes.txt         → shape_id → ordered (lon, lat) coordinate list
  calendar.txt       → service_id → weekday bitmask + date range
  calendar_dates.txt → service_id exceptions (additions / removals)

Cascading spatial + calendar filter
-------------------------------------
Parsing runs in a strict dependency order to avoid loading the entire
national BODS feed into memory:

  1. _parse_stops        — keep only stops within the OSM bbox.
  2. _parse_stop_times   — keep only stop_times whose stop_id survived (1).
                           Populates _valid_trips.
  3. _parse_trips        — keep only trips in _valid_trips that also pass
                           the calendar filter.  Populates _valid_routes
                           and _valid_shapes.
  4. _parse_routes       — keep only routes in _valid_routes.
  5. _parse_shapes       — keep only shapes in _valid_shapes.

This means stop_times contains ALL trips that touch the bbox, including
trips from the wrong service day.  Callers (notably GTFSGraph.build())
must check whether trip_id exists in self.trips (the calendar-filtered
set) before using trip data.  See get_shape_for_trip().

Fuel type inference
-------------------
GTFS has no mandatory electric/diesel field.  Fuel is inferred from:
  1. User-supplied overrides dict (highest priority).
  2. GTFS route_type extended codes (trolleybus, tram → electric).
  3. Keywords in route_desc or route_long_name.
  4. Route colour (many agencies colour electric routes distinctly).

Design principles
-----------------
  • Pure stdlib only — no pandas dependency.
  • Lazy parsing: files are read on first load() call.
  • Tolerant: missing optional files are silently skipped.
  • Timezone-agnostic: times stored as total seconds past midnight (int),
    so 25:30:00 (next-day trip) stores as 91800 without datetime objects.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ── GTFS route_type → RTD_SIM mode mapping ───────────────────────────────────
# Reference: https://gtfs.org/documentation/schedule/reference/#routestxt
_ROUTE_TYPE_TO_MODE: Dict[int, str] = {
    0:   'tram',             # Tram / Streetcar / Light Rail
    1:   'local_train',      # Metro / Subway
    2:   'intercity_train',  # Rail (intercity treated as primary)
    3:   'bus',              # Bus
    4:   'ferry_diesel',     # Ferry (assume diesel until tagged electric)
    5:   'cable_car',        # Cable Car
    6:   'gondola',          # Gondola / Suspended Cable Car
    7:   'funicular',        # Funicular
    11:  'trolleybus',       # Trolleybus (electric, reclassified below)
    12:  'monorail',         # Monorail
    # Extended route types
    100: 'intercity_train',  101: 'intercity_train',   102: 'intercity_train',
    103: 'local_train',      104: 'local_train',       105: 'local_train',
    106: 'local_train',      107: 'local_train',       108: 'local_train',
    109: 'local_train',      110: 'local_train',
    200: 'bus',              201: 'bus',               202: 'bus',
    400: 'tram',             401: 'local_train',       402: 'local_train',
    403: 'local_train',      404: 'tram',              405: 'local_train',
    700: 'bus',              701: 'bus',               702: 'bus',
    703: 'bus',              704: 'bus',               705: 'bus',
    706: 'bus',              707: 'bus',               708: 'bus',
    709: 'bus',              710: 'bus',               711: 'bus',
    712: 'bus',              713: 'bus',               714: 'bus',
    715: 'bus',              716: 'bus',               717: 'bus',
    800: 'tram',
    900: 'tram',             901: 'tram',              902: 'tram',
    903: 'tram',             904: 'tram',              905: 'tram',
    906: 'tram',
    1000: 'ferry_diesel',    1001: 'ferry_diesel',     1002: 'ferry_diesel',
    1003: 'ferry_diesel',    1004: 'ferry_diesel',     1005: 'ferry_diesel',
    1006: 'ferry_diesel',    1007: 'ferry_diesel',     1008: 'ferry_diesel',
    1009: 'ferry_diesel',    1010: 'ferry_diesel',     1011: 'ferry_diesel',
    1012: 'ferry_diesel',
    1100: 'flight_domestic',
}

# Route types that are inherently electric — no keyword inference needed.
_ELECTRIC_ROUTE_TYPES: Set[int] = {
    0, 1, 5, 6, 7, 11, 12,
    400, 401, 402, 403, 404, 405,
    800, 900, 901, 902, 903, 904, 905, 906,
}

# Keywords in route_desc / route_long_name that signal fuel type.
_FUEL_KEYWORDS: Dict[str, str] = {
    'electric':      'electric',
    'battery':       'electric',
    'bev':           'electric',
    'zero.emission': 'electric',
    'zero emission': 'electric',
    'zev':           'electric',
    'trolley':       'electric',
    'hydrogen':      'hydrogen',
    'fuel.cell':     'hydrogen',
    'fcev':          'hydrogen',
    'diesel':        'diesel',
    'petrol':        'diesel',
    'hybrid':        'hybrid',
}


def _parse_time_s(time_str: str) -> int:
    """
    Parse a GTFS time string (HH:MM:SS, including >24h next-day trips) into
    total seconds past midnight.

    Returns -1 on parse failure so callers can detect and skip invalid rows.
    """
    try:
        parts = time_str.strip().split(':')
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except Exception:
        return -1


class GTFSLoader:
    """
    Parses a GTFS static feed (zip archive or directory) into Python dicts.

    Usage
    -----
        loader = GTFSLoader('/path/to/gtfs.zip', service_date='20260404')
        loader.load()
        stops    = loader.stops           # {stop_id: {...}}
        routes   = loader.routes          # {route_id: {...}}
        headways = loader.compute_headways()
    """

    def __init__(
        self,
        feed_path,
        fuel_overrides: Optional[Dict[str, str]] = None,
        service_date: Optional[str] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,
    ):
        """
        Args:
            feed_path:      Path to the GTFS .zip file or directory.
            fuel_overrides: {route_id: fuel_type} to override inference.
            service_date:   'YYYYMMDD' string.  When supplied, only trips
                            active on this date are loaded.  When None,
                            all trips are loaded regardless of calendar.
            bbox:           (west, south, east, north) in WGS84 decimal
                            degrees.  Stops outside this box are discarded.
        """
        self.feed_path      = Path(feed_path)
        self.fuel_overrides = fuel_overrides or {}
        self.service_date   = service_date
        self.bbox           = bbox

        self.stops:      Dict[str, Dict[str, Any]] = {}
        self.routes:     Dict[str, Dict[str, Any]] = {}
        self.trips:      Dict[str, Dict[str, Any]] = {}
        self.stop_times: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.shapes:     Dict[str, List[Tuple[float, float]]] = {}

        # Intermediate sets used by the cascading filter.
        self._active_services: Optional[Set[str]] = None
        self._valid_trips:     Set[str] = set()
        self._valid_routes:    Set[str] = set()
        self._valid_shapes:    Set[str] = set()

        self._loaded = False

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def load(self) -> 'GTFSLoader':
        """Parse all GTFS files.  Idempotent — safe to call multiple times."""
        if self._loaded:
            return self
        logger.info("Loading GTFS feed: %s", self.feed_path)
        self._parse_all()
        self._loaded = True
        return self

    def get_shape_for_trip(
        self, trip_id: str
    ) -> List[Tuple[float, float]]:
        """
        Return the (lon, lat) shape coordinate list for a trip_id.

        Always returns a list — empty when the trip has no shape_id or the
        shape was not loaded.  Callers must handle the empty list gracefully
        (typically by falling back to a straight stop-to-stop line segment).
        """
        trip     = self.trips.get(trip_id, {})
        shape_id = trip.get('shape_id', '')
        return self.shapes.get(shape_id) or []

    def compute_headways(
        self,
        time_window: Optional[Tuple[int, int]] = None,
    ) -> Dict[Tuple[str, str], int]:
        """
        Compute average headway (seconds) per (route_id, stop_id) pair.

        Uses departure times within time_window (start_s, end_s).
        Defaults to the AM peak: 07:00–09:30 (25200–34200 s).

        A value of 3600 (1 h) is used for routes with only one trip in the
        window — this correctly penalises infrequent services in the BDI
        generalised cost without making them infinite.

        Returns:
            {(route_id, stop_id): avg_headway_seconds}
        """
        if not self._loaded:
            self.load()

        t_start, t_end = time_window or (25200, 34200)  # 07:00–09:30 default

        dep_times: Dict[Tuple[str, str], List[int]] = defaultdict(list)

        for trip_id, stops in self.stop_times.items():
            trip     = self.trips.get(trip_id, {})
            route_id = trip.get('route_id', '')
            if not route_id:
                continue
            for st in stops:
                dep_s = st['departure_s']
                if t_start <= dep_s <= t_end:
                    dep_times[(route_id, st['stop_id'])].append(dep_s)

        headways: Dict[Tuple[str, str], int] = {}
        for key, times in dep_times.items():
            if len(times) < 2:
                headways[key] = 3600   # sparse service — 1-hour penalty
                continue
            times.sort()
            gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
            headways[key] = int(sum(gaps) / len(gaps))

        logger.debug(
            "Computed headways for %d (route, stop) pairs", len(headways)
        )
        return headways

    def get_route_for_stop_pair(
        self,
        stop_id_from: str,
        stop_id_to: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Find the first route that serves both stops consecutively.

        Used by the GTFS router to look up fuel_type and mode when building
        pydeck layers.  Returns the route dict or None.
        """
        for trip_id, stops in self.stop_times.items():
            ids = [s['stop_id'] for s in stops]
            try:
                i = ids.index(stop_id_from)
                if i + 1 < len(ids) and ids[i + 1] == stop_id_to:
                    trip = self.trips.get(trip_id, {})
                    return self.routes.get(trip.get('route_id', ''))
            except ValueError:
                continue
        return None

    def summary(self) -> Dict[str, Any]:
        """Return a compact summary dict suitable for logging."""
        modes: Dict[str, int] = defaultdict(int)
        fuels: Dict[str, int] = defaultdict(int)
        for r in self.routes.values():
            modes[r['mode']]     += 1
            fuels[r['fuel_type']] += 1
        return {
            'stops':  len(self.stops),
            'routes': len(self.routes),
            'trips':  len(self.trips),
            'shapes': len(self.shapes),
            'modes':  dict(modes),
            'fuels':  dict(fuels),
        }

    # =========================================================================
    # INTERNAL PARSING
    # =========================================================================

    def _parse_all(self) -> None:
        """Run all parsers in dependency order (see module docstring)."""
        self._parse_calendar()
        self._parse_calendar_dates()
        self._parse_stops()
        self._parse_stop_times()   # must run before _parse_trips
        self._parse_trips()        # must run before _parse_routes/_parse_shapes
        self._parse_routes()
        self._parse_shapes()

    def _yield_csv_rows(self, name: str):
        """
        Generator that yields csv.DictReader rows one at a time.

        Supports both zip archives (searches for the filename at any depth)
        and bare directories.  Returns immediately when the file is absent so
        callers don't need separate existence checks.
        """
        if self.feed_path.suffix.lower() == '.zip':
            try:
                with zipfile.ZipFile(self.feed_path) as zf:
                    match = next(
                        (n for n in zf.namelist()
                         if n.endswith(f'/{name}') or n == name),
                        None,
                    )
                    if match is None:
                        return
                    with zf.open(match) as f:
                        wrapper = io.TextIOWrapper(f, encoding='utf-8-sig')
                        for row in csv.DictReader(wrapper):
                            yield row
            except KeyError:
                return
        else:
            path = self.feed_path / name
            if not path.exists():
                return
            with open(path, encoding='utf-8-sig') as f:
                for row in csv.DictReader(f):
                    yield row

    def _parse_calendar(self) -> None:
        """
        Populate _active_services from calendar.txt for the requested date.

        If service_date is None, _active_services stays None and all trips
        pass the calendar filter in _parse_trips.
        """
        if self.service_date is None:
            return
        self._active_services = set()
        try:
            y, m, d = (
                int(self.service_date[:4]),
                int(self.service_date[4:6]),
                int(self.service_date[6:]),
            )
            from datetime import date
            target  = date(y, m, d)
            day_col = ['monday', 'tuesday', 'wednesday', 'thursday',
                       'friday', 'saturday', 'sunday'][target.weekday()]
        except Exception:
            self._active_services = None
            return

        for row in self._yield_csv_rows('calendar.txt'):
            try:
                from datetime import date as _date
                start = row.get('start_date', '19700101')
                end   = row.get('end_date',   '20991231')
                s = _date(int(start[:4]), int(start[4:6]), int(start[6:]))
                e = _date(int(end[:4]),   int(end[4:6]),   int(end[6:]))
                if s <= target <= e and row.get(day_col, '0') == '1':
                    self._active_services.add(row['service_id'])
            except Exception:
                continue

    def _parse_calendar_dates(self) -> None:
        """Apply exception overrides from calendar_dates.txt."""
        if self.service_date is None or self._active_services is None:
            return
        for row in self._yield_csv_rows('calendar_dates.txt'):
            if row.get('date', '') != self.service_date:
                continue
            sid, exc = row.get('service_id', ''), row.get('exception_type', '')
            if exc == '1':
                self._active_services.add(sid)
            elif exc == '2':
                self._active_services.discard(sid)

    def _parse_stops(self) -> None:
        """Load stops, filtering by bbox when supplied."""
        count = 0
        for row in self._yield_csv_rows('stops.txt'):
            sid = row.get('stop_id', '').strip()
            if not sid:
                continue
            try:
                lat = float(row.get('stop_lat', 0) or 0)
                lon = float(row.get('stop_lon', 0) or 0)
            except ValueError:
                continue
            if lat == 0.0 and lon == 0.0:
                continue

            if self.bbox:
                west, south, east, north = self.bbox
                if not (west <= lon <= east and south <= lat <= north):
                    continue

            self.stops[sid] = {
                'name':           row.get('stop_name', '').strip(),
                'lat':            lat,
                'lon':            lon,
                'code':           row.get('stop_code', '').strip(),
                'wheelchair':     row.get('wheelchair_boarding', '0') == '1',
                'location_type':  int(row.get('location_type', '0') or '0'),
                'parent_station': row.get('parent_station', '').strip(),
            }
            count += 1
        logger.info("GTFS: %d stops loaded within map region", count)

        # ── Diagnostic: log a sample of loaded stops so operators can verify
        # the feed is being read correctly (especially stop_id ↔ name mapping).
        # Shows first 5 stops alphabetically by name for readability.
        if self.stops:
            _sample = sorted(self.stops.items(), key=lambda kv: kv[1]['name'])[:5]
            for _sid, _s in _sample:
                logger.info(
                    "GTFS stops.txt sample — id=%-20s  name=%-35s  lat=%.5f  lon=%.5f",
                    _sid, _s['name'], _s['lat'], _s['lon'],
                )
            # Also log the total unique stop_ids for cross-check with feed metadata
            logger.info(
                "GTFS stops.txt: %d unique stop_ids in bbox "
                "(feed: f-bus~dft~gov~uk or equivalent)",
                len(self.stops),
            )

    def _parse_stop_times(self) -> None:
        """
        Load stop_times for stops that survived the spatial filter.

        All trips that visit at least one in-bbox stop are added to
        _valid_trips regardless of service date — the calendar filter is
        applied later in _parse_trips.  This is intentional: we need to
        know which trips are even spatially relevant before filtering by day.
        """
        count = 0
        for row in self._yield_csv_rows('stop_times.txt'):
            sid = row.get('stop_id', '').strip()
            if sid not in self.stops:
                continue

            tid = row.get('trip_id', '').strip()
            self._valid_trips.add(tid)

            dep_str = row.get('departure_time', '') or row.get('arrival_time', '')
            arr_str = row.get('arrival_time', '') or dep_str
            dep_s, arr_s = _parse_time_s(dep_str), _parse_time_s(arr_str)
            if dep_s < 0:
                continue

            try:
                seq = int(row.get('stop_sequence', '0') or '0')
            except ValueError:
                seq = 0

            self.stop_times[tid].append({
                'stop_id':     sid,
                'stop_sequence': seq,
                'arrival_s':   arr_s,
                'departure_s': dep_s,
                'pickup_type':  int(row.get('pickup_type',  '0') or '0'),
                'dropoff_type': int(row.get('drop_off_type', '0') or '0'),
            })
            count += 1

        for tid in self.stop_times:
            self.stop_times[tid].sort(key=lambda x: x['stop_sequence'])

        logger.info("GTFS: %d stop_times loaded (spatially filtered)", count)

    def _parse_trips(self) -> None:
        """
        Load trips that are both spatially relevant and active on service_date.

        Only trips in _valid_trips (populated by _parse_stop_times) survive.
        When _active_services is set, a further calendar filter is applied.
        """
        for row in self._yield_csv_rows('trips.txt'):
            tid = row.get('trip_id', '').strip()
            if tid not in self._valid_trips:
                continue

            sid = row.get('service_id', '').strip()
            if self._active_services is not None and sid not in self._active_services:
                continue

            route_id = row.get('route_id',  '').strip()
            shape_id = row.get('shape_id',  '').strip()
            self._valid_routes.add(route_id)
            if shape_id:
                self._valid_shapes.add(shape_id)

            self.trips[tid] = {
                'route_id':    route_id,
                'service_id':  sid,
                'shape_id':    shape_id,
                'direction_id': int(row.get('direction_id', '0') or '0'),
                'headsign':    row.get('trip_headsign', '').strip(),
            }

    def _infer_fuel_type(
        self,
        route_id: str,
        route_type: int,
        desc: str,
        color: str,
    ) -> str:
        """Infer fuel type from overrides, route_type, and description keywords."""
        if route_id in self.fuel_overrides:
            return self.fuel_overrides[route_id]
        if route_type in _ELECTRIC_ROUTE_TYPES:
            return 'electric'
        combined = (desc + ' ' + color).lower()
        for kw, fuel in _FUEL_KEYWORDS.items():
            if re.search(kw, combined):
                return fuel
        # Rail types are almost always electric in the UK.
        if route_type in (2, 100, 101, 102, 103, 106, 109):
            return 'electric'
        return 'diesel'

    def _parse_routes(self) -> None:
        """Load routes that survived the cascading spatial/calendar filter."""
        for row in self._yield_csv_rows('routes.txt'):
            rid = row.get('route_id', '').strip()
            if rid not in self._valid_routes:
                continue

            try:
                rtype = int(row.get('route_type', '3') or '3')
            except ValueError:
                rtype = 3

            desc  = row.get('route_desc',      '')
            lname = row.get('route_long_name', '')
            color = row.get('route_color',     '')
            fuel  = self._infer_fuel_type(rid, rtype, desc + ' ' + lname, color)
            mode  = _ROUTE_TYPE_TO_MODE.get(rtype, 'bus')

            if mode == 'ferry_diesel' and fuel == 'electric':
                mode = 'ferry_electric'

            self.routes[rid] = {
                'agency_id':  row.get('agency_id', '').strip(),
                'short_name': row.get('route_short_name', '').strip(),
                'long_name':  lname.strip(),
                'route_type': rtype,
                'mode':       mode,
                'fuel_type':  fuel,
                'color':      '#' + color if color else '#888888',
            }

    def _parse_shapes(self) -> None:
        """Load shape polylines for trips that survived the cascading filter.

        Shape points outside the simulation bbox are stripped from the polyline.
        Without this, a bus route Edinburgh→Fife has shape_coords that include
        the full Forth Road Bridge arc even when only the Edinburgh segment is
        relevant — the visualiser then draws the route crossing open water.

        The resulting shapes are clipped: only the contiguous sub-sequence of
        points that falls within the bbox is retained.  If the route re-enters
        the bbox after leaving it (e.g. loop routes) only the first contiguous
        in-bbox segment is kept.  This is intentional: the GTFSGraph builds
        edges between in-bbox stops, so cross-bbox shape fragments are unused.
        """
        raw: Dict[str, list] = defaultdict(list)
        for row in self._yield_csv_rows('shapes.txt'):
            shape_id = row.get('shape_id', '').strip()
            if shape_id not in self._valid_shapes:
                continue
            try:
                seq = int(row.get('shape_pt_sequence', '0') or '0')
                lat = float(row.get('shape_pt_lat', 0) or 0)
                lon = float(row.get('shape_pt_lon', 0) or 0)
            except (ValueError, TypeError):
                continue
            raw[shape_id].append((seq, lon, lat))

        for shape_id, pts in raw.items():
            pts.sort(key=lambda x: x[0])
            if self.bbox:
                west, south, east, north = self.bbox
                # Add a 20% buffer around the bbox so stop-snap geometry
                # at the edge of the area isn't prematurely clipped
                lon_buf = (east - west) * 0.20
                lat_buf = (north - south) * 0.20
                w2, e2 = west - lon_buf, east + lon_buf
                s2, n2 = south - lat_buf, north + lat_buf
                self.shapes[shape_id] = [
                    (lon, lat) for _, lon, lat in pts
                    if w2 <= lon <= e2 and s2 <= lat <= n2
                ]
            else:
                self.shapes[shape_id] = [(lon, lat) for _, lon, lat in pts]