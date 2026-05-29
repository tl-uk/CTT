#!/usr/bin/env python3
"""
services/l6-gaiax/policy_enforcer.py

Phase 8 — ODRL Policy Enforcement Stub.

Attaches usage constraints to Kafka topics or ZMQ headers.
Example: Tesco HGV data can only be used for carbon calculations.
"""
import json
from typing import Optional

class ODRLEnforcer:
    """Minimal ODRL rule engine for CTT data streams."""

    def __init__(self):
        self.policies = {}

    def load_policy(self, policy_id: str, policy: dict):
        """Register an ODRL policy."""
        self.policies[policy_id] = policy
        print(f"[ODRL] Loaded policy: {policy_id}")

    def check(self, data_source: str, intended_use: str) -> bool:
        """Check if intended_use is permitted for data_source."""
        policy = self.policies.get(data_source)
        if not policy:
            return True  # No policy = permissive

        allowed = policy.get("allowed_uses", [])
        if intended_use in allowed:
            return True

        print(f"[ODRL] ❌ DENIED: {data_source} → {intended_use}")
        return False

if __name__ == "__main__":
    enforcer = ODRLEnforcer()
    enforcer.load_policy("tesco_hgv", {
        "allowed_uses": ["carbon_calculation", "emission_reporting"],
        "denied_uses": ["competitor_sharing", "commercial_resale"]
    })

    assert enforcer.check("tesco_hgv", "carbon_calculation") == True
    assert enforcer.check("tesco_hgv", "competitor_sharing") == False
    print("[ODRL] All tests passed.")
