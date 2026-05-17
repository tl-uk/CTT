#!/usr/bin/env python3
"""Quick BAT API key diagnostic."""
import os, sys
from pathlib import Path

# Force load .env
from dotenv import load_dotenv
PROJECT_ROOT = Path(__file__).parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Check raw env var
raw_key = os.getenv("BAT_API_KEY", "")
print(f"Raw BAT_API_KEY from os.getenv: '{raw_key}'")
print(f"Length: {len(raw_key)} chars")
print(f"Starts with 'bat_': {raw_key.startswith('bat_')}")
print(f"First 20 chars: '{raw_key[:20]}'")
print(f"Last 5 chars: '{raw_key[-5:]}'")

# Now try importing via settings
sys.path.insert(0, str(PROJECT_ROOT / "services" / "config"))
from settings import config
print(f"\nFrom settings module:")
print(f"  BAT_API_KEY length: {len(config.BAT_API_KEY)}")
print(f"  BAT_BASE_URL: {config.BAT_BASE_URL}")

# Test a simple ping
import requests
headers = {"Authorization": f"Bearer {config.BAT_API_KEY}"}
print(f"\nTesting /v1/stops?q=Cardiff (timeout=15s)...")
try:
    resp = requests.get(f"{config.BAT_BASE_URL}/v1/stops", headers=headers, params={"q": "Cardiff", "limit": 1}, timeout=15)
    print(f"  Status: {resp.status_code}")
    print(f"  Body: {resp.text[:200]}")
except Exception as e:
    print(f"  Error: {e}")