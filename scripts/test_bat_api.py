#!/usr/bin/env python3
"""
BAT API Diagnostic Script
Run this to test your BAT API key against various endpoints.
"""
import os
import sys
from pathlib import Path

# Load .env
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "services" / "config"))
from settings import config

import requests

API_KEY = config.BAT_API_KEY
BASE = config.BAT_BASE_URL

print("=" * 60)
print("BAT API Diagnostic")
print("=" * 60)
print(f"Base URL: {BASE}")
print(f"Key prefix: {API_KEY[:15]}..." if len(API_KEY) > 15 else f"Key: {API_KEY}")
print(f"Key length: {len(API_KEY)} chars")
print()

headers = {"Authorization": f"Bearer {API_KEY}"}

# Test 1: Simple stops search (should work on free tier)
print("Test 1: Search stops near Cardiff")
url = f"{BASE}/v1/stops"
params = {"q": "Cardiff", "limit": 1}
try:
    resp = requests.get(url, headers=headers, params=params, timeout=10)
    print(f"  Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(f"  ✅ OK — found {data.get('total', 0)} stops")
    else:
        print(f"  ❌ Failed: {resp.text[:200]}")
except Exception as e:
    print(f"  ❌ Error: {e}")

print()

# Test 2: Bus departures (Cardiff Central Station)
print("Test 2: Bus departures (Cardiff Central)")
atco = "5710AWA10575"
url = f"{BASE}/v1/stops/{atco}/departures"
try:
    resp = requests.get(url, headers=headers, timeout=10)
    print(f"  Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        deps = data.get("departures", [])
        print(f"  ✅ OK — {len(deps)} departures")
        for d in deps[:2]:
            print(f"      {d.get('line')} to {d.get('destination')} — sched:{d.get('scheduled')} exp:{d.get('expected')}")
    else:
        print(f"  ❌ Failed: {resp.text[:200]}")
except Exception as e:
    print(f"  ❌ Error: {e}")

print()

# Test 3: Rail departures (Paddington)
print("Test 3: Rail departures (Paddington)")
crs = "PAD"
url = f"{BASE}/v1/rail/stations/{crs}/departures"
try:
    resp = requests.get(url, headers=headers, timeout=10)
    print(f"  Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        deps = data.get("departures", [])
        print(f"  ✅ OK — {len(deps)} departures")
        for d in deps[:2]:
            print(f"      {d.get('scheduled')} to {d.get('destination')} — Platform {d.get('platform', '?')}")
    else:
        print(f"  ❌ Failed: {resp.text[:200]}")
except Exception as e:
    print(f"  ❌ Error: {e}")

print()
print("=" * 60)
print("Diagnostic complete.")
print("=" * 60)
