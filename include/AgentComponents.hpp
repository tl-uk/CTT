#pragma once
#include <string>

namespace CTT {
    // 3. The Psychological Engine (Adversarial BDI)
    struct MindsetComponent {
        double habit_resistance;  // H: Pull toward legacy ICE driving
        double satisfaction;      // S: Quality of public transport experience
        bool is_decarbonized;     // The binary state of the Schmitt Trigger
    };

    // ROI & Social Capital (The "Utility" calculation)
    struct ROI_Component {
        double financial_cost;    // Ticket/Fuel/Maintenance
        double social_capital;    // Influence from peers
        double personal_roi;      // Summed utility
    };

    // Macro Feedback (Gaia-X Link)
    struct CLD_FeedbackComponent {
        double grid_load_impact;  // Energy consumption data
        double air_quality_impact; // NO2 emission data
        std::string hub_id;       // Federated ID (e.g., "EDI-Waverley-01")
    };
}


// ==========================================
// 1. HIGH-LEVEL TAXONOMY & ONTOLOGY ENUMS
// Aligned with Transmodel / DfT definitions
// ==========================================

enum class TransportMode { 
    ROAD_MOTORIZED,  // Cars, Vans, HGVs, Buses
    ROAD_ACTIVE,     // Bicycles, Cargo Bikes, e-Scooters (Micro-mobility)
    PEDESTRIAN,      // Walking (Passengers or Last-Mile Couriers)
    RAIL,            // Trains, Trams, Subway
    MARITIME,        // Ferries, Cargo Ships
    AIR,             // Planes, Drones
    DEPOT_HANDLING   // Forklifts, Terminal Tractors (Replaces ambiguous "OFF_ROAD")
};

enum class CargoType { 
    PASSENGER, LIQUID_BULK, DRY_BULK, REFRIGERATED, PALLETISED, MIXED 
};

enum class PowertrainType { 
    ICE_DIESEL, ICE_PETROL, BEV_ELECTRIC, FCEV_HYDROGEN, HYBRID 
};

// ==========================================
// 2. THE COMPONENTS (Data Pods)
// ==========================================

// Tracks where the entity is in the world
struct PositionComponent {
    double latitude;
    double longitude;
    float elevation; // Crucial for energy calc (hill climbs)
};

// Represents the "Operational Characteristics" (Ontology Part 1 & 4)
struct TaxonomyComponent {
    TransportMode mode;
    uint8_t automationLevel; // SAE Levels 0-5
    bool isEmergency;        // High priority routing
};

// Represents the "Functional Categorization" (Ontology Part 2)
struct PayloadComponent {
    CargoType type;
    float currentLoadKg;
    float maxCapacityKg; // GVW or DWT
    int passengerCount;
    int maxPassengers;
};

// Represents the "Energy & Physics" for Decarbonization (Ontology Part 3)
struct EnergyComponent {
    PowertrainType engineType;
    float currentEnergyStorage; // kWh for batteries, Liters for ICE
    float maxEnergyStorage;
    float baseEfficiency;       // e.g., kWh per km at 0% grade, empty load
};

// Represents the "Velocity & Movement" 
struct KinematicComponent {
    float speed_mps; // Meters per second
    float heading;
};