# =============================================================================
# CTT L5 Macro — Audit Logger & Federation Bridge
# Multi-stage build: compiles confluent-kafka against librdkafka
# =============================================================================

FROM python:3.13-slim AS builder

# Install build deps for confluent-kafka (librdkafka headers + gcc)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libzmq3-dev \
    librdkafka-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY services/l5-macro/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Runtime stage
# ---------------------------------------------------------------------------
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libzmq5 \
    librdkafka1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY services/config/ /app/services/config/
COPY services/l5-macro/ /app/services/l5-macro/
COPY api/proto/ /app/api/proto/

WORKDIR /app/services/l5-macro

# Default command overridden by docker-compose per service
CMD ["python", "audit_logger.py"]
