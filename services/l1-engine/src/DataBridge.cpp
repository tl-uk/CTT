// services/l1-engine/src/DataBridge.cpp
#include "DataBridge.h"
#include "AgentComponents.h"
#include <nlohmann/json.hpp>
#include <iostream>
#include "ctt_messages.pb.h"

using json = nlohmann::json;

namespace CTT {

DataBridge::DataBridge(const std::string& pub_address, const std::string& sub_address)
    : context(1)
    , publisher(context, zmq::socket_type::pub)
    , subscriber(context, zmq::socket_type::sub) {
    
    publisher.bind(pub_address);
    std::cout << "[L2 Bridge] ZeroMQ Publisher bound to " << pub_address << std::endl;
    
    subscriber.connect(sub_address);
    subscriber.set(zmq::sockopt::subscribe, "");
    std::cout << "[L2 Bridge] ZeroMQ Subscriber connected to " << sub_address << std::endl;
}

void DataBridge::broadcast_state(flecs::world& world) {
    json payload = json::array();

    auto q = world.query<
        const TaxonomyComponent, 
        const EnergyComponent, 
        const PositionComponent,
        const MindsetComponent
    >();

    q.each([&](flecs::entity e, 
               const TaxonomyComponent& tax, 
               const EnergyComponent& energy, 
               const PositionComponent& pos,
               const MindsetComponent& mindset) {
        
        float energy_pct = 0.0f;
        if (energy.maxEnergyStorage > 0.0f) {
            energy_pct = (energy.currentEnergyStorage / energy.maxEnergyStorage) * 100.0f;
        }

        payload.push_back({
            {"entity_name", e.name().c_str()},
            {"mode", static_cast<int>(tax.mode)},
            {"powertrain", static_cast<int>(energy.engineType)},
            {"energy_pct", energy_pct},
            {"lat", pos.latitude},
            {"lon", pos.longitude},
            {"adversarial_pressure", mindset.adversarial_pressure},
            {"is_decarbonized", mindset.is_decarbonized}
        });
    });

    std::string message_string = payload.dump();
    zmq::message_t message(message_string.data(), message_string.size());
    publisher.send(message, zmq::send_flags::none);
}

void DataBridge::receive_perturbations(flecs::world& world) {
    zmq::message_t msg;
    auto result = subscriber.recv(msg, zmq::recv_flags::dontwait);
    
    if (!result || msg.size() == 0) {
        return;
    }

    ctt::MindsetPerturbation p;
    if (!p.ParseFromArray(msg.data(), static_cast<int>(msg.size()))) {
        std::cerr << "[L2 Bridge] ⚠️  Failed to parse Protobuf perturbation" << std::endl;
        return;
    }

    std::cout << "[L2 Bridge] 📥 RAW RECEIVED: agent=" << p.agent_uuid() 
              << " delta=" << p.pressure_delta() 
              << " source=" << p.source() << std::endl;

    if (p.agent_uuid() == "all_hgv" || p.agent_uuid() == "all") {
        auto q = world.query<MindsetComponent>();
        q.each([&](flecs::entity e, MindsetComponent& m) {
            std::cout << "[L2 Bridge] 🔄 BEFORE: " << e.name() 
                      << " pressure=" << m.adversarial_pressure << std::endl;
            m.adversarial_pressure += p.pressure_delta();
            std::cout << "[L2 Bridge] ✅ AFTER: " << e.name() 
                      << " pressure=" << m.adversarial_pressure << std::endl;
        });
    } else {
        auto e = world.lookup(p.agent_uuid().c_str());
        if (e.is_alive()) {
            auto& m = e.get_mut<MindsetComponent>();
            std::cout << "[L2 Bridge] 🔄 BEFORE: " << e.name() 
                      << " pressure=" << m.adversarial_pressure << std::endl;
            m.adversarial_pressure += p.pressure_delta();
            std::cout << "[L2 Bridge] ✅ AFTER: " << e.name() 
                      << " pressure=" << m.adversarial_pressure << std::endl;
        } else {
            std::cerr << "[L2 Bridge] ⚠️  Entity not found: " << p.agent_uuid() << std::endl;
        }
    }
}

} // namespace CTT