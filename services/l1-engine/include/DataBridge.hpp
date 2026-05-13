// services/l1-engine/include/DataBridge.hpp
#pragma once
#include <zmq.hpp>
#include <flecs.h>
#include <string>

namespace CTT {

    /**
     * @class DataBridge
     * @brief L2 Messaging layer: broadcasts state OUT and receives perturbations IN.
     */
    class DataBridge {
    public:
        /**
         * @brief Initializes ZMQ pub (telemetry out) and sub (commands in).
         * @param pub_address  Bind address for state broadcasts (e.g., "tcp://*:5555").
         * @param sub_address  Connect address for perturbations (e.g., "tcp://localhost:5556").
         */
        DataBridge(const std::string& pub_address, const std::string& sub_address);
        ~DataBridge() = default;

        /** @brief Serializes agent states and broadcasts to Python layer. */
        void broadcast_state(flecs::world& world);

        /** @brief Receives Protobuf perturbations and applies to ECS entities. */
        void receive_perturbations(flecs::world& world);

    private:
        zmq::context_t context;
        zmq::socket_t publisher;
        zmq::socket_t subscriber;
    };

} // namespace CTT