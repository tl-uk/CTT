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