# =============================================================================
# CTT L1 Engine — Debian-based build
# =============================================================================

# -----------------------------------------------------------------------------
# Build stage
# -----------------------------------------------------------------------------
FROM debian:bookworm-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    ninja-build \
    pkg-config \
    libzmq3-dev \
    libprotobuf-dev \
    protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy project root so Makefile and api/proto are accessible
COPY . .

# Build using the cross-platform Makefile
RUN make build-engine

# -----------------------------------------------------------------------------
# Runtime stage
# -----------------------------------------------------------------------------
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libzmq5 \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /build/services/l1-engine/build/CTT_Engine /usr/local/bin/CTT_Engine

# ZMQ telemetry out, ZMQ perturbations in, Flecs REST API
EXPOSE 5555/tcp
EXPOSE 5556/tcp
EXPOSE 27750/tcp

ENTRYPOINT ["/usr/local/bin/CTT_Engine"]