#!/usr/bin/env python3
"""
services/l7-kg/sig_compressor.py

Semantic Signature Compressor — SSN observation → 128-dim vector.

Produces a compressed hash of {Stimulus, Procedure, Result} that can be
stored in the C++ Flecs ECS (SSN_Experience_Component) and matched via
cosine similarity at tick speed.
"""
import hashlib
import json
from typing import Dict, Any, List
import numpy as np

class SemanticSignatureCompressor:
    """
    Compresses SSN (System, Stimulus, Procedure, Result) observations into
    fixed-length semantic vectors for fast similarity matching in C++ ECS.
    """

    VECTOR_DIM = 128  # Must match SSN_Experience_Component in C++

    def __init__(self, dim: int = VECTOR_DIM):
        self.dim = dim

    def compress(self, stimulus: Dict[str, Any], 
                 procedure: Dict[str, Any],
                 result: Dict[str, Any]) -> np.ndarray:
        """
        Produce a normalized semantic signature vector.

        The hash is deterministic — same {stimulus, procedure, result} always
        produces the same vector, enabling C++ cosine similarity matching.
        """
        # Canonical JSON serialization for deterministic hashing
        canonical = json.dumps({
            "stimulus": self._canonicalize(stimulus),
            "procedure": self._canonicalize(procedure),
            "result": self._canonicalize(result)
        }, sort_keys=True, separators=(',', ':'))

        # SHA-256 → 32 bytes → expand to 128 dims via repeated hashing
        hash_bytes = hashlib.sha256(canonical.encode()).digest()

        # Expand to target dimension
        vector = np.zeros(self.dim, dtype=np.float32)
        for i in range(self.dim):
            byte_idx = i % len(hash_bytes)
            # Map byte [0, 255] to [-1, 1]
            vector[i] = (hash_bytes[byte_idx] / 127.5) - 1.0

        # L2 normalize for cosine similarity
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm

        return vector

    def _canonicalize(self, obj: Any) -> Any:
        """Recursively sort dict keys for deterministic serialization."""
        if isinstance(obj, dict):
            return {k: self._canonicalize(v) for k, v in sorted(obj.items())}
        elif isinstance(obj, list):
            return [self._canonicalize(v) for v in obj]
        elif isinstance(obj, float):
            # Round floats to avoid noise from precision differences
            return round(obj, 6)
        return obj

    def similarity(self, vec_a: np.ndarray, vec_b: np.ndarray) -> float:
        """Cosine similarity between two signature vectors."""
        return float(np.dot(vec_a, vec_b))


# =============================================================================
# Example usage / test
# =============================================================================
if __name__ == "__main__":
    compressor = SemanticSignatureCompressor()

    # Example: HGV driver switches to EV charging corridor
    sig1 = compressor.compress(
        stimulus={
            "corridor": "a20_charging_corridor",
            "pressure": 12.5,
            "energy_pct": 0.15,
            "time_of_day": "morning_peak"
        },
        procedure={
            "action": "switch_mode",
            "target": "BEV_ELECTRIC",
            "route": "a20_charging_corridor"
        },
        result={
            "success": True,
            "energy_saved_kwh": 45.2,
            "cost_delta_gbp": -12.50,
            "time_delta_min": 8
        }
    )

    # Similar situation, different time
    sig2 = compressor.compress(
        stimulus={
            "corridor": "a20_charging_corridor",
            "pressure": 13.1,
            "energy_pct": 0.18,
            "time_of_day": "evening_peak"
        },
        procedure={
            "action": "switch_mode",
            "target": "BEV_ELECTRIC",
            "route": "a20_charging_corridor"
        },
        result={
            "success": True,
            "energy_saved_kwh": 42.8,
            "cost_delta_gbp": -11.20,
            "time_delta_min": 6
        }
    )

    sim = compressor.similarity(sig1, sig2)
    print(f"SSN Signature similarity: {sim:.4f}")
    print(f"Vector shape: {sig1.shape}, dtype: {sig1.dtype}")
    print(f"Vector norm: {np.linalg.norm(sig1):.6f}")
