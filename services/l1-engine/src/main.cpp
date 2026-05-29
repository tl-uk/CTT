// services/l1-engine/src/main.cpp
#include <iostream>
#include <chrono>
#include <thread>
#include <atomic>
#include <cstdlib>
#include "SimulationEngine.h"
#include "DataBridge.h"

// Global shutdown flag for ZMQ thread
std::atomic<bool> g_running{true};

/**
 * @brief ZMQ I/O thread.
 * 
 * Isolated from the Flecs main thread to prevent REST timeout warnings.
 * Polls perturbations at ~100 Hz and broadcasts telemetry whenever fresh
 * data is available from the main thread.
 */
void zmq_thread_func(CTT::DataBridge* bridge,
                     CTT::ThreadSafePerturbationQueue* pert_queue,
                     CTT::ThreadSafeTelemetryBuffer* tele_buffer) {
    std::cout << "[L2 Bridge] ZMQ I/O thread started" << std::endl;

    while (g_running && bridge->running()) {
        // 1. Poll incoming perturbations from Python pipeline (non-blocking)
        bridge->poll_perturbations(*pert_queue);

        // 2. Broadcast telemetry if main thread has published a fresh snapshot
        std::string payload;
        if (tele_buffer->get(payload)) {
            bridge->broadcast_string(payload);
        }

        // 3. Sleep to yield CPU (10 kHz polling is overkill; 100 Hz is fine)
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }

    std::cout << "[L2 Bridge] ZMQ I/O thread stopped" << std::endl;
}

int main() {
    std::cout << "--- CTT Master Engine Online ---" << std::endl;

    CTT::SimulationEngine engine;

    // PUB on 5555 (telemetry out), SUB on 5556 (perturbations in)
    const char* fusion_host = std::getenv("CTT_FUSION_HOST");
    std::string sub_addr = "tcp://";
    sub_addr += (fusion_host ? fusion_host : "localhost");
    sub_addr += ":5556";
    CTT::DataBridge bridge("tcp://*:5555", sub_addr);

    engine.initialize_test_fleet();

    std::cout << "[L1 UI] Open Flecs Explorer: http://localhost:8000" << std::endl;
    std::cout << "[L1 UI] REST API: http://localhost:27750/explorer to view the Digital Twin" << std::endl;

    // -----------------------------------------------------------------------
    // Phase 6.5 — Threaded ZMQ I/O
    // -----------------------------------------------------------------------
    CTT::ThreadSafePerturbationQueue pert_queue;
    CTT::ThreadSafeTelemetryBuffer tele_buffer;

    std::thread zmq_worker(zmq_thread_func, &bridge, &pert_queue, &tele_buffer);

    // The Master Clock Loop — deterministic 10 Hz, isolated from ZMQ latency
    auto last_time = std::chrono::high_resolution_clock::now();

    while (true) {
        auto current_time = std::chrono::high_resolution_clock::now();
        float delta_time = std::chrono::duration<float>(current_time - last_time).count();
        last_time = current_time;

        // 1. Apply queued perturbations from ZMQ thread BEFORE the tick
        auto perts = pert_queue.pop_all();
        if (!perts.empty()) {
            CTT::DataBridge::apply_perturbations(engine.get_world(), perts);
        }

        // 2. Tick the Flecs Reflexive Engine (BDI + Physics)
        engine.update(delta_time);

        // 3. Snapshot world state and hand off to ZMQ thread for broadcast
        std::string snapshot = CTT::DataBridge::snapshot_world(engine.get_world());
        tele_buffer.set(std::move(snapshot));

        // 4. Maintain ~10 Hz (100 ms) tick rate
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    // Cleanup (unreachable in current loop, but good practice)
    g_running = false;
    bridge.stop();
    if (zmq_worker.joinable()) {
        zmq_worker.join();
    }

    return 0;
}