import requests

API_KEY = "bat_53ea4a29042b7fd16c657b3c38e0c849"
BASE = "https://api.busesandtrains.co.uk"
headers = {"Authorization": f"Bearer {API_KEY}"}

# Bus departures
data = requests.get(
    f"{BASE}/v1/stops/5710AWA10575/departures",
    headers=headers
).json()

for dep in data["departures"]:
    status = dep.get("expected") or dep["scheduled"]
    print(f"  {dep['line']} to {dep['destination']} - {status}")

# Rail departures
rail = requests.get(
    f"{BASE}/v1/rail/stations/CDF/departures",
    headers=headers
).json()

for train in rail["departures"]:
    print(f"  {train['scheduled']} to {train['destination']} (Platform {train.get('platform', '?')})")