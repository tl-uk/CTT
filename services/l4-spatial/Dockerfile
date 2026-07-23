# =============================================================================
# CTT Phase 14a: Layer 4 Spatial — SUMO/libsumo Bridge
# MMOG Analogy: Zone Server (physics engine for one corridor)
# =============================================================================

FROM ubuntu:22.04 AS sumo-builder

ENV DEBIAN_FRONTEND=noninteractive
ENV SUMO_VERSION=1.22.0

# Install SUMO + libsumo dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    sumo sumo-tools libsumo-dev \
    libxerces-c3.2 libproj22 libgdal30 \
    python3 python3-pip python3-dev \
    gcc g++ libzmq3-dev \
    && rm -rf /var/lib/apt/lists/*

# Ensure SUMO tools are available
ENV SUMO_HOME=/usr/share/sumo
ENV PYTHONPATH="/usr/share/sumo/tools:${PYTHONPATH}"

# ---------------------------------------------------------------------------
# Python dependencies
# ---------------------------------------------------------------------------
WORKDIR /app
COPY services/l4-spatial/requirements.txt /app/services/l4-spatial/
RUN pip install --no-cache-dir -r /app/services/l4-spatial/requirements.txt

# ---------------------------------------------------------------------------
# Copy source
# ---------------------------------------------------------------------------
COPY services/config/ /app/services/config/
COPY services/l4-spatial/*.py /app/services/l4-spatial/
COPY deploy/osm-networks/ /app/deploy/osm-networks/

ENV PYTHONPATH=/app/services/config:/app/services/l4-spatial:/usr/share/sumo/tools
WORKDIR /app/services/l4-spatial

# Default: run bridge for corridor (overridden by docker-compose per instance)
CMD ["python", "-u", "sumo_bridge.py"]
