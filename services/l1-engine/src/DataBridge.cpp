// services/l1-engine/src/DataBridge.cpp
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

void DataBridge::broadcast_state(flecs::world& world) {
    json payload = json::array();

    // Create a query to find all entities with these specific components
    auto q = world.query<const TaxonomyComponent, const EnergyComponent, const PositionComponent>();

    q.each([&](flecs::entity e, const TaxonomyComponent& tax, const EnergyComponent& energy, const PositionComponent& pos) {
        float energy_pct = 0.0f;
        if (energy.maxEnergyStorage > 0.0f) {
            energy_pct = (energy.currentEnergyStorage / energy.maxEnergyStorage) * 100.0f;
        }

        payload.push_back({
            {"entity_name", e.name().c_str()}, // Flecs allows us to send the actual name
            {"mode", static_cast<int>(tax.mode)},
            {"powertrain", static_cast<int>(energy.engineType)},
            {"energy_pct", energy_pct},
            {"lat", pos.latitude},
            {"lon", pos.longitude}
        });
    });

    std::string message_string = payload.dump();
    zmq::message_t message(message_string.data(), message_string.size());
    publisher.send(message, zmq::send_flags::none);
}

} // namespace CTT