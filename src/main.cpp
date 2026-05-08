#include <iostream>
#include <zmq.hpp>
#include <chrono>
#include <thread>

int main() {
    zmq::context_t context(1);
    zmq::socket_t socket(context, zmq::socket_type::pub); // Using PUB for "Broadcast"
    socket.bind("tcp://*:5555");

    std::cout << "CTT Master Engine Online [L1 Reflexive Layer]" << std::endl;
    
    int tick = 0;
    while (true) { // This keeps the engine ALIVE
        std::string message = "Pulse from M3 at tick " + std::to_string(tick);
        socket.send(zmq::buffer(message), zmq::send_flags::none);
        
        std::cout << "Pulse sent at tick " << tick << std::endl;
        tick++;

        // Sleep for 1 second so we don't spam the CPU
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    return 0;
}