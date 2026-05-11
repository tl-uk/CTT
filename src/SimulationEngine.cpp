#include "SimulationEngine.hpp"
#include <iostream>

namespace CTT {

SimulationEngine::SimulationEngine() {
    // 1. Enable the L1 UI Portal (REST API & Web Explorer)
    // Using string-based import avoids 'unexpected namespace' errors in Clang/macOS
    world.import("flecs.monitor");
    world.import("flecs.rest");

    // 2. Initialize the REST server
    // Note: If 'Rest' is still not found, ensure FLECS_REST is enabled in your build.
#ifdef FLECS_REST
    world.set<flecs::rest::Rest>({}); 
    std::cout << "[L1 Engine] REST API enabled on port 8080" << std::endl;
#else
    std::cerr << "[L1 Engine] Warning: Flecs built without REST support!" << std::endl;
#endif

    // 3. Setup systems
    register_systems();
}

flecs::world& SimulationEngine::get_world() {
    return world;
}

void SimulationEngine::update(float delta_time) {
    // Progress the Flecs world (this triggers all registered systems)
    world.progress(delta_time);
}

void SimulationEngine::register_systems() {
    /**
     * @system EnergyConsumptionSystem
     * @brief Calculates energy drain based on speed and payload.
     * Filter: Only processes entities with the 'MicroActive' tag.
     */
    world.system<KinematicComponent, EnergyComponent, const PayloadComponent>("EnergyConsumptionSystem")
        .with<MicroActive>()
        .iter([](flecs::iter& it, KinematicComponent* kin, EnergyComponent* energy, const PayloadComponent* payload) {
            for (auto i : it) {
                float load_multiplier = 1.0f;
                if (payload[i].maxCapacityKg > 0) {
                    load_multiplier += (payload[i].currentLoadKg / payload[i].maxCapacityKg);
                }

                // Consumption math
                float consumption = energy[i].baseEfficiency * (kin[i].speed_mps / 10.0f) * load_multiplier * it.delta_time();
                energy[i].currentEnergyStorage -= consumption;

                if (energy[i].currentEnergyStorage < 0) {
                    energy[i].currentEnergyStorage = 0;
                }
            }
        });

    std::cout << "[L1 Engine] ECS Systems Registered." << std::endl;
}

void SimulationEngine::initialize_test_fleet() {
    auto ehgv = world.entity("Volvo_eHGV_001")
        .add<MicroActive>()
        .set<TaxonomyComponent>({TransportMode::ROAD_MOTORIZED, 2, false})
        .set<PayloadComponent>({CargoType::PALLETISED, 15000.0f, 40000.0f, 1, 2})
        .set<EnergyComponent>({PowertrainType::BEV_ELECTRIC, 600.0f, 600.0f, 1.5f})
        .set<KinematicComponent>({22.0f, 90.0f})
        .set<PositionComponent>({55.9533, -3.1883, 50.0f});

    std::cout << "[L1 Engine] Test fleet initialized." << std::endl;
}

} // namespace CTT