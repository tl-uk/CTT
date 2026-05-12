#include "SimulationEngine.hpp"
#include <iostream>

namespace CTT {

SimulationEngine::SimulationEngine() {
    // v4: 'monitor' renamed to 'stats'
    world.import<flecs::stats>();
    
#ifdef FLECS_REST
    // flecs::rest is a namespace — use the C macro for import
    ECS_IMPORT(world.c_ptr(), FlecsRest);
    
    // EcsRest is the C struct for configuration (works in v3 and v4)
    world.set<EcsRest>({ .port = 27750 });
    
    std::cout << "[L3 Core] REST API active on port 27750" << std::endl;
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
    
    // --- SYSTEM 1: SCHMITT TRIGGER (HDS Cognitive Logic) ---
    // v4: .iter() removed → use .run() with while(it.next())
    // v4: field indices start at 0 (not 1)
    world.system<MindsetComponent>("SchmittTriggerSystem")
        .kind(flecs::PreUpdate) 
        .run([](flecs::iter& it) {
            while (it.next()) {
                auto m = it.field<MindsetComponent>(0);
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
            }
        });

    // --- SYSTEM 2: ENERGY CONSUMPTION (Reflexive Muscle) ---
    // v4: .iter() removed → use .run() with while(it.next())
    // v4: field indices start at 0 (not 1)
    world.system<KinematicComponent, EnergyComponent, const PayloadComponent>("EnergyConsumptionSystem")
        .with<MicroActive>()
        .run([](flecs::iter& it) {
            while (it.next()) {
                auto kin = it.field<KinematicComponent>(0);
                auto energy = it.field<EnergyComponent>(1);
                auto payload = it.field<const PayloadComponent>(2);
                
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
            15.0,   // habit_resistance
            2.0,    // satisfaction
            10.0,   // high_threshold
            5.0,    // low_threshold
            false   // is_decarbonized
        });

    std::cout << "[L3 Core] Test fleet initialized with HDS Mindset models." << std::endl;
}

} // namespace CTT