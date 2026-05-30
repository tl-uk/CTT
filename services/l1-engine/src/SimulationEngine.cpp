// services/l1-engine/src/SimulationEngine.cpp
#include "SimulationEngine.h"
#include <iostream>
#include <random>
#include <cmath>
#include <cstdlib>  // for std::getenv

namespace CTT {

SimulationEngine::SimulationEngine() {
    world.import<flecs::stats>();

#ifdef FLECS_REST
    // Phase 6.5: REST is opt-in via env var to avoid progress() stalls
    const char* enable_rest = std::getenv("CTT_ENABLE_REST");
    if (enable_rest && std::string(enable_rest) == "1") {
        ECS_IMPORT(world.c_ptr(), FlecsRest);
        world.set<EcsRest>({ .port = 27750 });
        std::cout << "[L3 Core] REST API active on port 27750" << std::endl;
    }
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

    // --- SYSTEM 1: MARKET PRESSURE (Strategic L3 Influence) ---
    // MUST run in PreUpdate so the tax ramp feeds the trigger in the same tick.
    world.system<MindsetComponent>("MarketPressureSystem")
        .kind(flecs::PreUpdate)
        .each([](flecs::iter& it, size_t i, MindsetComponent& m) {
            const float tax_ramp_rate = 1.2f; 
            if (!m.is_decarbonized) {
                m.adversarial_pressure += tax_ramp_rate * it.delta_time();
            }
        });

    // --- SYSTEM 2: SCHMITT TRIGGER (HDS Cognitive Logic) ---
    // Runs in PreUpdate, after MarketPressureSystem, using jittered thresholds.
    // Phase 6.5: Single-line logging to reduce Docker stdout pressure.
    world.system<MindsetComponent>("SchmittTriggerSystem")
        .kind(flecs::PreUpdate) 
        .each([](flecs::iter& it, size_t i, MindsetComponent& m) {
            auto entity = it.entity(i);

            // Apply per-agent jitter to prevent thundering-herd
            double effective_high = (m.high_threshold + m.habit_resistance) * m.threshold_jitter;
            double effective_low  = (m.low_threshold - m.satisfaction) * m.threshold_jitter;

            if (!m.is_decarbonized) {
                if (m.adversarial_pressure >= effective_high) {
                    m.is_decarbonized = true;
                    std::cout << "[L3] " << entity.name() 
                              << " -> GREEN (thr=" << effective_high << ")" << std::endl;
                }
            } else {
                if (m.adversarial_pressure <= effective_low) {
                    m.is_decarbonized = false;
                    std::cout << "[L3] " << entity.name() 
                              << " -> LEGACY (thr=" << effective_low << ")" << std::endl;
                }
            }
        });

    // --- SYSTEM 3: ENERGY CONSUMPTION (Reflexive Muscle) ---
    // Physics — runs in OnUpdate, after all PreUpdate decisions.
    world.system<KinematicComponent, EnergyComponent, const PayloadComponent>("EnergyConsumptionSystem")
        .with<MicroActive>()
        .kind(flecs::OnUpdate)
        .each([](flecs::iter& it, size_t i, 
                 KinematicComponent& kin, 
                 EnergyComponent& energy, 
                 const PayloadComponent& payload) {

            float load_multiplier = 1.0f;
            if (payload.maxCapacityKg > 0) {
                load_multiplier += (payload.currentLoadKg / payload.maxCapacityKg);
            }

            float consumption = energy.baseEfficiency * (kin.speed_mps / 10.0f) 
                              * load_multiplier * it.delta_time();
            energy.currentEnergyStorage -= consumption;

            if (energy.currentEnergyStorage < 0) energy.currentEnergyStorage = 0;
        });

    // --- SYSTEM 4: KINEMATICS UPDATE (Simple motion model) ---
    // Physics — runs in OnUpdate.
    world.system<PositionComponent, const KinematicComponent>("KinematicsUpdateSystem")
        .kind(flecs::OnUpdate)
        .each([](flecs::iter& it, size_t i, 
                 PositionComponent& pos, 
                 const KinematicComponent& kin) {
            float dt = it.delta_time();
            pos.latitude  += (kin.speed_mps * std::sin(kin.heading * 3.14159f / 180.0f) * dt) / 111320.0f;
            pos.longitude += (kin.speed_mps * std::cos(kin.heading * 3.14159f / 180.0f) * dt) / (111320.0f * std::cos(pos.latitude * 3.14159f / 180.0f));
        });
}

// ---------------------------------------------------------------------------
// Fleet Data
// ---------------------------------------------------------------------------

struct FleetTemplate {
    const char* name;
    TransportMode mode;
    PowertrainType engine;
    float maxEnergy;
    float baseEff;
    float maxLoad;
    float speed;
    float lat;
    float lon;
    float habit;
    float satisfaction;
    float high_thr;
    float low_thr;
};

static const FleetTemplate FLEET_TEMPLATES[] = {
    // HGVs — Long haul, high capacity
    {"Volvo_eHGV_001",   TransportMode::ROAD_MOTORIZED, PowertrainType::BEV_ELECTRIC, 600.0f, 1.5f, 40000.0f, 22.0f, 55.9533f, -3.1883f, 15.0f, 2.0f, 10.0f, 5.0f},
    {"Scania_eHGV_002",  TransportMode::ROAD_MOTORIZED, PowertrainType::BEV_ELECTRIC, 650.0f, 1.4f, 44000.0f, 24.0f, 51.5074f, -0.1278f,  14.0f, 2.5f, 11.0f, 5.5f},
    {"DAF_XF_HGV_003",   TransportMode::ROAD_MOTORIZED, PowertrainType::ICE_DIESEL,     800.0f, 2.2f, 42000.0f, 25.0f, 53.4808f, -2.2426f,  18.0f, 1.0f, 12.0f, 6.0f},
    {"MAN_TGX_HGV_004",  TransportMode::ROAD_MOTORIZED, PowertrainType::FCEV_HYDROGEN,  700.0f, 1.6f, 40000.0f, 23.0f, 52.5200f, -1.8900f,  16.0f, 1.5f, 10.5f, 5.0f},
    {"Renault_ETech_005",TransportMode::ROAD_MOTORIZED, PowertrainType::BEV_ELECTRIC, 550.0f, 1.3f, 38000.0f, 20.0f, 54.9783f, -1.6178f,  13.0f, 3.0f, 9.0f,  4.5f},

    // Vans — Urban delivery
    {"Ford_ETransit_006",TransportMode::ROAD_MOTORIZED, PowertrainType::BEV_ELECTRIC,  68.0f, 0.25f, 3500.0f, 12.0f, 51.4543f, -2.5879f,  8.0f,  4.0f, 7.0f,  3.5f},
    {"Merc_eSprinter_007",TransportMode::ROAD_MOTORIZED,PowertrainType::BEV_ELECTRIC,  90.0f, 0.22f, 3500.0f, 11.0f, 51.7520f, -1.2577f,  9.0f,  3.5f, 7.5f, 3.8f},
    {"Vauxhall_Movano_008",TransportMode::ROAD_MOTORIZED,PowertrainType::ICE_DIESEL,   80.0f, 0.35f, 4500.0f, 13.0f, 50.8225f, -0.1372f,  10.0f, 2.0f, 8.0f,  4.0f},

    // Rail — Intermodal
    {"Class_66_Freight_009", TransportMode::RAIL, PowertrainType::ICE_DIESEL,  3000.0f, 0.8f, 3000000.0f, 27.0f, 53.4106f, -1.4600f, 20.0f, 1.0f, 15.0f, 7.0f},
    {"Class_88_BiMode_010",  TransportMode::RAIL, PowertrainType::HYBRID,      2500.0f, 0.7f, 2500000.0f, 30.0f, 54.9100f, -1.5800f, 18.0f, 1.5f, 14.0f, 6.5f},
    {"Class_323_EMU_011",    TransportMode::RAIL, PowertrainType::BEV_ELECTRIC, 1500.0f, 0.5f,  500000.0f, 35.0f, 52.4500f, -1.7300f, 12.0f, 3.0f, 8.0f,  4.0f},

    // Maritime — Short-sea / ferry
    {"Stena_Freight_012",  TransportMode::MARITIME, PowertrainType::ICE_DIESEL,  50000.0f, 5.0f, 50000000.0f, 15.0f, 54.6400f, -5.5400f, 22.0f, 0.5f, 18.0f, 9.0f},
    {"P&O_Hybrid_Ferry_013",TransportMode::MARITIME, PowertrainType::HYBRID,     40000.0f, 4.5f, 40000000.0f, 16.0f, 53.3500f, -3.0000f, 19.0f, 1.0f, 16.0f, 8.0f},

    // Active travel / cargo bikes
    {"PedalMe_Cargo_014",  TransportMode::ROAD_ACTIVE, PowertrainType::BEV_ELECTRIC,  1.5f, 0.02f, 150.0f, 5.0f, 51.5200f, -0.0900f, 5.0f, 5.0f, 4.0f, 2.0f},
    {"Brompton_Cargo_015", TransportMode::ROAD_ACTIVE, PowertrainType::BEV_ELECTRIC,  0.8f, 0.015f, 100.0f, 4.0f, 51.4900f, -0.1800f, 4.5f, 5.5f, 3.5f, 1.8f},

    // Aviation — Air cargo / drones
    {"DHL_CargoDrone_016", TransportMode::AIR, PowertrainType::BEV_ELECTRIC,  10.0f, 0.05f, 50.0f, 25.0f, 51.4700f, -0.4600f, 6.0f, 4.0f, 5.0f, 2.5f},
    {"RoyalMail_Drone_017",TransportMode::AIR, PowertrainType::BEV_ELECTRIC,   8.0f, 0.04f, 30.0f, 20.0f, 55.9500f, -3.3700f, 7.0f, 3.5f, 6.0f, 3.0f},

    // Depot handling
    {"Linde_EFork_018",    TransportMode::DEPOT_HANDLING, PowertrainType::BEV_ELECTRIC,  40.0f, 0.1f, 8000.0f, 3.0f, 51.4800f, -0.4500f, 3.0f, 6.0f, 2.5f, 1.5f},
    {"JCB_Hydrogen_019",   TransportMode::DEPOT_HANDLING, PowertrainType::FCEV_HYDROGEN,  60.0f, 0.12f, 10000.0f, 3.5f, 52.4800f, -1.6800f, 4.0f, 5.0f, 3.0f, 1.8f},

    // More HGVs for density
    {"Mercedes_Actros_020",TransportMode::ROAD_MOTORIZED, PowertrainType::ICE_DIESEL,  750.0f, 2.0f, 41000.0f, 24.0f, 51.2800f,  0.1200f, 17.0f, 1.2f, 11.5f, 5.8f},
    {"Iveco_SWay_021",     TransportMode::ROAD_MOTORIZED, PowertrainType::FCEV_HYDROGEN,  620.0f, 1.7f, 39000.0f, 22.5f, 50.9000f, -1.4000f, 15.5f, 1.8f, 10.0f, 5.2f},
    {"Volvo_FL_Elec_022",  TransportMode::ROAD_MOTORIZED, PowertrainType::BEV_ELECTRIC,  300.0f, 0.9f, 16000.0f, 18.0f, 53.8000f, -1.5500f, 11.0f, 2.8f, 8.5f, 4.2f},
    {"Nissan_eNV200_023",  TransportMode::ROAD_MOTORIZED, PowertrainType::BEV_ELECTRIC,   40.0f, 0.18f, 2000.0f, 10.0f, 52.4100f, -1.5100f, 7.5f, 3.8f, 6.5f, 3.2f},
    {"Tesla_Semi_024",     TransportMode::ROAD_MOTORIZED, PowertrainType::BEV_ELECTRIC, 1000.0f, 1.2f,  37000.0f, 28.0f, 55.8600f, -4.2500f, 14.0f, 2.2f, 9.5f, 4.8f},
    {"BYD_8TT_025",        TransportMode::ROAD_MOTORIZED, PowertrainType::BEV_ELECTRIC,  420.0f, 1.1f,  36000.0f, 19.0f, 51.3800f, -2.3600f, 12.5f, 2.5f, 8.0f, 4.0f},
};

static constexpr size_t FLEET_SIZE = sizeof(FLEET_TEMPLATES) / sizeof(FleetTemplate);

void SimulationEngine::initialize_test_fleet() {
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_real_distribution<float> heading_dist(0.0f, 360.0f);
    std::uniform_real_distribution<float> load_dist(0.3f, 0.95f);
    std::uniform_int_distribution<int> pax_dist(0, 2);
    // NEW: ±5% jitter to break thundering-herd synchronisation
    std::uniform_real_distribution<float> jitter_dist(0.95f, 1.05f);

    for (size_t i = 0; i < FLEET_SIZE; ++i) {
        const auto& t = FLEET_TEMPLATES[i];
        auto e = world.entity(t.name);

        e.add<MicroActive>();

        uint8_t sae_level = (t.mode == TransportMode::RAIL || t.mode == TransportMode::AIR) 
                            ? static_cast<uint8_t>(3) : static_cast<uint8_t>(2);

        e.set(TaxonomyComponent{t.mode, sae_level, false});

        float current_load = t.maxLoad * load_dist(gen);
        int pax = (t.mode == TransportMode::ROAD_MOTORIZED || t.mode == TransportMode::ROAD_ACTIVE) 
                  ? pax_dist(gen) : 0;

        e.set(PayloadComponent{
            CargoType::PALLETISED, 
            current_load, 
            t.maxLoad, 
            pax, 
            (t.mode == TransportMode::ROAD_MOTORIZED ? 2 : 0)
        });

        e.set(EnergyComponent{
            t.engine, 
            t.maxEnergy, 
            t.maxEnergy, 
            t.baseEff
        });

        e.set(KinematicComponent{
            t.speed, 
            heading_dist(gen)
        });

        e.set(PositionComponent{
            t.lat, 
            t.lon, 
            50.0f
        });

        e.set(MindsetComponent{
            0.0,           // adversarial_pressure (starts at 0)
            t.habit,       // habit_resistance
            t.satisfaction,// satisfaction
            t.high_thr,    // high_threshold
            t.low_thr,     // low_threshold
            jitter_dist(gen), // threshold_jitter — unique per agent
            false          // is_decarbonized
        });
    }

    std::cout << "[L3 Core] Fleet initialized: " << FLEET_SIZE 
              << " agents with HDS Mindset models (±5% jitter)." << std::endl;
}

void CTT::SimulationEngine::register_reflection() {
    world.component<MindsetComponent>()
        .member<double>("adversarial_pressure")
        .member<double>("habit_resistance")
        .member<double>("satisfaction")
        .member<double>("high_threshold")
        .member<double>("low_threshold")
        .member<double>("threshold_jitter")  // NEW
        .member<bool>("is_decarbonized");

    world.component<EnergyComponent>()
        .member<float>("currentEnergyStorage")
        .member<float>("maxEnergyStorage")
        .member<float>("baseEfficiency");

    world.component<KinematicComponent>()
        .member<float>("speed_mps")
        .member<float>("heading");

    world.component<PositionComponent>()
        .member<double>("latitude")
        .member<double>("longitude")
        .member<float>("elevation");

    world.component<TaxonomyComponent>()
        .member<int>("mode")
        .member<uint8_t>("automationLevel")
        .member<bool>("isEmergency");
}

} // namespace CTT