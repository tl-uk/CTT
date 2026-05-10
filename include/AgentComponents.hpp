#pragma once
#include <string>
#include <cstdint>

namespace CTT {

    /**
     * @enum TransportMode
     * @brief High-level taxonomy of the vehicle's operational domain.
     * Aligned with Transport Data Ontology (TDO) to separate motorized, active, and depot transport.
     */
    enum class TransportMode { 
        ROAD_MOTORIZED,  ///< Cars, Vans, HGVs, Buses
        ROAD_ACTIVE,     ///< Bicycles, Cargo Bikes, e-Scooters (Micro-mobility)
        PEDESTRIAN,      ///< Walking (Passengers or Last-Mile Couriers)
        RAIL,            ///< Trains, Trams, Subway
        MARITIME,        ///< Ferries, Cargo Ships
        AIR,             ///< Planes, Drones
        DEPOT_HANDLING   ///< Forklifts, Terminal Tractors 
    };

    /**
     * @enum CargoType
     * @brief Functional payload categorization.
     */
    enum class CargoType { 
        PASSENGER, LIQUID_BULK, DRY_BULK, REFRIGERATED, PALLETISED, MIXED 
    };

    /**
     * @enum PowertrainType
     * @brief Energy source determining the carbon intensity of the agent.
     */
    enum class PowertrainType { 
        ICE_DIESEL, ICE_PETROL, BEV_ELECTRIC, FCEV_HYDROGEN, HYBRID 
    };

    /**
     * @struct PositionComponent
     * @brief Spatial location of the agent in the physical world.
     */
    struct PositionComponent {
        double latitude;
        double longitude;
        float elevation; ///< Crucial for energy calculations (hill climbs)
    };

    /**
     * @struct TaxonomyComponent
     * @brief Operational characteristics based on UK CAM and Transmodel standards.
     */
    struct TaxonomyComponent {
        TransportMode mode;
        uint8_t automationLevel; ///< SAE Levels 0-5
        bool isEmergency;        ///< High priority routing flag
    };

    /**
     * @struct PayloadComponent
     * @brief Tracks the current physical load against maximum capacity.
     */
    struct PayloadComponent {
        CargoType type;
        float currentLoadKg;
        float maxCapacityKg; ///< Gross Vehicle Weight (GVW) or Deadweight Tonnage (DWT)
        int passengerCount;
        int maxPassengers;
    };

    /**
     * @struct EnergyComponent
     * @brief Core physics component for Decarbonization and grid load simulation.
     */
    struct EnergyComponent {
        PowertrainType engineType;
        float currentEnergyStorage; ///< kWh for batteries, Liters for ICE
        float maxEnergyStorage;
        float baseEfficiency;       ///< Energy consumed per unit distance at baseline load
    };

    /**
     * @struct KinematicComponent
     * @brief Movement vectors.
     */
    struct KinematicComponent {
        float speed_mps; ///< Velocity in meters per second
        float heading;   ///< Direction of travel in degrees
    };

    /**
     * @struct MindsetComponent
     * @brief L3 Cognitive linkage: Adversarial BDI triggers.
     */
    struct MindsetComponent {
        double habit_resistance;  ///< H: Pull toward legacy ICE driving
        double satisfaction;      ///< S: Quality of experience
        bool is_decarbonized;     ///< Binary state of the Schmitt Trigger
    };

    /**
     * @struct CLD_FeedbackComponent
     * @brief Links the individual agent to macro-economic systems and national databases.
     */
    struct CLD_FeedbackComponent {
        double grid_load_impact;   ///< Energy consumption data sent to Python
        double air_quality_impact; ///< Localized NO2/Particulate emission data
        std::string hub_id;        ///< DfT NaPTAN ID (e.g., "9100WAVRLY")
    };

} // namespace CTT