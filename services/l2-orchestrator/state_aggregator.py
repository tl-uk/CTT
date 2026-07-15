#!/usr/bin/env python3
"""
services/l2-orchestrator/state_aggregator.py

Phase 12d: Temporal Firewall — Reflexive DT → ABDT State Aggregation

Purpose: Batches 10ms tick telemetry into 1-second ABDT observations.
Ensures ABDT agents never see raw tick data, only aggregated state.

Architecture:
- SUBSCRIBES to: ctt-engine ZMQ PUB (tcp://ctt-engine:5555)
- PUBLISHES to: Kafka topic ctt.abdt.observation (JSON belief envelope)
- BUFFERS: Ring buffer of 100 ticks per agent
- FLUSHES: Every 1.0 second (or on significant event: mindset shift, collision)

Scaling considerations:
- 25 agents × 100 ticks/sec = 2,500 messages/sec input
- 25 agents × 1 observation/sec = 25 messages/sec output (100× reduction)
- Stateless: can be horizontally scaled behind a load balancer
"""
import json
import os
import sys
import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "config"))

import zmq
from ports import ZMQ_PORTS, get_resilient_socket

# =============================================================================
# Configuration
# =============================================================================

AGGREGATION_WINDOW_SEC = 1.0
SIGNIFICANT_EVENT_THRESHOLD = 5.0  # Pressure delta that triggers immediate flush
RING_BUFFER_SIZE = 120  # 100 ticks + 20% headroom

ZMQ_TELEMETRY_SUB = os.environ.get("CTT_ZMQ_TELEMETRY", "tcp://ctt-engine:5555")
KAFKA_BOOTSTRAP = os.environ.get("CTT_KAFKA", "ctt-kafka:9092")

# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class TickSnapshot:
    """Single 10ms tick state from reflexive layer."""
    timestamp_ms: int
    agent_id: str
    lat: float
    lon: float
    energy_pct: float
    speed_mps: float
    adversarial_pressure: float
    is_decarbonized: bool
    current_co2_g_km: float
    current_nox_g_km: float
    current_pm25_g_km: float
    current_noise_db: float
    cumulative_co2_kg: float
    accessibility_score: float
    jobs_dependent: int
    deprivation_index: float
    equity_exposure: float
    serves_deprived_ward: bool
    corridor_id: str
    has_ssn: bool

@dataclass
class AggregatedObservation:
    """1-second aggregated state for ABDT consumption."""
    observation_id: str
    agent_id: str
    window_start_ms: int
    window_end_ms: int
    tick_count: int

    # Position: mean and variance
    lat_mean: float
    lon_mean: float
    lat_var: float
    lon_var: float

    # Energy: trend
    energy_pct_start: float
    energy_pct_end: float
    energy_pct_min: float
    energy_pct_max: float

    # Kinematics: mean and max
    speed_mean_mps: float
    speed_max_mps: float

    # Mindset: trajectory
    pressure_start: float
    pressure_end: float
    pressure_max: float
    pressure_min: float
    decarbonized_at_start: bool
    decarbonized_at_end: bool
    mindset_shift_count: int  # Number of threshold crossings

    # Externalities: cumulative and peak
    co2_emitted_g: float  # Delta cumulative
    nox_emitted_g: float
    pm25_emitted_g: float
    noise_peak_db: float

    # Social: static (doesn't change per tick)
    accessibility_score: float
    jobs_dependent: int
    deprivation_index: float
    equity_exposure: float
    serves_deprived_ward: bool
    corridor_id: str

    # SSN: experience recorded this window
    ssn_recorded: bool

# =============================================================================
# State Aggregator
# =============================================================================

class StateAggregator:
    def __init__(self):
        self.ctx = zmq.Context()
        self.tele_sub = get_resilient_socket(self.ctx, zmq.SUB, is_sub=True)
        self._connect_with_retry(self.tele_sub, ZMQ_TELEMETRY_SUB)
        self.tele_sub.setsockopt_string(zmq.SUBSCRIBE, "")

        # Ring buffers per agent: {agent_id: deque[TickSnapshot]}
        self.buffers: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=RING_BUFFER_SIZE)
        )

        # Kafka producer (optional — can write to file for testing)
        self.kafka_producer = None
        try:
            from kafka import KafkaProducer
            self.kafka_producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                value_serializer=lambda v: json.dumps(v, default=str).encode('utf-8'),
                retries=3,
                retry_backoff_ms=1000,
                acks='all'  # Durability for ABDT state
            )
            print(f"[StateAggregator] Kafka connected to {KAFKA_BOOTSTRAP}")
        except Exception as e:
            print(f"[StateAggregator] ⚠️  Kafka unavailable: {e}")
            print(f"[StateAggregator] Writing observations to /tmp/ctt_observations.jsonl")

        self._running = False
        self.last_flush = time.time()
        self.lock = threading.RLock()

        # Observation counter for id generation
        self.observation_counter = 0

    def _connect_with_retry(self, socket, address, max_retries=30, delay=2.0):
        for attempt in range(max_retries):
            try:
                socket.connect(address)
                print(f"[StateAggregator] Connected to {address}")
                return
            except zmq.error.ZMQError as e:
                print(f"[StateAggregator] ⏳ Retry {attempt+1}/{max_retries}: {e}")
                time.sleep(delay)
        raise RuntimeError(f"Failed to connect to {address}")

    def _parse_tick(self, raw_json: str) -> List[TickSnapshot]:
        """Parse ZMQ telemetry JSON into TickSnapshot list."""
        try:
            data = json.loads(raw_json)
            if not isinstance(data, list):
                return []

            snapshots = []
            now_ms = int(time.time() * 1000)
            for agent in data:
                snap = TickSnapshot(
                    timestamp_ms=now_ms,
                    agent_id=agent.get("entity_name", "unknown"),
                    lat=agent.get("lat", 0.0),
                    lon=agent.get("lon", 0.0),
                    energy_pct=agent.get("energy_pct", 0.0),
                    speed_mps=agent.get("speed_mps", 0.0),  # May not be in telemetry
                    adversarial_pressure=agent.get("adversarial_pressure", 0.0),
                    is_decarbonized=agent.get("is_decarbonized", False),
                    current_co2_g_km=agent.get("current_co2_g_km", 0.0),
                    current_nox_g_km=agent.get("current_nox_g_km", 0.0),
                    current_pm25_g_km=agent.get("current_pm25_g_km", 0.0),
                    current_noise_db=agent.get("current_noise_db", 0.0),
                    cumulative_co2_kg=agent.get("cumulative_co2_kg", 0.0),
                    accessibility_score=agent.get("accessibility_score", 0.0),
                    jobs_dependent=agent.get("jobs_dependent", 0),
                    deprivation_index=agent.get("deprivation_index", 0.0),
                    equity_exposure=agent.get("equity_exposure", 0.0),
                    serves_deprived_ward=agent.get("serves_deprived_ward", False),
                    corridor_id=agent.get("corridor_id", "unknown"),
                    has_ssn=agent.get("has_ssn", False)
                )
                snapshots.append(snap)
            return snapshots
        except json.JSONDecodeError as e:
            print(f"[StateAggregator] JSON parse error: {e}")
            return []

    def _aggregate(self, agent_id: str, ticks: List[TickSnapshot]) -> AggregatedObservation:
        """Aggregate 100 ticks into a single ABDT observation."""
        if not ticks:
            raise ValueError("Empty tick list")

        self.observation_counter += 1
        obs_id = f"obs-{agent_id}-{ticks[0].timestamp_ms}-{self.observation_counter}"

        # Position statistics
        lats = [t.lat for t in ticks]
        lons = [t.lon for t in ticks]
        lat_mean = sum(lats) / len(lats)
        lon_mean = sum(lons) / len(lons)
        lat_var = sum((x - lat_mean) ** 2 for x in lats) / len(lats) if len(lats) > 1 else 0.0
        lon_var = sum((x - lon_mean) ** 2 for x in lons) / len(lons) if len(lons) > 1 else 0.0

        # Energy trend
        energy_vals = [t.energy_pct for t in ticks]

        # Speed (if not in telemetry, estimate from position delta)
        speed_vals = [t.speed_mps for t in ticks if t.speed_mps > 0]
        if not speed_vals:
            # Estimate from position delta
            speed_vals = [0.0]  # Fallback

        # Pressure trajectory
        pressures = [t.adversarial_pressure for t in ticks]

        # Mindset shifts
        decarbonized = [t.is_decarbonized for t in ticks]
        shift_count = sum(1 for i in range(1, len(decarbonized)) 
                         if decarbonized[i] != decarbonized[i-1])

        # Emissions delta
        co2_start = ticks[0].cumulative_co2_kg
        co2_end = ticks[-1].cumulative_co2_kg

        # Noise peak
        noise_vals = [t.current_noise_db for t in ticks]

        # SSN detection
        ssn_recorded = any(t.has_ssn for t in ticks)

        return AggregatedObservation(
            observation_id=obs_id,
            agent_id=agent_id,
            window_start_ms=ticks[0].timestamp_ms,
            window_end_ms=ticks[-1].timestamp_ms,
            tick_count=len(ticks),
            lat_mean=lat_mean,
            lon_mean=lon_mean,
            lat_var=lat_var,
            lon_var=lon_var,
            energy_pct_start=energy_vals[0],
            energy_pct_end=energy_vals[-1],
            energy_pct_min=min(energy_vals),
            energy_pct_max=max(energy_vals),
            speed_mean_mps=sum(speed_vals) / len(speed_vals),
            speed_max_mps=max(speed_vals),
            pressure_start=pressures[0],
            pressure_end=pressures[-1],
            pressure_max=max(pressures),
            pressure_min=min(pressures),
            decarbonized_at_start=decarbonized[0],
            decarbonized_at_end=decarbonized[-1],
            mindset_shift_count=shift_count,
            co2_emitted_g=(co2_end - co2_start) * 1000.0,  # kg → g
            nox_emitted_g=sum(t.current_nox_g_km for t in ticks) / 1000.0,  # Rough estimate
            pm25_emitted_g=sum(t.current_pm25_g_km for t in ticks) / 1000.0,
            noise_peak_db=max(noise_vals) if noise_vals else 0.0,
            accessibility_score=ticks[-1].accessibility_score,
            jobs_dependent=ticks[-1].jobs_dependent,
            deprivation_index=ticks[-1].deprivation_index,
            equity_exposure=ticks[-1].equity_exposure,
            serves_deprived_ward=ticks[-1].serves_deprived_ward,
            corridor_id=ticks[-1].corridor_id,
            ssn_recorded=ssn_recorded
        )

    def _flush_agent(self, agent_id: str):
        """Flush buffer for single agent and emit observation."""
        with self.lock:
            ticks = list(self.buffers[agent_id])
            self.buffers[agent_id].clear()

        if not ticks:
            return

        try:
            obs = self._aggregate(agent_id, ticks)
            obs_dict = asdict(obs)

            # Wrap in belief envelope for cross-domain compatibility
            envelope = {
                "meta": {
                    "schema_version": "ctt-belief-1.0",
                    "domain_id": "ctt-reflexive",
                    "corridor_id": obs.corridor_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source_host": "state-aggregator",
                    "ttl_seconds": 60,
                },
                "payload": obs_dict,
                "provenance": {
                    "upstream_domains": ["ctt-reflexive"],
                    "confidence": 1.0,
                    "model_version": "ctt-phase12d",
                    "tick_count": obs.tick_count
                }
            }

            if self.kafka_producer:
                self.kafka_producer.send('ctt.abdt.observation', envelope)
                self.kafka_producer.send('ctt.abdt.observation.' + obs.corridor_id, envelope)
            else:
                # File fallback for testing
                with open('/tmp/ctt_observations.jsonl', 'a') as f:
                    f.write(json.dumps(envelope) + '
')

            print(f"[StateAggregator] 📊 {agent_id}: {obs.tick_count} ticks → 1 observation "
                  f"(pressure: {obs.pressure_start:.1f}→{obs.pressure_end:.1f}, "
                  f"shifts: {obs.mindset_shift_count})")

        except Exception as e:
            print(f"[StateAggregator] ⚠️  Flush failed for {agent_id}: {e}")

    def _check_significant_event(self, snap: TickSnapshot) -> bool:
        """Check if tick represents a significant event requiring immediate flush."""
        with self.lock:
            buf = self.buffers.get(snap.agent_id, [])
            if not buf:
                return False
            last_pressure = buf[-1].adversarial_pressure if buf else 0.0
            pressure_delta = abs(snap.adversarial_pressure - last_pressure)
            return pressure_delta > SIGNIFICANT_EVENT_THRESHOLD

    def run(self):
        print("[StateAggregator] 🚀 Starting temporal firewall")
        print(f"[StateAggregator] Window: {AGGREGATION_WINDOW_SEC}s")
        print(f"[StateAggregator] Buffer: {RING_BUFFER_SIZE} ticks per agent")

        self._running = True
        last_flush = time.time()

        while self._running:
            try:
                # Non-blocking receive with timeout
                if self.tele_sub.poll(100):  # 100ms timeout
                    msg = self.tele_sub.recv_string()
                    ticks = self._parse_tick(msg)

                    for snap in ticks:
                        with self.lock:
                            self.buffers[snap.agent_id].append(snap)

                        # Significant event: immediate flush
                        if self._check_significant_event(snap):
                            print(f"[StateAggregator] ⚡ Significant event for {snap.agent_id}")
                            self._flush_agent(snap.agent_id)

                # Periodic flush
                now = time.time()
                if now - last_flush >= AGGREGATION_WINDOW_SEC:
                    for agent_id in list(self.buffers.keys()):
                        self._flush_agent(agent_id)
                    last_flush = now

            except Exception as e:
                print(f"[StateAggregator] 💥 Error: {e}")
                time.sleep(0.1)

        # Final flush on shutdown
        print("[StateAggregator] 🛑 Final flush...")
        for agent_id in list(self.buffers.keys()):
            self._flush_agent(agent_id)

    def stop(self):
        self._running = False
        if self.kafka_producer:
            self.kafka_producer.close()

if __name__ == "__main__":
    agg = StateAggregator()
    try:
        agg.run()
    except KeyboardInterrupt:
        print("
🛑 State aggregator stopping...")
        agg.stop()
    except Exception as e:
        import traceback
        print(f"
💥 Fatal: {e}")
        traceback.print_exc()
        agg.stop()
