// services/l1-engine/src/main.cpp
#include <iostream>
#include <chrono>
#include <thread>
#include <cstdlib>   // std::getenv
#include <ctime>     // std::time (for jitter seed)
#include "SimulationEngine.h"
#include "DataBridge.h"

int main() {
    std::cout << "--- CTT Master Engine Online ---" << std::endl;
    
    // Phase 6 TODO: Seed RNG for per-agent Schmitt Trigger jitter
    // (±5% threshold variance prevents thundering-herd decarbonisation).
    // Requires SimulationEngine.cpp modification:
    //   threshold = base * (1.0 + ((rand() % 11) - 5) / 100.0);
    // std::srand(std::time(nullptr));
    
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

    // The Master Clock Loop
    auto last_time = std::chrono::high_resolution_clock::now();

    while (true) {
        auto current_time = std::chrono::high_resolution_clock::now();
        float delta_time = std::chrono::duration<float>(current_time - last_time).count();
        last_time = current_time;

        // 1. Ingest external state changes from Python dashboard (e.g., perturbations, one-shot successes)
        bridge.receive_perturbations(engine.get_world());

        // 2. Run systems with fresh perturbations applied 
        engine.update(delta_time);

        // 3. Broadcast state to Python dashboard
        bridge.broadcast_state(engine.get_world());

        // Sleep to maintain ~10Hz (100ms) tick rate
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    return 0;
}