# =============================================================================
# CTT L2 Orchestrator — Multi-Protocol Federation Scheduler
# =============================================================================

FROM python:3.13-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libzmq5 \
    && rm -rf /var/lib/apt/lists/*

COPY services/l2-orchestrator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN pip install kafka-python pyzmq

COPY services/config/ /app/services/config/
COPY services/l2-orchestrator/ /app/services/l2-orchestrator/

WORKDIR /app/services/l2-orchestrator
CMD ["python", "orchestrator.py"]
