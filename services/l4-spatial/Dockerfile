# services/l4-spatial/Dockerfile
# CTT Phase 14a: SUMO Spatial Service — MMOG Zone Server
# Uses libsumo (C++ API) for zero socket overhead vs TraCI

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install SUMO + dependencies
RUN apt-get update && apt-get install -y --no-install-recommends     sumo sumo-tools libsumo-dev     python3 python3-pip     netcat-openbsd     && rm -rf /var/lib/apt/lists/*

# Set SUMO_HOME
ENV SUMO_HOME=/usr/share/sumo
ENV PYTHONPATH=/usr/share/sumo/tools:/app/services/config:/app/services/l4-spatial

WORKDIR /app

# Copy requirements first for layer caching
COPY services/l4-spatial/requirements.txt /app/services/l4-spatial/
RUN pip3 install --no-cache-dir -r /app/services/l4-spatial/requirements.txt

# Copy source code
COPY services/l4-spatial/*.py /app/services/l4-spatial/
COPY services/config/ports.py /app/services/config/
COPY services/config/settings.py /app/services/config/

# Default: run the SUMO bridge for the configured corridor
CMD ["python3", "-u", "services/l4-spatial/sumo_bridge.py"]