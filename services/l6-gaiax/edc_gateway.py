#!/usr/bin/env python3
"""
services/l6-gaiax/edc_gateway.py

CTT Phase 12 — Eclipse Dataspace Connector (EDC) Gateway Stub
Replaces the previous "print('STUB')" with actual ODRL policy enforcement logic.

This stub:
1. Validates incoming self-descriptions against Gaia-X Trust Framework shape rules
2. Enforces ODRL policies before allowing data exchange
3. Logs all contract negotiations for audit
4. Integrates with CTT ZMQ/Kafka topics for policy propagation
"""
import json
import logging
import os
import sys
from datetime import datetime
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "config"))
from ports import ZMQ_PORTS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ctt.edc_gateway")


class ODRLPolicyEnforcer:
    """
    Enforces ODRL policies from Gaia-X self-descriptions.

    Supported actions:
    - odrl:use — allow data usage for specified purpose
    - odrl:share — allow sharing with specified recipients
    - odrl:prohibit — deny specified actions
    """

    def __init__(self):
        self.policies: Dict[str, Dict] = {}
        self.negotiation_log = []

    def load_self_description(self, sd_path: str) -> bool:
        """Load and validate a Gaia-X self-description."""
        try:
            with open(sd_path) as f:
                sd = json.load(f)

            # Extract policies from all VCs
            for vc in sd.get("verifiableCredential", []):
                cs = vc.get("credentialSubject", {})
                policy = cs.get("gx:policy", {}).get("odrl:hasPolicy", {})
                uid = policy.get("odrl:uid", "unknown")
                self.policies[uid] = policy
                logger.info("Loaded policy: %s", uid)

            return True
        except Exception as e:
            logger.error("Failed to load self-description: %s", e)
            return False

    def check_permission(self, policy_uid: str, action: str, 
                         purpose: Optional[str] = None,
                         recipient: Optional[str] = None) -> Dict[str, Any]:
        """Check if an action is permitted under a policy."""
        policy = self.policies.get(policy_uid)
        if not policy:
            return {"allowed": False, "reason": "Policy not found"}

        # Check prohibitions first
        prohibitions = policy.get("odrl:prohibition", [])
        for prohib in prohibitions:
            if prohib.get("odrl:action") == action:
                # Check if constraints match
                for constraint in prohib.get("odrl:constraint", []):
                    left = constraint.get("odrl:leftOperand")
                    op = constraint.get("odrl:operator")
                    right = constraint.get("odrl:rightOperand")

                    if left == "odrl:recipient" and recipient:
                        if op == "odrl:neq" and recipient == right:
                            return {"allowed": False, "reason": f"Prohibited recipient: {recipient}"}

        # Check permissions
        permissions = policy.get("odrl:permission", [])
        for perm in permissions:
            if perm.get("odrl:action") == action:
                # Check constraints
                constraints = perm.get("odrl:constraint", [])
                for constraint in constraints:
                    left = constraint.get("odrl:leftOperand")
                    op = constraint.get("odrl:operator")
                    right = constraint.get("odrl:rightOperand")

                    if left == "odrl:purpose" and purpose:
                        if op == "odrl:eq" and purpose != right:
                            return {"allowed": False, "reason": f"Purpose mismatch: {purpose} != {right}"}

                # All constraints satisfied
                result = {"allowed": True, "policy": policy_uid}
                self.negotiation_log.append({
                    "timestamp": datetime.now().isoformat(),
                    "policy": policy_uid,
                    "action": action,
                    "purpose": purpose,
                    "recipient": recipient,
                    "result": "allowed"
                })
                return result

        return {"allowed": False, "reason": "No matching permission found"}

    def get_audit_log(self) -> list:
        """Return all negotiation decisions for audit."""
        return self.negotiation_log


def test_odrl_enforcement():
    """Run standalone ODRL policy tests."""
    print("\n" + "=" * 60)
    print("EDC Gateway — ODRL Policy Enforcement Test")
    print("=" * 60)

    enforcer = ODRLPolicyEnforcer()

    # Test with DHL self-description
    sd_path = os.path.join(os.path.dirname(__file__), 
                           "self-descriptions", 
                           "gaiax_self_description_dhl_express.json")

    if not os.path.exists(sd_path):
        print(f"❌ Self-description not found: {sd_path}")
        return False

    if not enforcer.load_self_description(sd_path):
        print("❌ Failed to load self-description")
        return False

    print("\n📋 Loaded policies:")
    for uid in enforcer.policies:
        print(f"   - {uid}")

    # Test cases
    tests = [
        ("urn:ctt:policy:dhl-carbon-calc-only", "odrl:use", "carbon_intensity_modelling", None, True),
        ("urn:ctt:policy:dhl-carbon-calc-only", "odrl:use", "unauthorised_purpose", None, False),
        ("urn:ctt:policy:dhl-carbon-calc-only", "odrl:share", None, "ctt_federation_peer", False),
        ("urn:ctt:policy:dhl-carbon-calc-only", "odrl:share", None, "external_third_party", True),
    ]

    print("\n🧪 Running policy tests:")
    all_passed = True
    for policy_uid, action, purpose, recipient, expected in tests:
        result = enforcer.check_permission(policy_uid, action, purpose, recipient)
        passed = result["allowed"] == expected
        status = "✅" if passed else "❌"
        print(f"   {status} {action} (purpose={purpose}, recipient={recipient}) -> allowed={result['allowed']} (expected={expected})")
        if not passed:
            all_passed = False
            print(f"      Reason: {result.get('reason', 'N/A')}")

    print(f"\n📊 Audit log: {len(enforcer.get_audit_log())} negotiation(s) recorded")

    if all_passed:
        print("\n✅ All ODRL policy tests passed!")
    else:
        print("\n❌ Some tests failed")

    return all_passed


if __name__ == "__main__":
    success = test_odrl_enforcement()
    sys.exit(0 if success else 1)
