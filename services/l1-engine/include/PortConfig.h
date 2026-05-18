// services/l1-engine/include/PortConfig.hpp
// Single source of truth for ZMQ endpoints.
// KEEP IN SYNC WITH services/config/ports.py
#pragma once
#include <string>

namespace CTT {
namespace Ports {

    // L1 Engine
    constexpr const char* L1_TELEMETRY_PUB    = "tcp://*:5555";      // Bind
    constexpr const char* L1_TELEMETRY_SUB    = "tcp://localhost:5555"; // Connect

    constexpr const char* L1_PERTURBATION_PUB = "tcp://*:5556";      // Fusion binds here
    constexpr const char* L1_PERTURBATION_SUB = "tcp://localhost:5556"; // C++ SUB connects

    // Data Pipeline
    constexpr const char* HARVESTER_PUB       = "tcp://*:5560";      // Bind
    constexpr const char* HARVESTER_SUB       = "tcp://localhost:5560"; // Connect

    constexpr const char* INTERPRETER_PUB     = "tcp://*:5561";      // Bind
    constexpr const char* INTERPRETER_SUB     = "tcp://localhost:5561"; // Connect

    // Legacy
    constexpr const char* LEGACY_INGESTOR_PUB = "tcp://*:5562";      // Bind

} // namespace Ports
} // namespace CTT
