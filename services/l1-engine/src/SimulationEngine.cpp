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

    // --- SYSTEM 5: EXTERNALITIES UPDATE (Phase 7) ---
    // Computes real-time emissions based on kinematics, energy, and powertrain.
    // Idling emissions (terminal gates, congestion) are computed separately.
    world.system<KinematicComponent, EnergyComponent, PayloadComponent, ExternalitiesComponent>()
        .kind(flecs::OnUpdate)
        .each([](flecs::iter& it, size_t i,
                 KinematicComponent& kin,
                 EnergyComponent& energy,
                 const PayloadComponent& payload,
                 ExternalitiesComponent& ext) {

            float speed_kmh = kin.speed_mps * 3.6f;
            bool is_idling = kin.speed_mps < 0.5f;
            float load_factor = 1.0f;
            if (payload.maxCapacityKg > 0.0f) {
                load_factor = 0.5f + 0.5f * (payload.currentLoadKg / payload.maxCapacityKg);
            }

            float dt_seconds = it.delta_time();
            float distance_km = (kin.speed_mps * dt_seconds) / 1000.0f;

            if (is_idling) {
                // Idling mode: terminal gates, traffic queues
                ext.current_co2_g_km = 0.0f;
                ext.current_nox_g_km = 0.0f;
                ext.current_pm25_g_km = 0.0f;
                ext.current_noise_db = ext.baseline_noise_db * 0.7f;

                ext.cumulative_co2_kg  += (ext.idling_co2_g_s * dt_seconds) / 1000.0f;
                ext.cumulative_nox_kg  += (ext.idling_nox_g_s * dt_seconds) / 1000.0f;
                ext.cumulative_pm25_kg += (ext.baseline_pm25_g_km * 0.1f * dt_seconds) / 1000.0f;
            } else {
                // Driving mode: U-curve emission profile (worse at very low and very high speed)
                float speed_factor = 1.0f;
                if (speed_kmh < 30.0f) speed_factor = 1.3f;
                else if (speed_kmh > 90.0f) speed_factor = 1.2f;

                ext.current_co2_g_km  = ext.baseline_co2_g_km * load_factor * speed_factor;
                ext.current_nox_g_km  = ext.baseline_nox_g_km * load_factor * speed_factor;
                ext.current_pm25_g_km = ext.baseline_pm25_g_km * load_factor * speed_factor;
                ext.current_noise_db  = ext.baseline_noise_db + 10.0f * std::log10(std::max(1.0f, speed_kmh / 50.0f));

                ext.cumulative_co2_kg  += (ext.current_co2_g_km * distance_km) / 1000.0f;
                ext.cumulative_nox_kg  += (ext.current_nox_g_km * distance_km) / 1000.0f;
                ext.cumulative_pm25_kg += (ext.current_pm25_g_km * distance_km) / 1000.0f;
            }
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
    // Phase 7 — Externality baselines (g/km, g/s, dB)
    float baseline_co2_g_km;
    float baseline_nox_g_km;
    float baseline_pm25_g_km;
    float baseline_noise_db;
    float idling_co2_g_s;
    float idling_nox_g_s;
    // Phase 7 — Social impact baselines
    float accessibility_score;
    int jobs_dependent;
    float deprivation_index;
    float equity_exposure;
    bool serves_deprived_ward;
    const char* corridor_id;
};

static const FleetTemplate FLEET_TEMPLATES[] = {
    // HGVs — Long haul, high capacity
    {"Volvo_eHGV_001", TransportMode::ROAD_MOTORIZED, PowertrainType::BEV_ELECTRIC, 600.0f, 1.5f, 40000.0f, 22.0f, 55.9533f, -3.1883f, 15.0f, 2.0f, 10.0f, 5.0f, 0.0f, 0.0f, 0.0f, 65.0f, 0.0f, 0.0f, 0.3f, 150, 42.0f, 0.18f, false, "m20_corridor"},
    {"Scania_eHGV_002", TransportMode::ROAD_MOTORIZED, PowertrainType::BEV_ELECTRIC, 650.0f, 1.4f, 44000.0f, 24.0f, 51.5074f, -0.1278f, 14.0f, 2.5f, 11.0f, 5.5f, 0.0f, 0.0f, 0.0f, 65.0f, 0.0f, 0.0f, 0.28f, 180, 38.0f, 0.15f, false, "m20_corridor"},
    {"DAF_XF_HGV_003", TransportMode::ROAD_MOTORIZED, PowertrainType::ICE_DIESEL, 800.0f, 2.2f, 42000.0f, 25.0f, 53.4808f, -2.2426f, 18.0f, 1.0f, 12.0f, 6.0f, 900.0f, 4.0f, 0.08f, 82.0f, 15.0f, 0.04f, 0.55f, 200, 46.0f, 0.55f, true, "a20_charging_corridor"},
    {"MAN_TGX_HGV_004", TransportMode::ROAD_MOTORIZED, PowertrainType::FCEV_HYDROGEN, 700.0f, 1.6f, 40000.0f, 23.0f, 52.52f, -1.89f, 16.0f, 1.5f, 10.5f, 5.0f, 0.0f, 0.0f, 0.0f, 70.0f, 0.0f, 0.0f, 0.25f, 160, 44.0f, 0.12f, false, "m20_corridor"},
    {"Renault_ETech_005", TransportMode::ROAD_MOTORIZED, PowertrainType::BEV_ELECTRIC, 550.0f, 1.3f, 38000.0f, 20.0f, 54.9783f, -1.6178f, 13.0f, 3.0f, 9.0f, 4.5f, 0.0f, 0.0f, 0.0f, 64.0f, 0.0f, 0.0f, 0.35f, 140, 48.0f, 0.22f, false, "pod_hinterland_corridor"},

    // Vans — Urban delivery
    {"Ford_ETransit_006", TransportMode::ROAD_MOTORIZED, PowertrainType::BEV_ELECTRIC, 68.0f, 0.25f, 3500.0f, 12.0f, 51.4543f, -2.5879f, 8.0f, 4.0f, 7.0f, 3.5f, 0.0f, 0.0f, 0.0f, 55.0f, 0.0f, 0.0f, 0.6f, 25, 45.0f, 0.42f, true, "a20_charging_corridor"},
    {"Merc_eSprinter_007", TransportMode::ROAD_MOTORIZED, PowertrainType::BEV_ELECTRIC, 90.0f, 0.22f, 3500.0f, 11.0f, 51.752f, -1.2577f, 9.0f, 3.5f, 7.5f, 3.8f, 0.0f, 0.0f, 0.0f, 54.0f, 0.0f, 0.0f, 0.62f, 30, 43.0f, 0.38f, true, "a20_charging_corridor"},
    {"Vauxhall_Movano_008", TransportMode::ROAD_MOTORIZED, PowertrainType::ICE_DIESEL, 80.0f, 0.35f, 4500.0f, 13.0f, 50.8225f, -0.1372f, 10.0f, 2.0f, 8.0f, 4.0f, 250.0f, 0.5f, 0.02f, 75.0f, 5.0f, 0.015f, 0.58f, 20, 47.0f, 0.58f, true, "a20_charging_corridor"},

    // Rail — Intermodal
    {"Class_66_Freight_009", TransportMode::RAIL, PowertrainType::ICE_DIESEL, 3000.0f, 0.8f, 3000000.0f, 27.0f, 53.4106f, -1.46f, 20.0f, 1.0f, 15.0f, 7.0f, 30.0f, 0.5f, 0.01f, 80.0f, 8.0f, 0.02f, 0.85f, 500, 35.0f, 0.1f, false, "m20_corridor"},
    {"Class_88_BiMode_010", TransportMode::RAIL, PowertrainType::HYBRID, 2500.0f, 0.7f, 2500000.0f, 30.0f, 54.91f, -1.58f, 18.0f, 1.5f, 14.0f, 6.5f, 15.0f, 0.25f, 0.005f, 78.0f, 4.0f, 0.01f, 0.88f, 450, 33.0f, 0.08f, false, "m20_corridor"},
    {"Class_323_EMU_011", TransportMode::RAIL, PowertrainType::BEV_ELECTRIC, 1500.0f, 0.5f, 500000.0f, 35.0f, 52.45f, -1.73f, 12.0f, 3.0f, 8.0f, 4.0f, 0.0f, 0.0f, 0.0f, 70.0f, 0.0f, 0.0f, 0.9f, 300, 30.0f, 0.05f, false, "national_rail"},

    // Maritime — Short-sea / ferry
    {"Stena_Freight_012", TransportMode::MARITIME, PowertrainType::ICE_DIESEL, 50000.0f, 5.0f, 50000000.0f, 15.0f, 54.64f, -5.54f, 22.0f, 0.5f, 18.0f, 9.0f, 15.0f, 0.3f, 0.005f, 90.0f, 20.0f, 0.05f, 0.4f, 800, 52.0f, 0.3f, false, "pod_terminal"},
    {"P&O_Hybrid_Ferry_013", TransportMode::MARITIME, PowertrainType::HYBRID, 40000.0f, 4.5f, 40000000.0f, 16.0f, 53.35f, -3.0f, 19.0f, 1.0f, 16.0f, 8.0f, 8.0f, 0.15f, 0.002f, 85.0f, 10.0f, 0.025f, 0.45f, 750, 50.0f, 0.25f, false, "pod_terminal"},

    // Active travel / cargo bikes
    {"PedalMe_Cargo_014", TransportMode::ROAD_ACTIVE, PowertrainType::BEV_ELECTRIC, 1.5f, 0.02f, 150.0f, 5.0f, 51.52f, -0.09f, 5.0f, 5.0f, 4.0f, 2.0f, 0.0f, 0.0f, 0.0f, 40.0f, 0.0f, 0.0f, 0.95f, 2, 44.0f, 0.35f, true, "a20_charging_corridor"},
    {"Brompton_Cargo_015", TransportMode::ROAD_ACTIVE, PowertrainType::BEV_ELECTRIC, 0.8f, 0.015f, 100.0f, 4.0f, 51.49f, -0.18f, 4.5f, 5.5f, 3.5f, 1.8f, 0.0f, 0.0f, 0.0f, 38.0f, 0.0f, 0.0f, 0.96f, 1, 46.0f, 0.4f, true, "a20_charging_corridor"},

    // Aviation — Air cargo / drones
    {"DHL_CargoDrone_016", TransportMode::AIR, PowertrainType::BEV_ELECTRIC, 10.0f, 0.05f, 50.0f, 25.0f, 51.47f, -0.46f, 6.0f, 4.0f, 5.0f, 2.5f, 0.0f, 0.0f, 0.0f, 60.0f, 0.0f, 0.0f, 0.4f, 5, 48.0f, 0.28f, false, "pod_hinterland_corridor"},
    {"RoyalMail_Drone_017", TransportMode::AIR, PowertrainType::BEV_ELECTRIC, 8.0f, 0.04f, 30.0f, 20.0f, 55.95f, -3.37f, 7.0f, 3.5f, 6.0f, 3.0f, 0.0f, 0.0f, 0.0f, 58.0f, 0.0f, 0.0f, 0.42f, 3, 36.0f, 0.18f, false, "national_distribution"},

    // Depot handling
    {"Linde_EFork_018", TransportMode::DEPOT_HANDLING, PowertrainType::BEV_ELECTRIC, 40.0f, 0.1f, 8000.0f, 3.0f, 51.48f, -0.45f, 3.0f, 6.0f, 2.5f, 1.5f, 0.0f, 0.0f, 0.0f, 55.0f, 0.0f, 0.0f, 0.35f, 15, 50.0f, 0.32f, false, "pod_terminal"},
    {"JCB_Hydrogen_019", TransportMode::DEPOT_HANDLING, PowertrainType::FCEV_HYDROGEN, 60.0f, 0.12f, 10000.0f, 3.5f, 52.48f, -1.68f, 4.0f, 5.0f, 3.0f, 1.8f, 0.0f, 0.0f, 0.0f, 58.0f, 0.0f, 0.0f, 0.32f, 12, 48.0f, 0.3f, false, "pod_terminal"},

    // More HGVs for density
    {"Mercedes_Actros_020", TransportMode::ROAD_MOTORIZED, PowertrainType::ICE_DIESEL, 750.0f, 2.0f, 41000.0f, 24.0f, 51.28f, 0.12f, 17.0f, 1.2f, 11.5f, 5.8f, 850.0f, 3.8f, 0.07f, 81.0f, 14.0f, 0.035f, 0.28f, 190, 40.0f, 0.32f, false, "m20_corridor"},
    {"Iveco_SWay_021", TransportMode::ROAD_MOTORIZED, PowertrainType::FCEV_HYDROGEN, 620.0f, 1.7f, 39000.0f, 22.5f, 50.9f, -1.4f, 15.5f, 1.8f, 10.0f, 5.2f, 0.0f, 0.0f, 0.0f, 68.0f, 0.0f, 0.0f, 0.26f, 170, 38.0f, 0.14f, false, "m20_corridor"},
    {"Volvo_FL_Elec_022", TransportMode::ROAD_MOTORIZED, PowertrainType::BEV_ELECTRIC, 300.0f, 0.9f, 16000.0f, 18.0f, 53.8f, -1.55f, 11.0f, 2.8f, 8.5f, 4.2f, 0.0f, 0.0f, 0.0f, 60.0f, 0.0f, 0.0f, 0.5f, 80, 44.0f, 0.28f, false, "a20_charging_corridor"},
    {"Nissan_eNV200_023", TransportMode::ROAD_MOTORIZED, PowertrainType::BEV_ELECTRIC, 40.0f, 0.18f, 2000.0f, 10.0f, 52.41f, -1.51f, 7.5f, 3.8f, 6.5f, 3.2f, 0.0f, 0.0f, 0.0f, 52.0f, 0.0f, 0.0f, 0.65f, 18, 46.0f, 0.4f, true, "a20_charging_corridor"},
    {"Tesla_Semi_024", TransportMode::ROAD_MOTORIZED, PowertrainType::BEV_ELECTRIC, 1000.0f, 1.2f, 37000.0f, 28.0f, 55.86f, -4.25f, 14.0f, 2.2f, 9.5f, 4.8f, 0.0f, 0.0f, 0.0f, 64.0f, 0.0f, 0.0f, 0.32f, 210, 41.0f, 0.16f, false, "m20_corridor"},
    {"BYD_8TT_025", TransportMode::ROAD_MOTORIZED, PowertrainType::BEV_ELECTRIC, 420.0f, 1.1f, 36000.0f, 19.0f, 51.38f, -2.36f, 12.5f, 2.5f, 8.0f, 4.0f, 0.0f, 0.0f, 0.0f, 63.0f, 0.0f, 0.0f, 0.38f, 155, 49.0f, 0.24f, false, "pod_hinterland_corridor"},
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

        e.set(ExternalitiesComponent{
            t.baseline_co2_g_km,
            t.baseline_nox_g_km,
            t.baseline_pm25_g_km,
            t.baseline_noise_db,
            t.idling_co2_g_s,
            t.idling_nox_g_s,
            0.0f, 0.0f, 0.0f, 0.0f,  // current values start at 0
            0.0f, 0.0f, 0.0f            // cumulative starts at 0
        });

        e.set(SocialImpactComponent{
            t.accessibility_score,
            t.jobs_dependent,
            t.deprivation_index,
            t.equity_exposure,
            t.serves_deprived_ward,
            std::string(t.corridor_id)
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

    world.component<ExternalitiesComponent>()
        .member<float>("baseline_co2_g_km")
        .member<float>("baseline_nox_g_km")
        .member<float>("baseline_pm25_g_km")
        .member<float>("baseline_noise_db")
        .member<float>("idling_co2_g_s")
        .member<float>("idling_nox_g_s")
        .member<float>("current_co2_g_km")
        .member<float>("current_nox_g_km")
        .member<float>("current_pm25_g_km")
        .member<float>("current_noise_db")
        .member<float>("cumulative_co2_kg")
        .member<float>("cumulative_nox_kg")
        .member<float>("cumulative_pm25_kg");

    world.component<SocialImpactComponent>()
        .member<float>("accessibility_score")
        .member<int>("jobs_dependent")
        .member<float>("deprivation_index")
        .member<float>("equity_exposure")
        .member<bool>("serves_deprived_ward")
        .member<std::string>("corridor_id");
}

} // namespace CTT