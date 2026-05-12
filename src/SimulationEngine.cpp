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

    register_reflection();
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
    // v4: .each() with (iter, index, component&) signature is idiomatic
    world.system<MindsetComponent>("SchmittTriggerSystem")
        .kind(flecs::PreUpdate) 
        .each([](flecs::iter& it, size_t i, MindsetComponent& m) {
            auto entity = it.entity(i);
            
            // HDS Math: Calculate thresholds influenced by behavior
            double effective_high = m.high_threshold + m.habit_resistance;
            double effective_low = m.low_threshold - m.satisfaction;

            // State Transition Latch
            if (!m.is_decarbonized) {
                if (m.adversarial_pressure >= effective_high) {
                    m.is_decarbonized = true;
                    std::cout << "[L3] Agent " << entity.name() << " switched to GREEN." << std::endl;
                }
            } else {
                if (m.adversarial_pressure <= effective_low) {
                    m.is_decarbonized = false;
                    std::cout << "[L3] Agent " << entity.name() << " regressed to LEGACY." << std::endl;
                }
            }
        });

    // --- SYSTEM 2: ENERGY CONSUMPTION (Reflexive Muscle) ---
    // v4: .each() cleanly provides all components by reference
    world.system<KinematicComponent, EnergyComponent, const PayloadComponent>("EnergyConsumptionSystem")
        .with<MicroActive>()
        .each([](flecs::iter& it, size_t i, 
                 KinematicComponent& kin, 
                 EnergyComponent& energy, 
                 const PayloadComponent& payload) {
            
            float load_multiplier = 1.0f;
            if (payload.maxCapacityKg > 0) {
                load_multiplier += (payload.currentLoadKg / payload.maxCapacityKg);
            }

            // Consumption math based on speed and load
            float consumption = energy.baseEfficiency * (kin.speed_mps / 10.0f) * load_multiplier * it.delta_time();
            energy.currentEnergyStorage -= consumption;
            
            if (energy.currentEnergyStorage < 0) energy.currentEnergyStorage = 0;
        });

    // --- SYSTEM 3: MARKET PRESSURE (Strategic L3 Influence) ---
    // v4: .each() is the cleanest approach for per-entity updates
    world.system<MindsetComponent>("MarketPressureSystem")
        .each([](flecs::iter& it, size_t i, MindsetComponent& m) {
            // Rate of pressure increase (units per second)
            const float tax_ramp_rate = 1.2f; 

            // Cognitive HDS Logic: Only ramp pressure if agent is not yet decarbonized
            if (!m.is_decarbonized) {
                m.adversarial_pressure += tax_ramp_rate * it.delta_time();
            }
        });
}

void SimulationEngine::initialize_test_fleet() {
    auto e = world.entity("Volvo_eHGV_001");
    
    e.add<MicroActive>();
    
    // Explicit temporaries — compiler deduces T from the argument type
    e.set(TaxonomyComponent{TransportMode::ROAD_MOTORIZED, static_cast<uint8_t>(2), false});
    e.set(PayloadComponent{CargoType::PALLETISED, 15000.0f, 40000.0f, 1, 2});
    e.set(EnergyComponent{PowertrainType::BEV_ELECTRIC, 600.0f, 600.0f, 1.5f});
    e.set(KinematicComponent{22.0f, 90.0f});
    e.set(PositionComponent{55.9533, -3.1883, 50.0f});
    e.set(MindsetComponent{
        0.0,    // adversarial_pressure
        15.0,   // habit_resistance
        2.0,    // satisfaction
        10.0,   // high_threshold
        5.0,    // low_threshold
        false   // is_decarbonized
    });

    std::cout << "[L3 Core] Test fleet initialized with HDS Mindset models." << std::endl;
}

void CTT::SimulationEngine::register_reflection() {
    // This maps the C++ struct members so the web Explorer can display them
    world.component<MindsetComponent>()
        .member<double>("adversarial_pressure")
        .member<double>("habit_resistance")
        .member<double>("satisfaction")
        .member<double>("high_threshold")
        .member<double>("low_threshold")
        .member<bool>("is_decarbonized");

    world.component<EnergyComponent>()
        .member<float>("currentEnergyStorage")
        .member<float>("maxCapacity")
        .member<float>("baseEfficiency");
        
    world.component<KinematicComponent>()
        .member<float>("speed_mps")
        .member<float>("heading_deg");
}

} // namespace CTT