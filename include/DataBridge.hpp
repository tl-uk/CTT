#pragma once
#include <zmq.hpp>
#include <entt/entt.hpp>
#include <string>

namespace CTT {

    /**
     * @class DataBridge
     * @brief Manages the L2 Messaging layer (Digital Shadow Telemetry).
     * Serializes CTT ECS component data into JSON and broadcasts it via ZeroMQ to the Python Cognitive layer.
     */
    class DataBridge {
    public:
        /**
         * @brief Initializes the ZeroMQ context and binds to the specified port.
         * @param address The TCP address to bind to (e.g., "tcp://*:5555").
         */
        DataBridge(const std::string& address);
        ~DataBridge() = default;

        /**
         * @brief Serializes agent states and sends the payload to the Python layer.
         * @param registry Reference to the core SimulationEngine ECS registry.
         */
        void broadcast_state(entt::registry& registry);

    private:
        zmq::context_t context;
        zmq::socket_t publisher;
    };

} // namespace CTT