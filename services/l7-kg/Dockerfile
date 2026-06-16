# services/l7-kg/Dockerfile
# CTT Phase 12 — Layer 7 Knowledge Graph Service
# Runs: kg_bridge.py (ZMQ bridge), sig_compressor.py, learn_mod.py

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libzmq3-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY services/l7-kg/requirements.txt /app/services/l7-kg/
RUN pip install --no-cache-dir -r /app/services/l7-kg/requirements.txt

# Copy source code
COPY services/l7-kg/*.py /app/services/l7-kg/
COPY services/config/ports.py /app/services/config/
COPY services/config/settings.py /app/services/config/

# Set Python path
ENV PYTHONPATH=/app/services/config:/app/services/l7-kg

# Default: run the KG bridge
CMD ["python", "-u", "services/l7-kg/kg_bridge.py"]