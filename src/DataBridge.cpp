#include "DataBridge.hpp"
#include "AgentComponents.hpp"
#include <nlohmann/json.hpp>
#include <iostream>

using json = nlohmann::json;

namespace CTT {

DataBridge::DataBridge(const std::string& address) 
    : context(1), publisher(context, zmq::socket_type::pub) {
    
    publisher.bind(address);
    std::cout << "[L2 Bridge] ZeroMQ Publisher bound to " << address << std::endl;
}

void DataBridge::broadcast_state(entt::registry& registry) {
    json payload = json::array();

    // Create a view of all agents with Taxonomy, Energy, and Position
    auto view = registry.view<TaxonomyComponent, EnergyComponent, PositionComponent>();

    view.each([&](auto entity, auto& tax, auto& energy, auto& pos) {
        
        // Calculate State of Charge (SoC) / Fuel Level percentage
        float energy_pct = 0.0f;
        if (energy.maxEnergyStorage > 0.0f) {
            energy_pct = (energy.currentEnergyStorage / energy.maxEnergyStorage) * 100.0f;
        }

        // Build the Digital Shadow telemetry object
        payload.push_back({
            {"entity_id", static_cast<uint32_t>(entity)},
            {"mode", static_cast<int>(tax.mode)},
            {"powertrain", static_cast<int>(energy.engineType)},
            {"energy_pct", energy_pct},
            {"lat", pos.latitude},
            {"lon", pos.longitude}
        });
    });

    // Serialize and send
    std::string message_string = payload.dump();
    zmq::message_t message(message_string.data(), message_string.size());
    
    publisher.send(message, zmq::send_flags::none);
}

} // namespace CTT