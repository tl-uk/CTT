"""
services/l2-bridge/dashboard.py

This script serves as a simple dashboard for the L2 Bridge, allowing users to monitor the pulses emitted 
by the M3 Engine in real-time. It connects to the M3 Engine's ZeroMQ publisher socket and prints incoming 
messages to the console.

"""
import zmq
import json
import os

def run_dashboard():
    # ZeroMQ Setup
    context = zmq.Context()
    subscriber = context.socket(zmq.SUB)
    subscriber.connect("tcp://localhost:5555")
    
    # Subscribe to all topics (empty string)
    subscriber.setsockopt_string(zmq.SUBSCRIBE, "")

    print("🚀 CTT L2 Dashboard Active. Listening for L1 Telemetry on port 5555...")
    print("Press Ctrl+C to stop.")

    # State tracking for L3 aggregation
    fleet_stats = {
        "total_agents": 0,
        "green_agents": 0,
        "legacy_agents": 0,
        "avg_adversarial_pressure": 0.0
    }

    try:
        while True:
            # Receive multipart or single string message
            message = subscriber.recv_string()
            
            try:
                data = json.loads(message)
                
                # Logic: Update local L2 state
                # Assuming L1 sends a list of agent updates or individual pulses
                if isinstance(data, list):
                    fleet_stats["total_agents"] = len(data)
                    fleet_stats["green_agents"] = sum(1 for a in data if a.get("is_decarbonized"))
                    fleet_stats["legacy_agents"] = fleet_stats["total_agents"] - fleet_stats["green_agents"]
                    
                    pressures = [a.get("adversarial_pressure", 0) for a in data]
                    fleet_stats["avg_adversarial_pressure"] = sum(pressures) / len(pressures) if pressures else 0

                # Periodic terminal output (scannable)
                os.system('cls' if os.name == 'nt' else 'clear')
                print(f"--- CTT Macro Fleet Status ---")
                print(f"Total Trucks:  {fleet_stats['total_agents']}")
                print(f"Green State:   {fleet_stats['green_agents']} ✅")
                print(f"Legacy State:  {fleet_stats['legacy_agents']} ⛽")
                print(f"Avg Pressure:  {fleet_stats['avg_adversarial_pressure']:.2f}")
                print(f"------------------------------")

            except json.JSONDecodeError:
                print("Received non-JSON payload.")

    except KeyboardInterrupt:
        print("\nShutting down Dashboard.")
    finally:
        subscriber.close()
        context.term()

if __name__ == "__main__":
    run_dashboard()