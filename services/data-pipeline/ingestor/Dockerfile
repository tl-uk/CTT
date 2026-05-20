# =============================================================================
# CTT/services/data-pipeline/ingestor — Debian-based build
# =============================================================================

FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libzmq3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY services/l2-bridge/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY services/config/ /app/services/config/
COPY services/data-pipeline/ingestor/ /app/services/data-pipeline/ingestor/
COPY api/proto/ /app/api/proto/

WORKDIR /app/services/data-pipeline/ingestor
CMD ["python", "harvester.py"]