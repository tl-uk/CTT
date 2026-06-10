// services/l7-kg/include/ssn_experience_component.h
// Phase 9 — C++ Flecs component for compressed SSN semantic signatures
#pragma once
#include <array>
#include <cstdint>

namespace CTT {

/**
 * @struct SSN_Experience_Component
 * @brief Compressed semantic signature for Knowledge Graph matching.
 * 
 * Stores a 128-dimensional float32 vector (L2-normalized) that represents
 * the hash of {Stimulus, Procedure, Result}. Enables cosine similarity
 * matching at tick speed without Python round-trips.
 * 
 * Size: 128 * 4 = 512 bytes per component. 
 * For 10,000 agents with 100 experiences each: ~512 MB — manageable.
 */
struct SSN_Experience_Component {
    static constexpr size_t VECTOR_DIM = 128;

    // Compressed semantic signature (L2-normalized)
    std::array<float, VECTOR_DIM> signature;

    // Metadata for KG indexing (not used in similarity calc)
    uint64_t experience_id;      // Unique record ID
    uint64_t timestamp_ms;       // Unix timestamp in milliseconds
    float confidence;            // Match confidence from Python KG
    bool is_one_shot_success;    // True if this was a decarbonization milestone

    // Cosine similarity with another signature (fast, no allocations)
    float cosine_similarity(const SSN_Experience_Component& other) const {
        float dot = 0.0f;
        for (size_t i = 0; i < VECTOR_DIM; ++i) {
            dot += signature[i] * other.signature[i];
        }
        // Both vectors are L2-normalized, so dot product == cosine similarity
        return dot;
    }
};

} // namespace CTT
