#!/usr/bin/env python3
"""
services/l7-kg/coalition_engine.py

Phase 13c: Coalition Formation — MMOG Guild/Party System

Purpose: Enable agents to form coalitions for collective action (bulk purchasing,
infrastructure lobbying, coordinated mode switches).

MMOG Analogy: Agents form "guilds" or "parties" based on shared interests.
- Discovery: Matchmaking by corridor + TCO gap compatibility
- Negotiation: Simple accept/reject protocol with BDI evaluation
- Commitment: Collective action if >60% of members commit

Architecture:
- CONSUMES: Kafka ctt.abdt.coalition (desires from BDI engines)
- PUBLISHES: Kafka ctt.abdt.action (collective actions)
- STORES: In-memory coalition registry (sharded by corridor)
"""
import json
import time
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from datetime import datetime, timezone

# =============================================================================
# Configuration
# =============================================================================

COALITION_TTL_MS = 3_600_000          # 1 hour coalition lifetime
COMMITMENT_THRESHOLD = 0.6            # 60% must commit for collective action
MAX_COALITION_SIZE = 50               # Prevent oversized coalitions

# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class Coalition:
    coalition_id: str
    corridor_id: str
    coalition_type: str                     # "bulk_purchase", "infrastructure_lobby", "mode_switch"
    members: Set[str] = field(default_factory=set)
    committed: Set[str] = field(default_factory=set)
    tco_gap_target: float = 0.0
    created_at_ms: int = 0
    status: str = "forming"                 # forming, active, dissolved

    def commitment_ratio(self) -> float:
        if not self.members:
            return 0.0
        return len(self.committed) / len(self.members)

    def is_expired(self) -> bool:
        return (int(time.time() * 1000) - self.created_at_ms) > COALITION_TTL_MS


class CoalitionEngine:
    """
    Manages coalition lifecycle across corridors.
    MMOG analogy: "Guild manager" server.
    """

    def __init__(self):
        self.coalitions: Dict[str, Coalition] = {}
        self.agent_coalitions: Dict[str, Set[str]] = defaultdict(set)
        self.lock = threading.RLock()

    def propose_coalition(self, agent_id: str, corridor_id: str, 
                          coalition_type: str, tco_gap: float) -> Optional[Coalition]:
        """Agent proposes a new coalition. Returns coalition if created."""
        with self.lock:
            # Check if agent already in active coalition of this type
            for cid in self.agent_coalitions.get(agent_id, set()):
                c = self.coalitions.get(cid)
                if c and c.coalition_type == coalition_type and c.status == "active":
                    return None

            coalition_id = f"coal-{corridor_id}-{uuid.uuid4().hex[:8]}"
            coalition = Coalition(
                coalition_id=coalition_id,
                corridor_id=corridor_id,
                coalition_type=coalition_type,
                members={agent_id},
                committed=set(),
                tco_gap_target=tco_gap,
                created_at_ms=int(time.time() * 1000),
                status="forming"
            )
            self.coalitions[coalition_id] = coalition
            self.agent_coalitions[agent_id].add(coalition_id)

            print(f"[Coalition] 🏛️  {agent_id} proposed {coalition_id} "
                  f"({coalition_type}) in {corridor_id}")
            return coalition

    def invite_members(self, coalition_id: str, candidate_ids: List[str]) -> None:
        """Invite candidates to join a coalition."""
        with self.lock:
            c = self.coalitions.get(coalition_id)
            if not c or c.status != "forming":
                return
            for aid in candidate_ids:
                if aid not in c.members and len(c.members) < MAX_COALITION_SIZE:
                    c.members.add(aid)
                    self.agent_coalitions[aid].add(coalition_id)
                    print(f"[Coalition] 📨 {aid} invited to {coalition_id}")

    def commit(self, agent_id: str, coalition_id: str) -> bool:
        """Agent commits to coalition. Returns True if threshold reached."""
        with self.lock:
            c = self.coalitions.get(coalition_id)
            if not c or agent_id not in c.members:
                return False

            c.committed.add(agent_id)
            ratio = c.commitment_ratio()
            print(f"[Coalition] ✋ {agent_id} committed to {coalition_id} "
                  f"({ratio*100:.0f}% of {len(c.members)})")

            if ratio >= COMMITMENT_THRESHOLD and c.status == "forming":
                c.status = "active"
                print(f"[Coalition] 🚀 {coalition_id} ACTIVATED ({ratio*100:.0f}% committed)")
                return True
            return False

    def dissolve(self, coalition_id: str, reason: str = "timeout") -> None:
        """Dissolve a coalition."""
        with self.lock:
            c = self.coalitions.pop(coalition_id, None)
            if c:
                for aid in c.members:
                    self.agent_coalitions[aid].discard(coalition_id)
                print(f"[Coalition] 💥 {coalition_id} dissolved ({reason})")

    def cleanup(self) -> None:
        """Remove expired coalitions."""
        with self.lock:
            expired = [cid for cid, c in self.coalitions.items() if c.is_expired()]
            for cid in expired:
                self.dissolve(cid, "expired")

    def generate_collective_action(self, coalition_id: str) -> Optional[Dict]:
        """Generate a collective action envelope for an active coalition."""
        with self.lock:
            c = self.coalitions.get(coalition_id)
            if not c or c.status != "active":
                return None

            return {
                "meta": {
                    "schema_version": "ctt-belief-1.0",
                    "domain_id": "ctt-abdt",
                    "corridor_id": c.corridor_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source_host": "coalition-engine",
                    "priority": "POLICY"
                },
                "payload": {
                    "coalition_id": c.coalition_id,
                    "coalition_type": c.coalition_type,
                    "member_count": len(c.members),
                    "committed_count": len(c.committed),
                    "member_ids": list(c.members),
                    "action_type": "collective_mode_switch" if c.coalition_type == "mode_switch" else "collective_lobby",
                    "tco_gap_target": c.tco_gap_target,
                    "corridor_id": c.corridor_id
                },
                "provenance": {
                    "upstream_domains": ["ctt-abdt"],
                    "confidence": c.commitment_ratio(),
                    "model_version": "ctt-phase13c"
                }
            }


if __name__ == "__main__":
    engine = CoalitionEngine()
    c = engine.propose_coalition("Agent_001", "a20_charging", "mode_switch", 8000.0)
    if c:
        engine.invite_members(c.coalition_id, ["Agent_002", "Agent_003", "Agent_004"])
        engine.commit("Agent_001", c.coalition_id)
        engine.commit("Agent_002", c.coalition_id)
        engine.commit("Agent_003", c.coalition_id)
        action = engine.generate_collective_action(c.coalition_id)
        print("\nCollective action:", json.dumps(action, indent=2) if action else None)
