# =============================================================================
# CTT L2 Bridge — Debian-based build
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
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY services/config/ /app/services/config/
COPY services/l2-bridge/ /app/services/l2-bridge/
COPY api/proto/ /app/api/proto/

WORKDIR /app/services/l2-bridge
CMD ["python", "dashboard.py"]