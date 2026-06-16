// services/l1-engine/src/DataBridge.cpp
#include "DataBridge.h"
#include "AgentComponents.h"
#include <nlohmann/json.hpp>
#include <iostream>
#include <algorithm>

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
DataBridge::DataBridge(const std::string& pub_address, const std::string& sub_address,
                         const std::string& kg_pub_address, const std::string& kg_sub_address)
    : context(1)
    , publisher(context, zmq::socket_type::pub)
    , subscriber(context, zmq::socket_type::sub)
    , kg_publisher(context, zmq::socket_type::pub)
    , kg_subscriber(context, zmq::socket_type::sub) {

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

    // Phase 12: L7 Knowledge Graph sockets
    if (!kg_pub_address.empty()) {
        kg_publisher.set(zmq::sockopt::sndhwm, 1000);
        kg_publisher.set(zmq::sockopt::linger, 0);
        kg_publisher.bind(kg_pub_address);
        std::cout << "[L7-KG] Experience PUB bound to " << kg_pub_address << std::endl;
    }
    if (!kg_sub_address.empty()) {
        kg_subscriber.set(zmq::sockopt::rcvhwm, 1000);
        kg_subscriber.set(zmq::sockopt::linger, 0);
        kg_subscriber.set(zmq::sockopt::reconnect_ivl, 100);
        kg_subscriber.set(zmq::sockopt::reconnect_ivl_max, 5000);
        kg_subscriber.connect(kg_sub_address);
        kg_subscriber.set(zmq::sockopt::subscribe, "ctt.kg.match");
        std::cout << "[L7-KG] Match SUB connected to " << kg_sub_address << std::endl;
    }
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
        const MindsetComponent,
        const ExternalitiesComponent,
        const SocialImpactComponent
    >();

    q.each([&](flecs::entity e, 
               const TaxonomyComponent& tax, 
               const EnergyComponent& energy, 
               const PositionComponent& pos,
               const MindsetComponent& mindset,
               const ExternalitiesComponent& ext,
               const SocialImpactComponent& soc) {

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
            {"is_decarbonized", mindset.is_decarbonized},
            // Phase 12 — SSN Experience (if available)
            {"has_ssn", e.has<SSN_Experience_Component>()},
            // Phase 7 — Externalities
            {"current_co2_g_km", ext.current_co2_g_km},
            {"current_nox_g_km", ext.current_nox_g_km},
            {"current_pm25_g_km", ext.current_pm25_g_km},
            {"current_noise_db", ext.current_noise_db},
            {"cumulative_co2_kg", ext.cumulative_co2_kg},
            {"cumulative_nox_kg", ext.cumulative_nox_kg},
            {"cumulative_pm25_kg", ext.cumulative_pm25_kg},
            // Phase 7 — Social impact
            {"accessibility_score", soc.accessibility_score},
            {"jobs_dependent", soc.jobs_dependent},
            {"deprivation_index", soc.deprivation_index},
            {"equity_exposure", soc.equity_exposure},
            {"serves_deprived_ward", soc.serves_deprived_ward},
            {"corridor_id", soc.corridor_id}
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
    if (cmds.empty()) {
        return;
    }

    size_t affected_count = 0;

    for (const auto& cmd : cmds) {
        if (cmd.agent_uuid == "all_hgv" || cmd.agent_uuid == "all") {
            auto q = world.query<MindsetComponent>();
            q.each([&](flecs::entity e, MindsetComponent& m) {
                m.adversarial_pressure += cmd.pressure_delta;
                affected_count++;
            });
        } else {
            auto e = world.lookup(cmd.agent_uuid.c_str());
            if (e.is_alive()) {
                auto& m = e.get_mut<MindsetComponent>();
                m.adversarial_pressure += cmd.pressure_delta;
                affected_count++;
            } else {
                std::cerr << "[L2 Bridge] ⚠️  Entity not found: " << cmd.agent_uuid << std::endl;
            }
        }
    }

    // Phase 6.5: Single summary line instead of per-agent spam
    std::cout << "[L2 Bridge] Applied " << cmds.size() << " perturbation command(s), "
              << affected_count << " agent(s) affected" << std::endl;
}

std::string DataBridge::snapshot_world(flecs::world& world) {
    json payload = json::array();

    auto q = world.query<
        const TaxonomyComponent, 
        const EnergyComponent, 
        const PositionComponent,
        const MindsetComponent,
        const ExternalitiesComponent,
        const SocialImpactComponent
    >();

    q.each([&](flecs::entity e, 
               const TaxonomyComponent& tax, 
               const EnergyComponent& energy, 
               const PositionComponent& pos,
               const MindsetComponent& mindset,
               const ExternalitiesComponent& ext,
               const SocialImpactComponent& soc) {

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
            {"is_decarbonized", mindset.is_decarbonized},
            // Phase 7 — Externalities
            {"current_co2_g_km", ext.current_co2_g_km},
            {"current_nox_g_km", ext.current_nox_g_km},
            {"current_pm25_g_km", ext.current_pm25_g_km},
            {"current_noise_db", ext.current_noise_db},
            {"cumulative_co2_kg", ext.cumulative_co2_kg},
            {"cumulative_nox_kg", ext.cumulative_nox_kg},
            {"cumulative_pm25_kg", ext.cumulative_pm25_kg},
            // Phase 7 — Social impact
            {"accessibility_score", soc.accessibility_score},
            {"jobs_dependent", soc.jobs_dependent},
            {"deprivation_index", soc.deprivation_index},
            {"equity_exposure", soc.equity_exposure},
            {"serves_deprived_ward", soc.serves_deprived_ward},
            {"corridor_id", soc.corridor_id}
        });
    });

    return payload.dump();
}

void DataBridge::broadcast_string(const std::string& payload) {
    zmq::message_t message(payload.data(), payload.size());
    publisher.send(message, zmq::send_flags::dontwait);
}

// ---------------------------------------------------------------------------
// Phase 12: L7 Knowledge Graph Methods
// ---------------------------------------------------------------------------

void DataBridge::broadcast_kg_experience(const std::string& agent_id,
                                          const SSN_Experience_Component& ssn,
                                          const std::string& corridor_id) {
    json payload = {
        {"topic", "ctt.kg.experience"},
        {"agent_id", agent_id},
        {"experience_id", ssn.experience_id},
        {"timestamp_ms", ssn.timestamp_ms},
        {"confidence", ssn.confidence},
        {"is_one_shot_success", ssn.is_one_shot_success},
        {"corridor_id", corridor_id},
        {"signature", std::vector<float>(ssn.signature.begin(), ssn.signature.end())}
    };

    std::string msg_str = payload.dump();
    zmq::message_t topic("ctt.kg.experience", 18);
    zmq::message_t body(msg_str.data(), msg_str.size());
    kg_publisher.send(topic, zmq::send_flags::sndmore);
    kg_publisher.send(body, zmq::send_flags::dontwait);
}

std::vector<KGMatch> DataBridge::poll_kg_matches() {
    std::vector<KGMatch> matches;

    while (true) {
        zmq::message_t topic_msg;
        auto result = kg_subscriber.recv(topic_msg, zmq::recv_flags::dontwait);
        if (!result) break;

        zmq::message_t body_msg;
        result = kg_subscriber.recv(body_msg, zmq::recv_flags::dontwait);
        if (!result) break;

        try {
            std::string body_str(static_cast<char*>(body_msg.data()), body_msg.size());
            json j = json::parse(body_str);

            KGMatch match;
            match.agent_id = j.value("agent_id", "");
            match.confidence = j.value("confidence", 0.0f);
            match.recommended_procedure = j.value("recommended_procedure", json::object()).dump();
            matches.push_back(match);

            std::cout << "[L7-KG] 📥 Match received for " << match.agent_id 
                      << " (confidence=" << match.confidence << ")" << std::endl;
        } catch (const std::exception& e) {
            std::cerr << "[L7-KG] ⚠️  Failed to parse KG match: " << e.what() << std::endl;
        }
    }
    return matches;
}

void DataBridge::apply_kg_matches(flecs::world& world, const std::vector<KGMatch>& matches) {
    if (matches.empty()) return;

    for (const auto& match : matches) {
        auto e = world.lookup(match.agent_id.c_str());
        if (e.is_alive()) {
            auto* mindset = e.get_mut<MindsetComponent>();
            if (mindset) {
                float boost = match.confidence * 2.0f;
                mindset->satisfaction = std::min(10.0, mindset->satisfaction + boost);

                std::cout << "[L7-KG] 🎯 Applied match to " << match.agent_id 
                          << " (satisfaction +" << boost << ")" << std::endl;
            }
        } else {
            std::cerr << "[L7-KG] ⚠️  Agent not found: " << match.agent_id << std::endl;
        }
    }
}

} // namespace CTT