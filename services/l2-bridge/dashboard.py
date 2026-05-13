"""
services/l2-bridge/dashboard.py

This script serves as a simple dashboard for the L2 Bridge, allowing users to monitor the pulses emitted 
by the M3 Engine in real-time. It connects to the M3 Engine's ZeroMQ publisher socket and prints incoming 
messages to the console.
"""
import zmq

context = zmq.Context()
socket = context.socket(zmq.SUB) # Subscriber mode
socket.connect("tcp://localhost:5555")
socket.setsockopt_string(zmq.SUBSCRIBE, "") # Subscribe to all messages

print("Listening for M3 Engine pulses...")

try:
    while True:
        message = socket.recv_string()
        print(f"Captured: {message}")
except KeyboardInterrupt:
    print("Bridge Closed.")