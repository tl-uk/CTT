// services/l1-engine/include/DataBridge.h
// Phase 7 — hardened ZMQ bridge with thread-safe telemetry & perturbation queues
#pragma once
#include <string>
#include <vector>
#include <mutex>
#include <atomic>
#include <zmq.hpp>
#include "flecs.h"
#include "AgentComponents.h"
#include "ctt_messages.pb.h"

namespace CTT {

/**
 * @struct PerturbationCmd
 * @brief Thread-safe command for applying pressure deltas.
 */
struct PerturbationCmd {
    std::string agent_uuid;
    double pressure_delta;
    std::string source;
};

/**
 * @class ThreadSafePerturbationQueue
 * @brief Lock-protected queue for cross-thread perturbation handoff.
 */
class ThreadSafePerturbationQueue {
public:
    void push(PerturbationCmd cmd);
    std::vector<PerturbationCmd> pop_all();
private:
    std::mutex mtx;
    std::vector<PerturbationCmd> buffer;
};

/**
 * @class ThreadSafeTelemetryBuffer
 * @brief Double-buffer for JSON telemetry snapshots.
 */
class ThreadSafeTelemetryBuffer {
public:
    void set(std::string payload);
    bool get(std::string& out);
private:
    std::mutex mtx;
    std::string buffer;
    bool fresh = false;
};

/**
 * @class DataBridge
 * @brief ZeroMQ PUB/SUB bridge with thread-safe queue mode.
 *
 * Two usage modes:
 *   1. Legacy (single-threaded): broadcast_state(world) + receive_perturbations(world)
 *   2. Threaded (Phase 6.5): zmq_thread() runs in background; main thread calls
 *      apply_perturbations(world, queue) + snapshot_world(world, buffer).
 */
class DataBridge {
public:
    DataBridge(const std::string& pub_address, const std::string& sub_address);

    // --- Legacy single-threaded API (kept for compatibility) ---
    void broadcast_state(flecs::world& world);
    void receive_perturbations(flecs::world& world);

    // --- Threaded API (Phase 6.5) ---
    /** Poll ZMQ SUB, parse protobuf, push to queue. Non-blocking. */
    void poll_perturbations(ThreadSafePerturbationQueue& queue);

    /** Apply queued perturbations to the Flecs world. Call from main thread. */
    static void apply_perturbations(flecs::world& world, const std::vector<PerturbationCmd>& cmds);

    /** Serialize world state to JSON. Call from main thread. */
    static std::string snapshot_world(flecs::world& world);

    /** Broadcast a pre-serialized JSON string. Call from ZMQ thread. */
    void broadcast_string(const std::string& payload);

    /** Signal the ZMQ thread to shut down. */
    void stop() { _running = false; }
    bool running() const { return _running.load(); }

private:
    zmq::context_t context;
    zmq::socket_t publisher;
    zmq::socket_t subscriber;
    std::atomic<bool> _running{true};
};

} // namespace CTT