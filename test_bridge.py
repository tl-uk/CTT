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