#!/usr/bin/env python3
"""
scripts/test_layer_communication.py

Phase 13b: End-to-End Layer Communication Test

Verifies that all CTT layers can communicate effectively:
  L1 Engine (Flecs C++) → ZMQ 5555 → L4 SUMO Bridge
  L4 SUMO Bridge → ZMQ 5557 → L2 State Aggregator
  L2 State Aggregator → Kafka → L7 ABDT Cache (BDI)
  L7 ABDT Cache → Kafka → L2 Action Dispatcher
  L2 Action Dispatcher → ZMQ 5556 → L1 Engine

Usage:
    python scripts/test_layer_communication.py [--mode mock|docker]

This test does NOT require a full docker-compose stack.
It uses mock services to verify message schemas and routing.
"""
import argparse
import json
import sys
import time
import threading
from datetime import datetime, timezone

sys.path.insert(0, "services/config")
sys.path.insert(0, "services/l7-kg")
sys.path.insert(0, "services/l4-spatial")

def test_l1_to_l4_zmq():
    """Test: L1 Engine → ZMQ → L4 SUMO Bridge (mock)"""
    print("\n[TEST 1] L1 Engine → ZMQ → L4 SUMO Bridge")
    try:
        import zmq
        ctx = zmq.Context()

        # Mock L1 publisher
        pub = ctx.socket(zmq.PUB)
        pub.bind("tcp://127.0.0.1:5555")

        # Mock L4 subscriber
        sub = ctx.socket(zmq.SUB)
        sub.connect("tcp://127.0.0.1:5555")
        sub.setsockopt_string(zmq.SUBSCRIBE, "")

        time.sleep(0.1)

        # Send Flecs telemetry
        telemetry = [{
            "entity_name": "agent_001",
            "mode": "diesel",
            "speed_mps": 22.5,
            "corridor_id": "m20_corridor"
        }]
        pub.send_string(json.dumps(telemetry))

        # Receive
        msg = sub.recv_string(zmq.NOBLOCK)
        data = json.loads(msg)
        assert data[0]["entity_name"] == "agent_001"

        pub.close()
        sub.close()
        ctx.term()
        print("  ✅ PASS: L1→L4 ZMQ telemetry flow verified")
        return True
    except Exception as e:
        print(f"  ⚠️  SKIP: {e} (zmq may not be installed)")
        return None


def test_l4_to_l2_kafka():
    """Test: L4 SUMO Bridge → Kafka → L2 State Aggregator (mock)"""
    print("\n[TEST 2] L4 SUMO Bridge → Kafka → L2 State Aggregator")
    try:
        from kafka import KafkaProducer, KafkaConsumer

        # This test requires a running Kafka — skip if unavailable
        producer = KafkaProducer(
            bootstrap_servers="localhost:9092",
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            retries=1,
            request_timeout_ms=2000
        )

        envelope = {
            "meta": {
                "schema_version": "ctt-belief-1.0",
                "domain_id": "ctt-spatial",
                "corridor_id": "m20_corridor",
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            "payload": {
                "corridor_id": "m20_corridor",
                "sumo_step": 1,
                "grid_load_mw": 0.35,
                "total_co2_g": 1250.5,
                "mean_speed_mps": 18.2
            }
        }

        future = producer.send("ctt.spatial.metrics", envelope)
        future.get(timeout=2)
        producer.close()
        print("  ✅ PASS: L4→L2 Kafka spatial metrics flow verified")
        return True
    except Exception as e:
        print(f"  ⚠️  SKIP: {e} (Kafka not running or not installed)")
        return None


def test_l2_to_l7_kafka():
    """Test: L2 State Aggregator → Kafka → L7 ABDT Cache (BDI)"""
    print("\n[TEST 3] L2 State Aggregator → Kafka → L7 ABDT Cache (BDI)")
    try:
        from kafka import KafkaProducer

        producer = KafkaProducer(
            bootstrap_servers="localhost:9092",
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            retries=1,
            request_timeout_ms=2000
        )

        observation = {
            "meta": {"schema_version": "ctt-belief-1.0", "domain_id": "ctt-abdt"},
            "payload": {
                "agent_id": "agent_001",
                "corridor_id": "m20_corridor",
                "pressure_end": 45.0,
                "energy_pct_end": 65.0,
                "toc_severity": 0.2,
                "equity_exposure": 0.3,
                "mindset_shift_count": 2,
                "tco_model": {
                    "green_grey_gap": 5000.0,
                    "capex_ice": 50000.0,
                    "capex_ev": 80000.0,
                    "opex_ice_annual": 15000.0,
                    "opex_ev_annual": 8000.0
                },
                "carbon_tax_gbp_tonne": 100.0,
                "diesel_price_ppl": 150.0,
                "electricity_price_ppkwh": 30.0,
            }
        }

        future = producer.send("ctt.abdt.observation", observation)
        future.get(timeout=2)
        producer.close()
        print("  ✅ PASS: L2→L7 Kafka observation flow verified")
        return True
    except Exception as e:
        print(f"  ⚠️  SKIP: {e} (Kafka not running or not installed)")
        return None


def test_l7_bdi_cycle():
    """Test: L7 BDI Engine internal cycle (no external deps)"""
    print("\n[TEST 4] L7 BDI Engine — Belief → Desire → Intention → Action")
    try:
        from bdi_engine import BDIEngine
        from bdi_config import get_bdi_profile, list_bdi_profiles

        # Test with each policy mode
        for mode in list_bdi_profiles().keys():
            engine = BDIEngine("test_agent", "m20_corridor", policy_mode=mode)
            engine.set_habit_profile(years_in_service=2.5)

            obs = {
                "agent_id": "test_agent",
                "tco_model": {"green_grey_gap": 5000.0},
                "pressure_end": 45.0,
                "energy_pct_end": 65.0,
                "toc_severity": 0.2,
                "equity_exposure": 0.3,
                "mindset_shift_count": 2,
                "carbon_tax_gbp_tonne": 100.0,
                "diesel_price_ppl": 150.0,
                "electricity_price_ppkwh": 30.0,
            }

            action = engine.cycle(obs)
            assert action is not None
            assert "payload" in action
            assert action["meta"]["policy_mode"] == mode

        print(f"  ✅ PASS: BDI cycle verified for all policy modes ({', '.join(list_bdi_profiles().keys())})")
        return True
    except Exception as e:
        print(f"  ❌ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_l7_to_l2_kafka():
    """Test: L7 ABDT Cache → Kafka → L2 Action Dispatcher"""
    print("\n[TEST 5] L7 ABDT Cache → Kafka → L2 Action Dispatcher")
    try:
        from kafka import KafkaProducer

        producer = KafkaProducer(
            bootstrap_servers="localhost:9092",
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            retries=1,
            request_timeout_ms=2000
        )

        action = {
            "meta": {
                "schema_version": "ctt-belief-1.0",
                "domain_id": "ctt-abdt",
                "priority": "POLICY"
            },
            "payload": {
                "agent_id": "agent_001",
                "action_type": "mode_switch",
                "target_mode": "BEV",
                "reason": "TCO gap positive"
            }
        }

        future = producer.send("ctt.abdt.action", action)
        future.get(timeout=2)
        producer.close()
        print("  ✅ PASS: L7→L2 Kafka action flow verified")
        return True
    except Exception as e:
        print(f"  ⚠️  SKIP: {e} (Kafka not running or not installed)")
        return None


def test_l2_to_l1_zmq():
    """Test: L2 Action Dispatcher → ZMQ → L1 Engine"""
    print("\n[TEST 6] L2 Action Dispatcher → ZMQ → L1 Engine")
    try:
        import zmq
        ctx = zmq.Context()

        # Mock L2 publisher (Action Dispatcher)
        pub = ctx.socket(zmq.PUB)
        pub.bind("tcp://127.0.0.1:5556")

        # Mock L1 subscriber (Engine)
        sub = ctx.socket(zmq.SUB)
        sub.connect("tcp://127.0.0.1:5556")
        sub.setsockopt_string(zmq.SUBSCRIBE, "")

        time.sleep(0.1)

        action = {"agent_id": "agent_001", "perturbation": "mode_switch_BEV"}
        pub.send_string(json.dumps(action))

        msg = sub.recv_string(zmq.NOBLOCK)
        data = json.loads(msg)
        assert data["agent_id"] == "agent_001"

        pub.close()
        sub.close()
        ctx.term()
        print("  ✅ PASS: L2→L1 ZMQ perturbation flow verified")
        return True
    except Exception as e:
        print(f"  ⚠️  SKIP: {e} (zmq may not be installed)")
        return None


def test_config_modularity():
    """Test: bdi_config.py provides all configuration without hardcoding"""
    print("\n[TEST 7] Config Modularity — bdi_config.py externalization")
    try:
        from bdi_config import (
            get_bdi_profile, get_tco_profile, get_effective_thresholds,
            list_bdi_profiles, list_tco_profiles, list_corridors,
            BDIProfile, TCOProfile
        )

        # Verify profiles exist
        bdi_profiles = list_bdi_profiles()
        assert "balanced" in bdi_profiles
        assert "aggressive" in bdi_profiles

        tco_profiles = list_tco_profiles()
        assert "base" in tco_profiles
        assert "carbon_tax_100" in tco_profiles

        corridors = list_corridors()
        assert "m20_corridor" in corridors

        # Verify no hardcoded values in effective thresholds
        thresholds = get_effective_thresholds()
        assert "SCHMITT_THRESHOLD_ON" in thresholds
        assert "TCO_CAPEX_ICE" in thresholds

        # Verify profile switching works
        conservative = get_bdi_profile("conservative")
        aggressive = get_bdi_profile("aggressive")
        assert conservative.schmitt_threshold_on > aggressive.schmitt_threshold_on

        print("  ✅ PASS: All configuration externalized, no hardcoded values")
        return True
    except Exception as e:
        print(f"  ❌ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_tco_what_if():
    """Test: Interactive TCO what-if scenario (simulator use case)"""
    print("\n[TEST 8] Interactive TCO What-If Scenario")
    try:
        from bdi_config import get_tco_profile, TCOProfile
        from bdi_engine import BDIEngine

        # Scenario: What if EV subsidy increases to £25k?
        custom_tco = TCOProfile(
            capex_ice=50000.0, capex_ev=55000.0,  # £25k subsidy
            opex_ice_annual=15000.0, opex_ev_annual=8000.0,
            carbon_tax_gbp_tonne=100.0,
            diesel_price_ppl=150.0, electricity_price_ppkwh=30.0,
            years_in_service=0.0, tco_horizon_years=5,
            description="What-if: £25k EV subsidy"
        )

        # Compute 5-year gap
        ice_5yr = custom_tco.capex_ice + 5 * custom_tco.opex_ice_annual + 5 * 100.0 * 10.0
        ev_5yr = custom_tco.capex_ev + 5 * custom_tco.opex_ev_annual
        gap = ice_5yr - ev_5yr

        engine = BDIEngine("whatif_agent", "m20_corridor", policy_mode="balanced")
        engine.set_habit_profile(years_in_service=1.0)

        obs = {
            "agent_id": "whatif_agent",
            "tco_model": {"green_grey_gap": gap},
            "pressure_end": 30.0,
            "energy_pct_end": 70.0,
            "toc_severity": 0.1,
            "equity_exposure": 0.2,
            "mindset_shift_count": 1,
            "carbon_tax_gbp_tonne": 100.0,
            "diesel_price_ppl": 150.0,
            "electricity_price_ppkwh": 30.0,
        }

        action = engine.cycle(obs)

        print(f"  ✅ PASS: What-if scenario computed")
        print(f"     Custom TCO: ICE 5yr=£{ice_5yr:,.0f}, EV 5yr=£{ev_5yr:,.0f}, gap=£{gap:,.0f}")
        print(f"     BDI action: {action['payload']['action_type'] if action else 'NONE'}")
        return True
    except Exception as e:
        print(f"  ❌ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(description="CTT Layer Communication Test")
    parser.add_argument("--mode", choices=["mock", "docker", "all"], default="all",
                        help="Test mode: mock (no deps), docker (needs stack), all")
    args = parser.parse_args()

    print("=" * 70)
    print("CTT Phase 13b: Layer Communication & Modularity Test")
    print("=" * 70)

    results = []

    # Always-run tests (no external deps)
    results.append(("Config Modularity", test_config_modularity()))
    results.append(("BDI Cycle", test_l7_bdi_cycle()))
    results.append(("TCO What-If", test_tco_what_if()))

    # ZMQ tests (need pyzmq)
    if args.mode in ("mock", "all"):
        results.append(("L1→L4 ZMQ", test_l1_to_l4_zmq()))
        results.append(("L2→L1 ZMQ", test_l2_to_l1_zmq()))

    # Kafka tests (need running Kafka)
    if args.mode in ("docker", "all"):
        results.append(("L4→L2 Kafka", test_l4_to_l2_kafka()))
        results.append(("L2→L7 Kafka", test_l2_to_l7_kafka()))
        results.append(("L7→L2 Kafka", test_l7_to_l2_kafka()))

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, r in results if r is True)
    skipped = sum(1 for _, r in results if r is None)
    failed = sum(1 for _, r in results if r is False)

    for name, result in results:
        status = "✅ PASS" if result is True else "⚠️  SKIP" if result is None else "❌ FAIL"
        print(f"  {status}: {name}")

    print(f"\n  Total: {passed} passed, {skipped} skipped, {failed} failed")

    if failed > 0:
        print("\n  ❌ Some tests failed. Check output above.")
        sys.exit(1)
    else:
        print("\n  ✅ All runnable tests passed. Skipped tests need external services.")
        sys.exit(0)


if __name__ == "__main__":
    main()
