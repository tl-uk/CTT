// services/l1-engine/include/DataBridge.h
#pragma once
#include <string>
#include <vector>
#include <mutex>
#include <zmq.hpp>
#include "flecs.h"
#include "AgentComponents.h"
#include "ssn_experience_component.h"

namespace CTT {

// ---------------------------------------------------------------------------
// Phase 12: L7 Knowledge Graph Match Structure
// ---------------------------------------------------------------------------
struct KGMatch {
    std::string agent_id;
    float confidence;
    std::string recommended_procedure;
};

// ---------------------------------------------------------------------------
// Thread-safe queues for cross-thread communication
// ---------------------------------------------------------------------------
struct PerturbationCmd {
    std::string agent_uuid;
    double pressure_delta;
    std::string source;
};

class ThreadSafePerturbationQueue {
    std::mutex mtx;
    std::vector<PerturbationCmd> buffer;
public:
    void push(PerturbationCmd cmd);
    std::vector<PerturbationCmd> pop_all();
};

class ThreadSafeTelemetryBuffer {
    std::mutex mtx;
    std::string buffer;
    bool fresh = false;
public:
    void set(std::string payload);
    bool get(std::string& out);
};

// Phase 12: Thread-safe KG match queue
class ThreadSafeKGMatchQueue {
    std::mutex mtx;
    std::vector<KGMatch> buffer;
public:
    void push_all(std::vector<KGMatch> matches) {
        std::lock_guard<std::mutex> lock(mtx);
        buffer.insert(buffer.end(), matches.begin(), matches.end());
    }
    std::vector<KGMatch> pop_all() {
        std::lock_guard<std::mutex> lock(mtx);
        auto out = std::move(buffer);
        buffer = {};
        return out;
    }
};

// ---------------------------------------------------------------------------
// DataBridge — ZMQ I/O for telemetry and perturbations
// Phase 12: Added L7 Knowledge Graph PUB/SUB
// ---------------------------------------------------------------------------
class DataBridge {
public:
    DataBridge(const std::string& pub_address, 
               const std::string& sub_address,
               const std::string& kg_pub_address = "",
               const std::string& kg_sub_address = "");

    ~DataBridge() { stop(); }

    void stop() { _running = false; }
    bool running() const { return _running; }

    // Legacy single-threaded API
    void broadcast_state(flecs::world& world);
    void receive_perturbations(flecs::world& world);

    // Threaded API (Phase 6.5 + 12)
    void poll_perturbations(ThreadSafePerturbationQueue& queue);
    static void apply_perturbations(flecs::world& world, const std::vector<PerturbationCmd>& cmds);

    // Phase 12: KG methods
    void broadcast_kg_experience(const std::string& agent_id,
                                  const SSN_Experience_Component& ssn,
                                  const std::string& corridor_id);
    std::vector<KGMatch> poll_kg_matches();
    static void apply_kg_matches(flecs::world& world, const std::vector<KGMatch>& matches);

    static std::string snapshot_world(flecs::world& world);
    void broadcast_string(const std::string& payload);

private:
    zmq::context_t context;
    zmq::socket_t publisher;
    zmq::socket_t subscriber;

    // Phase 12: L7 Knowledge Graph sockets
    zmq::socket_t kg_publisher;
    zmq::socket_t kg_subscriber;
    bool _running = true;
};

} // namespace CTT
