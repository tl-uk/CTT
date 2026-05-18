# services/data-pipeline/fusion/Dockerfile
FROM python:3.13-slim

WORKDIR /app

# Install system deps for pyzmq
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libzmq3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY services/l2-bridge/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy entire project so imports (ports.py, protobuf) resolve
COPY . .

WORKDIR /app/services/data-pipeline/fusion
CMD ["python", "fusion_engine.py"]