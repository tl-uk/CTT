// services/l1-engine/include/SimulationEngine.h
// Phase 7 — Flecs ECS with externality & social-impact systems
#pragma once
#include <flecs.h>
#include "AgentComponents.h"

namespace CTT {

    /**
     * @class SimulationEngine
     * @brief Manages the L1 Reflexive Layer physics using the Flecs ECS.
     */
    class SimulationEngine {
    public:
        SimulationEngine();

        /** @brief Returns the underlying Flecs world instance. */
        flecs::world& get_world();

        /** @brief Advances the Flecs world by delta_time. */
        void update(float delta_time);

        /** @brief Creates initial agents (eHGVs, Trains) in the world. */
        void initialize_test_fleet();

    private:
        flecs::world world;

        /** @brief Maps struct variables so they appear in the Flecs Explorer UI */
        void register_reflection();

        /** @brief Registers all Flecs systems (Energy, Kinematics, etc.) */
        void register_systems(); 
    };

} // namespace CTT