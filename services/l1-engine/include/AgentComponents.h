// services/l1-engine/include/AgentComponents.h
/**
 * @file AgentComponents.hpp
 * @brief Data structures, enumerations, and tags for the Cognitive Transit Twin (CTT).
 * * This file defines the core components used by the Flecs ECS.
 * Includes LOD tags, taxonomies aligned with UK CAM standards, and cognitive linkages.
 */

#pragma once
#include <string>
#include <cstdint>

namespace CTT {

    // ========================================================================
    // --- L1 Multi-Scale Tags (Level of Detail) ---
    // ========================================================================

    /** @struct MicroActive @brief High-fidelity physics simulation tag. */
    struct MicroActive {};

    /** @struct MacroActive @brief Abstracted statistical flow simulation tag. */
    struct MacroActive {};

    /** @struct OneShotSuccess @brief Event tag for SSN decarbonization milestones. */
    struct OneShotSuccess {};


    // ========================================================================
    // --- ENUMS (Ontology & Taxonomy) ---
    // ========================================================================

    /**
     * @enum TransportMode
     * @brief Taxonomy of the vehicle's operational domain.
     */
    enum class TransportMode { 
        ROAD_MOTORIZED,  ///< Cars, Vans, HGVs, Buses
        ROAD_ACTIVE,     ///< Bicycles, Cargo Bikes, e-Scooters
        PEDESTRIAN,      ///< Walking
        RAIL,            ///< Trains, Trams, Subway
        MARITIME,        ///< Ferries, Cargo Ships
        AIR,             ///< Planes, Drones
        DEPOT_HANDLING   ///< Forklifts, Terminal Tractors 
    };

    /** @enum CargoType @brief Payload categorization. */
    enum class CargoType { 
        PASSENGER, LIQUID_BULK, DRY_BULK, REFRIGERATED, PALLETISED, MIXED 
    };

    /** @enum PowertrainType @brief Energy source for carbon intensity tracking. */
    enum class PowertrainType { 
        ICE_DIESEL, ICE_PETROL, BEV_ELECTRIC, FCEV_HYDROGEN, HYBRID 
    };


    // ========================================================================
    // --- COMPONENTS (Data Pods) ---
    // ========================================================================

    /** @struct PositionComponent @brief WGS84 spatial coordinates. */
    struct PositionComponent {
        double latitude;   ///< Latitude
        double longitude;  ///< Longitude
        float elevation;   ///< Meters above sea level
    };

    /**
     * @struct TaxonomyComponent
     * @brief Operational characteristics based on SAE/DfT standards.
     */
    struct TaxonomyComponent {
        TransportMode mode;      ///< Base transport domain
        uint8_t automationLevel; ///< SAE Level 0-5
        bool isEmergency;        ///< Priority routing flag
    }; // <--- FIXED: Added missing closing brace and semicolon

    /** @struct PayloadComponent @brief Physical load tracking. */
    struct PayloadComponent {
        CargoType type;          ///< Cargo category
        float currentLoadKg;     ///< Current weight
        float maxCapacityKg;     ///< Max GVW
        int passengerCount;      ///< Current humans
        int maxPassengers;       ///< Max capacity
    };

    /** @struct EnergyComponent @brief Core physics for battery/fuel drain. */
    struct EnergyComponent {
        PowertrainType engineType;    ///< Engine architecture
        float currentEnergyStorage;   ///< kWh or Liters
        float maxEnergyStorage;       ///< Total capacity
        float baseEfficiency;         ///< Energy/km at baseline
    };

    /** @struct KinematicComponent @brief Movement vectors. */
    struct KinematicComponent {
        float speed_mps; ///< Meters per second
        float heading;   ///< 0-360 degrees
    };

    /** @struct MindsetComponent @brief L3 Cognitive BDI linkage. */
    struct MindsetComponent {
        // 1. The Continuous Dynamic (The Input Signal)
        double adversarial_pressure; ///< Calculated from Energy + ROI

        // 2. Behavioral Modifiers
        double habit_resistance;  ///< (H) Pull toward legacy behavior
        double satisfaction;      ///< (S) Boosted by SSN One-Shot Successes

        // 3. Hysteresis Thresholds (The Schmitt Trigger points)
        double high_threshold;    ///< Switch to EV
        double low_threshold;     ///< Revert to ICE

        // 4. Jitter — prevents thundering-herd synchronisation
        double threshold_jitter;  ///< Uniform [0.95, 1.05] multiplier

        // 5. The Discrete State (The Output)
        bool is_decarbonized;     ///< True if currently in a low-carbon state (e.g., BEV or FCEV)
    };

    // Tags for Layer 5 Events
    struct MindsetShiftEvent {};
    struct MindsetRegressionEvent {};

    /** @struct ROI_Component @brief Economic/Social viability. */
    struct ROI_Component {
        double financial_cost;    ///< TCO in GBP
        double social_capital;    ///< Intangible value
        double personal_roi;      ///< Perceived return
    };

    /** @struct CLD_FeedbackComponent @brief L5 System Dynamics linkage. */
    struct CLD_FeedbackComponent {
        double grid_load_impact;   ///< kW draw
        double air_quality_impact; ///< NO2/PM emissions
        std::string hub_id;        ///< NaPTAN Hub ID
    };

    /** @struct ExternalitiesComponent @brief First-class non-transport effects (CO₂, NOₓ, noise, PM2.5). */
    struct ExternalitiesComponent {
        // Baseline emission factors (g/km at reference speed 50 km/h)
        float baseline_co2_g_km;
        float baseline_nox_g_km;
        float baseline_pm25_g_km;
        float baseline_noise_db;

        // Idling emission rates (g/s when speed ≈ 0) — terminal gates, congestion queues
        float idling_co2_g_s;
        float idling_nox_g_s;

        // Current computed rates (updated by ECS system each tick)
        float current_co2_g_km;
        float current_nox_g_km;
        float current_pm25_g_km;
        float current_noise_db;

        // Accumulated lifetime emissions (kg)
        float cumulative_co2_kg;
        float cumulative_nox_kg;
        float cumulative_pm25_kg;
    };

    /** @struct SocialImpactComponent @brief Equity, accessibility, and economic dependency. */
    struct SocialImpactComponent {
        float accessibility_score;     ///< 0.0–1.0 (higher = more accessible to vulnerable groups)
        int jobs_dependent;            ///< FTE jobs structurally dependent on this agent/route
        float deprivation_index;       ///< Index of Multiple Deprivation (IMD) for current location (0–100)
        float equity_exposure;         ///< 0.0–1.0 policy-change exposure for deprived populations
        bool serves_deprived_ward;     ///< True if current corridor/terminal serves IMD Q1–Q2 area
        std::string corridor_id;         ///< Spatial scope identifier (e.g., "pod_hinterland", "a20_charging")
    };


} // namespace CTT