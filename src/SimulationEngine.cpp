#include "SimulationEngine.hpp"
#include "AgentComponents.hpp"
#include <iostream>

namespace CTT {

SimulationEngine::SimulationEngine() {
    // Initialization logic can go here
}

entt::registry& SimulationEngine::get_registry() {
    return registry;
}

void SimulationEngine::initialize_test_fleet() {
    // 1. Create a Road Freight Agent (eHGV)
    auto ehgv = registry.create();
    registry.emplace<TaxonomyComponent>(ehgv, TransportMode::ROAD_MOTORIZED, 2, false);
    registry.emplace<PayloadComponent>(ehgv, CargoType::PALLETISED, 15000.0f, 40000.0f, 1, 2);
    registry.emplace<EnergyComponent>(ehgv, PowertrainType::BEV_ELECTRIC, 600.0f, 600.0f, 1.5f);
    registry.emplace<KinematicComponent>(ehgv, 22.0f, 90.0f); // approx 80 km/h
    registry.emplace<PositionComponent>(ehgv, 55.9533, -3.1883, 50.0f); // Edinburgh coordinates

    // 2. Create a Rail Agent (Diesel Train)
    auto train = registry.create();
    registry.emplace<TaxonomyComponent>(train, TransportMode::RAIL, 1, false);
    registry.emplace<PayloadComponent>(train, CargoType::PASSENGER, 0.0f, 0.0f, 120, 400);
    registry.emplace<EnergyComponent>(train, PowertrainType::ICE_DIESEL, 5000.0f, 5000.0f, 3.2f);
    registry.emplace<KinematicComponent>(train, 30.0f, 0.0f);
    registry.emplace<PositionComponent>(train, 55.9520, -3.1900, 60.0f);

    std::cout << "[L1 Engine] Test fleet initialized in ECS." << std::endl;
}

void SimulationEngine::update(float delta_time) {
    // Run all L1 physics systems in sequence
    system_energy_consumption(delta_time);
    
    // Future systems will be added here:
    // system_kinematics(delta_time);
    // system_schmitt_trigger(); 
}

void SimulationEngine::system_energy_consumption(float delta_time) {
    // Query all entities that have Movement, Energy, and Payload components
    auto view = registry.view<KinematicComponent, EnergyComponent, PayloadComponent>();

    view.each([&](auto entity, auto& kinematics, auto& energy, auto& payload) {
        // Calculate load penalty: Heavier vehicles drain energy faster
        float load_multiplier = 1.0f;
        if (payload.maxCapacityKg > 0) {
            load_multiplier += (payload.currentLoadKg / payload.maxCapacityKg);
        }

        // Calculate consumption
        float consumption = energy.baseEfficiency * (kinematics.speed_mps / 10.0f) * load_multiplier * delta_time;
        energy.currentEnergyStorage -= consumption;

        // Prevent negative energy
        if (energy.currentEnergyStorage < 0) {
            energy.currentEnergyStorage = 0;
        }
    });
}

} // namespace CTT