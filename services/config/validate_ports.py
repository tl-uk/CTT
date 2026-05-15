#!/usr/bin/env python3
"""
services/config/validate_ports.py
Ensures Python ports.py and C++ PortConfig.hpp are synchronized.
Run in CI or before commit.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent

PY_FILE = ROOT / "services" / "config" / "ports.py"
CPP_FILE = ROOT / "services" / "l1-engine" / "include" / "PortConfig.hpp"

def extract_py_ports(path):
    text = path.read_text()
    ports = {}
    for line in text.splitlines():
        if '"' in line and (": " in line or "=" in line):
            m = re.search(r'"(\w+)":?\s*[=:]\s*"([^"]+)"', line)
            if m:
                ports[m.group(1)] = m.group(2)
    return ports

def extract_cpp_ports(path):
    text = path.read_text()
    ports = {}
    for line in text.splitlines():
        m = re.search(r'constexpr\s+const\s+char\*\s+(\w+)\s*=\s*"([^"]+)"', line)
        if m:
            ports[m.group(1)] = m.group(2)
    return ports

py_ports = extract_py_ports(PY_FILE)
cpp_ports = extract_cpp_ports(CPP_FILE)

mismatch = False
all_keys = set(py_ports.keys()) | set(cpp_ports.keys())
for key in sorted(all_keys):
    py_val = py_ports.get(key)
    cpp_val = cpp_ports.get(key)
    if py_val != cpp_val:
        mismatch = True
        print(f"❌ MISMATCH: {key}")
        print(f"   Python: {py_val}")
        print(f"   C++:    {cpp_val}")
    else:
        print(f"✅ {key}: {py_val}")

if mismatch:
    print("\n⚠️  Port configs are out of sync. Update both files.")
    sys.exit(1)
else:
    print("\n✅ All ports synchronized.")
    sys.exit(0)
