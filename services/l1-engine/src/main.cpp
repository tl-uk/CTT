// services/l1-engine/src/main.cpp
#include <iostream>
#include <chrono>
#include <thread>
#include "SimulationEngine.h"
#include "DataBridge.h"

int main() {
    std::cout << "--- CTT Master Engine Online ---" << std::endl;
    
    CTT::SimulationEngine engine;
    // PUB on 5555 (telemetry out), SUB on 5556 (perturbations in)
    CTT::DataBridge bridge("tcp://*:5555", "tcp://localhost:5556");

    engine.initialize_test_fleet();

    std::cout << "[L1 UI] Open Flecs Explorer: http://localhost:8000" << std::endl;
    std::cout << "[L1 UI] REST API: http://localhost:27750/explorer to view the Digital Twin" << std::endl;

    // The Master Clock Loop
    auto last_time = std::chrono::high_resolution_clock::now();

    while (true) {
        auto current_time = std::chrono::high_resolution_clock::now();
        float delta_time = std::chrono::duration<float>(current_time - last_time).count();
        last_time = current_time;

        // 1. Tick the Flecs Reflexive Engine
        engine.update(delta_time);

        // 2. Receive perturbations from Python pipeline and apply to the world
        bridge.receive_perturbations(engine.get_world());

        // 3. Broadcast state to Python dashboard
        bridge.broadcast_state(engine.get_world());

        // Sleep to maintain ~10Hz (100ms) tick rate
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    return 0;
}