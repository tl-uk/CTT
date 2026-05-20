# =============================================================================
# CTT L1 Engine — Multi-Platform Debian-based build
# =============================================================================

FROM debian:bookworm-slim AS builder

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
# Runtime stage with library verification
# -----------------------------------------------------------------------------
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libzmq5 \
    libprotobuf32 \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash ctt_user
USER ctt_user
WORKDIR /app

COPY --from=builder --chown=ctt_user:ctt_user /build/services/l1-engine/build/CTT_Engine /usr/local/bin/CTT_Engine

# Verify binary and libraries before running
RUN test -x /usr/local/bin/CTT_Engine && \
    ldd /usr/local/bin/CTT_Engine | grep -q "libzmq" && \
    ldd /usr/local/bin/CTT_Engine | grep -q "libprotobuf" && \
    echo "Binary verified"

EXPOSE 5555/tcp
EXPOSE 5556/tcp
EXPOSE 27750/tcp

ENTRYPOINT ["/usr/local/bin/CTT_Engine"]