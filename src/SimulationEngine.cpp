#include "SimulationEngine.hpp"
#include <iostream>

namespace CTT {

SimulationEngine::SimulationEngine() {
    // 1. Core Modules
    world.import<flecs::monitor>();
    
    // 2. REST API Configuration [cite: 10]
    // Note: In Flecs v3.2+, simply setting the flecs::Rest component 
    // automatically imports the module and starts the server on port 27750.
#ifdef FLECS_REST
    // Use the Macro if the template is giving you namespace errors.
    // This resolves at the C-level and is immune to C++ namespace shadowing.
    ECS_IMPORT(world.c_ptr(), FlecsRest);

    // Set the port using the stable C struct
    world.set<EcsRest>({ .port = 27750 });

    std::cout << "[L3 Core] REST API active on port 27750" << std::endl;
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
    
    // --- SYSTEM 1: SCHMITT TRIGGER (HDS Cognitive Logic) ---
    // Evaluates adversarial pressure against habit resistance thresholds.
    world.system<MindsetComponent>("SchmittTriggerSystem") // This system manages the decarbonization state "latch"
        .kind(flecs::PreUpdate) 
        .iter([](flecs::iter& it, MindsetComponent* m) {
            for (auto i : it) {
                auto entity = it.entity(i);
                
                // HDS Math: Calculate thresholds influenced by behavior
                double effective_high = m[i].high_threshold + m[i].habit_resistance;
                double effective_low = m[i].low_threshold - m[i].satisfaction;

                // State Transition Latch
                if (!m[i].is_decarbonized) {
                    if (m[i].adversarial_pressure >= effective_high) {
                        m[i].is_decarbonized = true;
                        std::cout << "[L3] Agent " << entity.name() << " switched to GREEN." << std::endl;
                    }
                } else {
                    if (m[i].adversarial_pressure <= effective_low) {
                        m[i].is_decarbonized = false;
                        std::cout << "[L3] Agent " << entity.name() << " regressed to LEGACY." << std::endl;
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

                // Consumption math based on speed and load
                float consumption = energy[i].baseEfficiency * (kin[i].speed_mps / 10.0f) * load_multiplier * it.delta_time();
                energy[i].currentEnergyStorage -= consumption;
                
                if (energy[i].currentEnergyStorage < 0) energy[i].currentEnergyStorage = 0;
            }
        });
}

void SimulationEngine::initialize_test_fleet() {
    // Creating an eHGV with both Reflexive (Energy) and Cognitive (Mindset) properties
    world.entity("Volvo_eHGV_001") // Initializing the Volvo eHGV with full HDS Mindset data
        .add<MicroActive>()
        .set<TaxonomyComponent>({TransportMode::ROAD_MOTORIZED, 2, false})
        .set<PayloadComponent>({CargoType::PALLETISED, 15000.0f, 40000.0f, 1, 2})
        .set<EnergyComponent>({PowertrainType::BEV_ELECTRIC, 600.0f, 600.0f, 1.5f})
        .set<KinematicComponent>({22.0f, 90.0f})
        .set<PositionComponent>({55.9533, -3.1883, 50.0f})
        .set<MindsetComponent>({
            0.0,    // adversarial_pressure
            15.0,   // habit_resistance
            2.0,    // satisfaction
            10.0,   // high_threshold
            5.0,    // low_threshold
            false   // is_decarbonized
        });

    std::cout << "[L3 Core] Test fleet initialized with HDS Mindset models." << std::endl;
}

} // namespace CTT