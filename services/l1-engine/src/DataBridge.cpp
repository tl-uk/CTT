// services/l1-engine/src/DataBridge.cpp
#include "DataBridge.h"
#include "AgentComponents.h"
#include <nlohmann/json.hpp>
#include <iostream>

using json = nlohmann::json;

namespace CTT {

// ---------------------------------------------------------------------------
// ThreadSafePerturbationQueue
// ---------------------------------------------------------------------------
void ThreadSafePerturbationQueue::push(PerturbationCmd cmd) {
    std::lock_guard<std::mutex> lock(mtx);
    buffer.push_back(std::move(cmd));
}

std::vector<PerturbationCmd> ThreadSafePerturbationQueue::pop_all() {
    std::lock_guard<std::mutex> lock(mtx);
    auto out = std::move(buffer);
    buffer = {};
    return out;
}

// ---------------------------------------------------------------------------
// ThreadSafeTelemetryBuffer
// ---------------------------------------------------------------------------
void ThreadSafeTelemetryBuffer::set(std::string payload) {
    std::lock_guard<std::mutex> lock(mtx);
    buffer = std::move(payload);
    fresh = true;
}

bool ThreadSafeTelemetryBuffer::get(std::string& out) {
    std::lock_guard<std::mutex> lock(mtx);
    if (!fresh) return false;
    out = std::move(buffer);
    fresh = false;
    return true;
}

// ---------------------------------------------------------------------------
// DataBridge
// ---------------------------------------------------------------------------
DataBridge::DataBridge(const std::string& pub_address, const std::string& sub_address)
    : context(1)
    , publisher(context, zmq::socket_type::pub)
    , subscriber(context, zmq::socket_type::sub) {

    // Hardened socket options for Colima / container network resilience
    publisher.set(zmq::sockopt::sndhwm, 1000);
    publisher.set(zmq::sockopt::linger, 0);
    publisher.set(zmq::sockopt::reconnect_ivl, 100);
    publisher.set(zmq::sockopt::reconnect_ivl_max, 5000);

    subscriber.set(zmq::sockopt::rcvhwm, 1000);
    subscriber.set(zmq::sockopt::linger, 0);
    subscriber.set(zmq::sockopt::reconnect_ivl, 100);
    subscriber.set(zmq::sockopt::reconnect_ivl_max, 5000);

    publisher.bind(pub_address);
    std::cout << "[L2 Bridge] ZeroMQ Publisher bound to " << pub_address << std::endl;

    subscriber.connect(sub_address);
    subscriber.set(zmq::sockopt::subscribe, "");
    std::cout << "[L2 Bridge] ZeroMQ Subscriber connected to " << sub_address << std::endl;
}

// ---------------------------------------------------------------------------
// Legacy Single-Threaded API
// ---------------------------------------------------------------------------
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

    apply_perturbations(world, {{p.agent_uuid(), p.pressure_delta(), p.source()}});
}

// ---------------------------------------------------------------------------
// Threaded API (Phase 6.5)
// ---------------------------------------------------------------------------
void DataBridge::poll_perturbations(ThreadSafePerturbationQueue& queue) {
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

    queue.push({p.agent_uuid(), p.pressure_delta(), p.source()});
}

void DataBridge::apply_perturbations(flecs::world& world, const std::vector<PerturbationCmd>& cmds) {
    for (const auto& cmd : cmds) {
        std::cout << "[L2 Bridge] 📥 RAW RECEIVED: agent=" << cmd.agent_uuid 
                  << " delta=" << cmd.pressure_delta 
                  << " source=" << cmd.source << std::endl;

        if (cmd.agent_uuid == "all_hgv" || cmd.agent_uuid == "all") {
            auto q = world.query<MindsetComponent>();
            q.each([&](flecs::entity e, MindsetComponent& m) {
                std::cout << "[L2 Bridge] 🔄 BEFORE: " << e.name() 
                          << " pressure=" << m.adversarial_pressure << std::endl;
                m.adversarial_pressure += cmd.pressure_delta;
                std::cout << "[L2 Bridge] ✅ AFTER: " << e.name() 
                          << " pressure=" << m.adversarial_pressure << std::endl;
            });
        } else {
            auto e = world.lookup(cmd.agent_uuid.c_str());
            if (e.is_alive()) {
                auto& m = e.get_mut<MindsetComponent>();
                std::cout << "[L2 Bridge] 🔄 BEFORE: " << e.name() 
                          << " pressure=" << m.adversarial_pressure << std::endl;
                m.adversarial_pressure += cmd.pressure_delta;
                std::cout << "[L2 Bridge] ✅ AFTER: " << e.name() 
                          << " pressure=" << m.adversarial_pressure << std::endl;
            } else {
                std::cerr << "[L2 Bridge] ⚠️  Entity not found: " << cmd.agent_uuid << std::endl;
            }
        }
    }
}

std::string DataBridge::snapshot_world(flecs::world& world) {
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

    return payload.dump();
}

void DataBridge::broadcast_string(const std::string& payload) {
    zmq::message_t message(payload.data(), payload.size());
    publisher.send(message, zmq::send_flags::dontwait);
}

} // namespace CTT