#include "SimulationEngine.hpp"
#include <iostream>

namespace CTT {

SimulationEngine::SimulationEngine() {
    // 1. Core Modules
    world.import<flecs::monitor>();
    
    // 2. REST API Configuration [cite: 10]
    // Note: In Flecs v3.2+, simply setting the flecs::Rest component 
    // automatically imports the module and starts the server on port 27750.
#if defined(FLECS_REST) || defined(flecs_rest_EXPORTS)
    world.set<flecs::Rest>({}); 
    std::cout << "[L3 Core] Flecs REST API/Explorer active on port 27750" << std::endl;
#else
    std::cout << "[L3 Core] Warning: REST module not detected. Explorer disabled." << std::endl;
#endif

    // 3. Register our "Muscle" and "Cognition" systems
    register_systems();
}

flecs::world& SimulationEngine::get_world() {
    return world;
}

void SimulationEngine::update(float delta_time) {
    world.progress(delta_time);
}

void SimulationEngine::register_systems() {
    
    // --- SYSTEM 1: SCHMITT TRIGGER (Cognitive HDS) ---
    // Evaluates adversarial pressure against habit resistance thresholds.
    world.system<MindsetComponent>("SchmittTriggerSystem")
        .kind(flecs::PreUpdate) // Ensure mindset state is set before physics calcs
        .iter([](flecs::iter& it, MindsetComponent* m) {
            for (auto i : it) {
                auto entity = it.entity(i);

                // HDS Coupling: Dynamic thresholds influenced by Habit (H) and Satisfaction (S)
                double effective_high = m[i].high_threshold + m[i].habit_resistance;
                double effective_low = m[i].low_threshold - m[i].satisfaction;

                // State Transition Logic (The "Latch")
                if (!m[i].is_decarbonized) {
                    if (m[i].adversarial_pressure >= effective_high) {
                        m[i].is_decarbonized = true;
                        entity.add<MindsetShiftEvent>(); // Broadcast to Layer 5 [cite: 7]
                        std::cout << "[L3] Agent " << entity.name() << " crossed High Threshold -> Green." << std::endl;
                    }
                } else {
                    if (m[i].adversarial_pressure <= effective_low) {
                        m[i].is_decarbonized = false;
                        entity.add<MindsetRegressionEvent>();
                        std::cout << "[L3] Agent " << entity.name() << " dropped below Low Threshold -> Legacy." << std::endl;
                    }
                }
            }
        });

    // --- SYSTEM 2: ENERGY CONSUMPTION (Reflexive Muscle) ---
    // Calculates energy drain based on speed, load, and powertrain efficiency.
    world.system<KinematicComponent, EnergyComponent, const PayloadComponent>("EnergyConsumptionSystem")
        .with<MicroActive>()
        .iter([](flecs::iter& it, KinematicComponent* kin, EnergyComponent* energy, const PayloadComponent* payload) {
            for (auto i : it) {
                float load_multiplier = 1.0f;
                if (payload[i].maxCapacityKg > 0) {
                    load_multiplier += (payload[i].currentLoadKg / payload[i].maxCapacityKg);
                }

                // Standard physics-based consumption
                float consumption = energy[i].baseEfficiency * (kin[i].speed_mps / 10.0f) * load_multiplier * it.delta_time();
                energy[i].currentEnergyStorage -= consumption;
                
                if (energy[i].currentEnergyStorage < 0) energy[i].currentEnergyStorage = 0;
            }
        });
}

void SimulationEngine::initialize_test_fleet() {
    // Creating an eHGV with both Reflexive (Energy) and Cognitive (Mindset) properties
    world.entity("Volvo_eHGV_001")
        .add<MicroActive>()
        .set<TaxonomyComponent>({TransportMode::ROAD_MOTORIZED, 2, false})
        .set<PayloadComponent>({CargoType::PALLETISED, 15000.0f, 40000.0f, 1, 2})
        .set<EnergyComponent>({PowertrainType::BEV_ELECTRIC, 600.0f, 600.0f, 1.5f})
        .set<KinematicComponent>({22.0f, 90.0f})
        .set<PositionComponent>({55.9533, -3.1883, 50.0f})
        .set<MindsetComponent>({
            0.0,    // adversarial_pressure
            15.0,   // habit_resistance (H)
            2.0,    // satisfaction (S)
            10.0,   // high_threshold
            5.0,    // low_threshold
            false   // is_decarbonized
        });

    std::cout << "[L3 Core] Test fleet initialized with HDS Mindset models." << std::endl;
}

} // namespace CTT