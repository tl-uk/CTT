# =============================================================================
# CTT L6 Gaia-X — Eclipse Dataspace Connector (EDC) Gateway Sidecar
# =============================================================================
# NOTE: This is a stub. Full EDC requires Java 17 + Maven build.
# For Phase 7 prototyping, we use a lightweight Python proxy that validates
# Self-Description headers and ODRL policies before forwarding to CTT ingestor.
# =============================================================================

FROM python:3.13-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libzmq5 \
    && rm -rf /var/lib/apt/lists/*

COPY services/l6-gaiax/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/config/ /app/services/config/
COPY services/l6-gaiax/ /app/services/l6-gaiax/

WORKDIR /app/services/l6-gaiax
CMD ["python", "edc_gateway.py"]
