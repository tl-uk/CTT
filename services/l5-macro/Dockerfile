# services/l5-macro/Dockerfile
# Phase 6 — L5 Macro: Kafka Audit + Federation Bridge (Apple Silicon / ARM64)

FROM python:3.11-slim

WORKDIR /app

# Unbuffered stdout so docker logs -f shows prints immediately
ENV PYTHONUNBUFFERED=1

# Install librdkafka headers + build tools for confluent-kafka Python wheel
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    librdkafka-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    confluent-kafka \
    pyzmq \
    python-dotenv

# Copy shared configuration
COPY services/config /app/services/config

# Copy L5 macro modules
COPY services/l5-macro /app/services/l5-macro

WORKDIR /app/services/l5-macro
# Default to audit_logger; overridden by docker-compose command
CMD ["python", "audit_logger.py"]