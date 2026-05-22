# =============================================================================
# CTT/services/data-pipeline/interpreter — Debian-based build
# =============================================================================

FROM python:3.13-slim AS builder

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libzmq3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY services/l2-bridge/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.13-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libzmq5 \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY services/config/ /app/services/config/
COPY services/data-pipeline/interpreter/ /app/services/data-pipeline/interpreter/

WORKDIR /app/services/data-pipeline/interpreter
CMD ["python", "semantic_agent.py"]