# services/l7-kg/Dockerfile
# CTT Phase 12-13: Layer 7 Knowledge Graph Service + BDI Engine
# Runs: kg_bridge.py (ZMQ bridge), sig_compressor.py, learn_mod.py
# Phase 13b: Also runs abdt_agent_cache_v2.py with BDI integration

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libzmq3-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY services/l7-kg/requirements.txt /app/services/l7-kg/
RUN pip install --no-cache-dir -r /app/services/l7-kg/requirements.txt

# Phase 13b: All L7 Python modules (including BDI)
COPY services/l7-kg/*.py /app/services/l7-kg/
COPY services/config/ports.py /app/services/config/
COPY services/config/settings.py /app/services/config/

# Set Python path
ENV PYTHONPATH=/app/services/config:/app/services/l7-kg

# Phase 13b: Default command runs KG bridge
# Override via docker-compose for abdt-cache-v2:
#   command: python services/l7-kg/abdt_agent_cache_v2.py
CMD ["python", "-u", "services/l7-kg/kg_bridge.py"]