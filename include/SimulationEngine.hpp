#pragma once
#include <flecs.h>
#include "AgentComponents.hpp"

namespace CTT {

    /**
     * @class SimulationEngine
     * @brief Manages the L1 Reflexive Layer physics and entity lifecycle.
     * * Responsible for iterating over the EnTT registry to calculate real-time 
     * kinematics, energy consumption, and structural state changes (e.g., Decarbonization).
     */
    class SimulationEngine {
    public:
        SimulationEngine();
        ~SimulationEngine() = default;

        /**
         * @brief Advances the simulation state by the specified time step.
         * @param delta_time Time elapsed since the last tick (in seconds).
         */
        void update(float delta_time);

        /**
         * @brief Exposes the ECS registry for reading by the Digital Shadow (DataBridge).
         * @return A reference to the Flecs world.
         */
        flecs::world& get_world();

        /**
         * @brief Populates the simulation with initial test agents (e.g., eHGV, Train).
         */
        void initialize_test_fleet();

    private:
        flecs::world world;

        /**
         * @brief Calculates energy drain based on speed, load, and powertrain type.
         * @param delta_time Time elapsed since the last tick.
         */
        void system_energy_consumption(float delta_time);
    };

} // namespace CTT