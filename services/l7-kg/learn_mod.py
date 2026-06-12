#!/usr/bin/env python3
"""
services/l7-kg/learn_mod.py

Emergent Learning Module — Mines the SSN Knowledge Graph for population patterns:
• Social Avalanche detection (DBSCAN clustering of simultaneous mindset shifts)
• Policy Resistance identification (correlation between policy and regression events)
• Structural Resonance mapping (corridor-level habit clustering)

Outputs feed:
- LearnDash (tipping point alerts, habit resonance heatmap)
- ToC_Engine (emergent constraint discovery)
- WhatIf (policy blind spot warnings)
"""
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import numpy as np
from sklearn.cluster import DBSCAN

@dataclass
class SSNRecord:
    """Single SSN observation from the Knowledge Graph."""
    agent_id: str
    timestamp: datetime
    corridor_id: str
    stimulus: Dict[str, Any]
    procedure: Dict[str, Any]
    result: Dict[str, Any]
    signature: np.ndarray  # 128-dim from sig_compressor


class EmergentLearningModule:
    """
    Detects emergent patterns in population SSN records that individual agents
    cannot perceive. Enables "recognition over calculation" at the macro level.
    """

    def __init__(self, eps: float = 0.3, min_samples: int = 5):
        """
        Args:
            eps: DBSCAN neighbourhood radius (cosine similarity space)
            min_samples: Minimum agents for a cluster to count as "emergent"
        """
        self.eps = eps
        self.min_samples = min_samples
        self.records: List[SSNRecord] = []

    def ingest(self, record: SSNRecord):
        """Add a new SSN record to the learning corpus."""
        self.records.append(record)

    def detect_social_avalanche(self, 
                                 time_window_minutes: int = 30,
                                 corridor_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Detect clusters of simultaneous mindset shifts (social avalanches).

        Returns list of avalanche events with:
        - cluster_size: number of agents in the avalanche
        - corridor_id: spatial scope
        - trigger_signature: common semantic signature
        - confidence: DBSCAN density score
        """
        # Filter by time window and optional corridor
        now = datetime.now()
        recent = [
            r for r in self.records
            if (now - r.timestamp).total_seconds() / 60 < time_window_minutes
            and (corridor_id is None or r.corridor_id == corridor_id)
            and r.result.get("success", False)  # Only successful switches
        ]

        if len(recent) < self.min_samples:
            return []

        # Stack signatures for clustering
        X = np.stack([r.signature for r in recent])

        # DBSCAN in cosine similarity space (vectors are already L2-normalized)
        clustering = DBSCAN(eps=self.eps, min_samples=self.min_samples, metric='cosine').fit(X)

        avalanches = []
        unique_labels = set(clustering.labels_) - {-1}  # -1 is noise

        for label in unique_labels:
            mask = clustering.labels_ == label
            cluster_records = [r for r, m in zip(recent, mask) if m]

            # Centroid = average signature (L2 re-normalize)
            centroid = np.mean([r.signature for r in cluster_records], axis=0)
            centroid = centroid / np.linalg.norm(centroid)

            avalanches.append({
                "cluster_size": len(cluster_records),
                "corridor_id": cluster_records[0].corridor_id,
                "trigger_signature": centroid.tolist(),
                "confidence": float(np.mean([
                    np.dot(r.signature, centroid) for r in cluster_records
                ])),
                "agent_ids": [r.agent_id for r in cluster_records],
                "timestamp": min(r.timestamp for r in cluster_records).isoformat()
            })

        # Sort by cluster size descending
        avalanches.sort(key=lambda x: x["cluster_size"], reverse=True)
        return avalanches

    def identify_policy_resistance(self, 
                                    policy_type: str,
                                    lookback_hours: int = 24) -> Dict[str, Any]:
        """
        Identify corridors where agents regress (revert to ICE) after a policy
        was applied, indicating policy resistance.

        Returns resistance profile with:
        - resistance_ratio: fraction of agents that regressed
        - avg_regression_time_min: how quickly they regressed
        - correlated_factors: what stimulus factors correlate with resistance
        """
        # TODO: Implement correlation analysis between policy application
        # and subsequent MindsetRegressionEvent records
        return {
            "policy_type": policy_type,
            "status": "not_implemented",
            "note": "Requires MindsetRegressionEvent stream from L3"
        }

    def map_structural_resonance(self, corridor_id: str) -> Dict[str, Any]:
        """
        Map habit resonance patterns in a corridor — which stimuli cause
        synchronized behaviour across the population.

        Returns resonance map with:
        - resonance_score: 0-1 (higher = more synchronized)
        - dominant_stimulus: most common trigger signature
        - susceptible_agents: list of agent IDs prone to resonance
        """
        corridor_records = [r for r in self.records if r.corridor_id == corridor_id]

        if len(corridor_records) < self.min_samples:
            return {
                "corridor_id": corridor_id,
                "resonance_score": 0.0,
                "status": "insufficient_data"
            }

        X = np.stack([r.signature for r in corridor_records])
        clustering = DBSCAN(eps=self.eps, min_samples=self.min_samples, metric='cosine').fit(X)

        # Resonance = fraction of records that belong to clusters (not noise)
        noise_ratio = np.sum(clustering.labels_ == -1) / len(clustering.labels_)
        resonance_score = 1.0 - noise_ratio

        # Find dominant cluster
        if len(set(clustering.labels_) - {-1}) > 0:
            largest_cluster = max(set(clustering.labels_) - {-1}, 
                                  key=lambda l: np.sum(clustering.labels_ == l))
            dominant_mask = clustering.labels_ == largest_cluster
            dominant_records = [r for r, m in zip(corridor_records, dominant_mask) if m]
            dominant_stimulus = np.mean([r.signature for r in dominant_records], axis=0)
            dominant_stimulus = dominant_stimulus / np.linalg.norm(dominant_stimulus)
        else:
            dominant_stimulus = np.zeros(128)

        return {
            "corridor_id": corridor_id,
            "resonance_score": float(resonance_score),
            "record_count": len(corridor_records),
            "cluster_count": len(set(clustering.labels_) - {-1}),
            "dominant_stimulus": dominant_stimulus.tolist(),
            "susceptible_agents": list(set(r.agent_id for r in corridor_records))
        }


# =============================================================================
# Example usage
# =============================================================================
if __name__ == "__main__":
    from sig_compressor import SemanticSignatureCompressor
    from datetime import datetime, timedelta

    compressor = SemanticSignatureCompressor()
    learn = EmergentLearningModule(eps=0.3, min_samples=3)

    # Simulate 10 agents all having the same successful experience
    base_stimulus = {"corridor": "m20_corridor", "pressure": 15.0, "energy_pct": 0.2}
    base_procedure = {"action": "switch_mode", "target": "BEV_ELECTRIC"}
    base_result = {"success": True, "energy_saved_kwh": 50.0}

    for i in range(10):
        sig = compressor.compress(base_stimulus, base_procedure, base_result)
        learn.ingest(SSNRecord(
            agent_id=f"agent_{i:03d}",
            timestamp=datetime.now() - timedelta(minutes=i),
            corridor_id="m20_corridor",
            stimulus=base_stimulus,
            procedure=base_procedure,
            result=base_result,
            signature=sig
        ))

    avalanches = learn.detect_social_avalanche(time_window_minutes=60)
    print(f"Detected {len(avalanches)} social avalanche(s)")
    for av in avalanches:
        print(f"  Cluster size: {av['cluster_size']}, Confidence: {av['confidence']:.4f}")

    resonance = learn.map_structural_resonance("m20_corridor")
    print(f"\nResonance score: {resonance['resonance_score']:.4f}")