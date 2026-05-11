#include "SimulationEngine.hpp"
#include <iostream>

namespace CTT {

SimulationEngine::SimulationEngine() {
    // 1. Enable the L1 UI Portal (REST API & Web Explorer)
    world.import<flecs::monitor>();
    world.set<flecs::rest::Reply>({});

    // 2. Setup systems
    register_systems();
}

flecs::world& SimulationEngine::get_world() {
    return world;
}

void SimulationEngine::register_systems() {
    // System: Energy Consumption (Only runs on MicroActive entities)
    world.system<KinematicComponent, EnergyComponent, const PayloadComponent>("EnergyConsumptionSystem")
        .with<MicroActive>() // Tag filtering
        .iter([](flecs::iter& it, KinematicComponent* kin, EnergyComponent* energy, const PayloadComponent* payload) {
            for (auto i : it) {
                float load_multiplier = 1.0f;
                if (payload[i].maxCapacityKg > 0) {
                    load_multiplier += (payload[i].currentLoadKg / payload[i].maxCapacityKg);
                }

                float consumption = energy[i].baseEfficiency * (kin[i].speed_mps / 10.0f) * load_multiplier * it.delta_time();
                energy[i].currentEnergyStorage -= consumption;

                if (energy[i].currentEnergyStorage < 0) {
                    energy[i].currentEnergyStorage = 0;
                }

                // SSN Detection: If battery > 50%, emit a "One-Shot Success"
                if (energy[i].currentEnergyStorage > (energy[i].maxEnergyStorage * 0.5f)) {
                    it.entity(i).add<OneShotSuccess>();
                }
            }
        });

    // System: SSN Observer (Catches the One-Shot Success)
    world.observer<OneShotSuccess>("SSN_SuccessDetector")
        .event(flecs::OnAdd)
        .each([](flecs::entity e, OneShotSuccess) {
            std::cout << "[SSN Vault] One-Shot Success Captured for: " << e.name() << std::endl;
            // Remove the tag so it can be triggered again later
            e.remove<OneShotSuccess>(); 
        });
}

void SimulationEngine::initialize_test_fleet() {
    // Flecs allows us to name entities, making the UI Explorer much easier to read
    auto ehgv = world.entity("Volvo_eHGV_001");
    ehgv.add<MicroActive>(); // Assign LOD Tag
    ehgv.set<TaxonomyComponent>({TransportMode::ROAD_MOTORIZED, static_cast<uint8_t>(2), false});
    ehgv.set<PayloadComponent>({CargoType::PALLETISED, 15000.0f, 40000.0f, 1, 2});
    ehgv.set<EnergyComponent>({PowertrainType::BEV_ELECTRIC, 600.0f, 600.0f, 1.5f});
    ehgv.set<KinematicComponent>({22.0f, 90.0f}); 
    ehgv.set<PositionComponent>({55.9533, -3.1883, 50.0f}); 

    auto train = world.entity("Freightliner_Class66");
    train.add<MicroActive>();
    train.set<TaxonomyComponent>({TransportMode::RAIL, static_cast<uint8_t>(1), false});
    train.set<PayloadComponent>({CargoType::PASSENGER, 0.0f, 0.0f, 120, 400});
    train.set<EnergyComponent>({PowertrainType::ICE_DIESEL, 5000.0f, 5000.0f, 3.2f});
    train.set<KinematicComponent>({30.0f, 0.0f});
    train.set<PositionComponent>({55.9520, -3.1900, 60.0f});

    std::cout << "[L1 Engine] Test fleet initialized in Flecs." << std::endl;
}

void SimulationEngine::update(float delta_time) {
    // world.progress() automatically executes all registered systems and observers
    world.progress(delta_time);
}

} // namespace CTT