# =============================================================================
# CTT L1 Engine — Multi-Platform Debian-based build
# Supports: linux/arm64 (Apple Silicon), linux/amd64 (Intel/AMD cloud)
# =============================================================================

# -----------------------------------------------------------------------------
# Build stage
# -----------------------------------------------------------------------------
FROM debian:bookworm-slim AS builder

ARG TARGETARCH
ARG BUILDARCH

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    ninja-build \
    pkg-config \
    libzmq3-dev \
    libprotobuf-dev \
    protobuf-compiler \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY services/l1-engine/ ./services/l1-engine/
COPY api/ ./api/
COPY Makefile ./

RUN make build-engine

# -----------------------------------------------------------------------------
# Runtime stage
# -----------------------------------------------------------------------------
FROM debian:bookworm-slim

ARG TARGETARCH

RUN apt-get update && apt-get install -y --no-install-recommends \
    libzmq5 \
    libprotobuf32 \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN useradd --create-home --shell /bin/bash ctt_user
USER ctt_user

WORKDIR /app

COPY --from=builder /build/services/l1-engine/build/CTT_Engine /usr/local/bin/CTT_Engine

EXPOSE 5555/tcp
EXPOSE 5556/tcp
EXPOSE 27750/tcp

ENTRYPOINT ["/usr/local/bin/CTT_Engine"]