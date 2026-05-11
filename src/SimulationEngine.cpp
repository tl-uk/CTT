#include "SimulationEngine.hpp"
#include <iostream>

namespace CTT {

SimulationEngine::SimulationEngine() {
    // Use the component types as template arguments, not strings.
    // This resolves the C/C++(304) template match error.
    world.import<flecs::monitor>();
    
    // Note: If 'Rest' is still not found, it's a build-time configuration issue.
    // We use a conditional check to ensure the code compiles even if the module is missing.
#if defined(FLECS_REST) || defined(flecs_rest_EXPORTS)
    world.import<flecs::rest>(); 
    world.set<flecs::rest::Rest>({}); 
    std::cout << "[L1 Engine] Flecs REST API active on port 8080" << std::endl;
#else
    std::cout << "[L1 Engine] Note: REST module not detected in current build." << std::endl;
#endif

    register_systems();
}

flecs::world& SimulationEngine::get_world() {
    return world;
}

void SimulationEngine::update(float delta_time) {
    world.progress(delta_time);
}

void SimulationEngine::register_systems() {
    // Energy Consumption System
    world.system<KinematicComponent, EnergyComponent, const PayloadComponent>("EnergyConsumptionSystem")
        .with<MicroActive>()
        .iter([](flecs::iter& it, KinematicComponent* kin, EnergyComponent* energy, const PayloadComponent* payload) {
            for (auto i : it) {
                float load_multiplier = 1.0f;
                if (payload[i].maxCapacityKg > 0) {
                    load_multiplier += (payload[i].currentLoadKg / payload[i].maxCapacityKg);
                }

                float consumption = energy[i].baseEfficiency * (kin[i].speed_mps / 10.0f) * load_multiplier * it.delta_time();
                energy[i].currentEnergyStorage -= consumption;
                
                if (energy[i].currentEnergyStorage < 0) energy[i].currentEnergyStorage = 0;
            }
        });
}

void SimulationEngine::initialize_test_fleet() {
    world.entity("Volvo_eHGV_001")
        .add<MicroActive>()
        .set<TaxonomyComponent>({TransportMode::ROAD_MOTORIZED, 2, false})
        .set<PayloadComponent>({CargoType::PALLETISED, 15000.0f, 40000.0f, 1, 2})
        .set<EnergyComponent>({PowertrainType::BEV_ELECTRIC, 600.0f, 600.0f, 1.5f})
        .set<KinematicComponent>({22.0f, 90.0f})
        .set<PositionComponent>({55.9533, -3.1883, 50.0f});
}

} // namespace CTT