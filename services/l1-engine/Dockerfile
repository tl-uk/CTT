# =============================================================================
# CTT L1 Engine — Multi-Platform Debian-based build
# Location: services/l1-engine/Dockerfile
# =============================================================================

# ---------------------------------------------------------------------------
# Builder stage
# ---------------------------------------------------------------------------
FROM debian:bookworm-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        ninja-build \
        pkg-config \
        git \
        ca-certificates \
        libzmq3-dev \
        libprotobuf-dev \
        protobuf-compiler \
        libprotoc-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy source tree preserving structure for CMake
COPY services/l1-engine/ ./services/l1-engine/
COPY api/ ./api/
COPY Makefile ./

# Build — CMakeLists.txt is inside services/l1-engine/
RUN cmake -B services/l1-engine/build -S services/l1-engine -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    && cmake --build services/l1-engine/build --parallel $(nproc)

# Stage shared libraries built from source (flecs) for the runtime stage
RUN mkdir -p /build/stage/lib && \
    find /build/services/l1-engine/build -name "libflecs.so*" -exec cp -a {} /build/stage/lib/ \; && \
    ls -la /build/stage/lib/

# Verify binary exists
RUN test -x /build/services/l1-engine/build/CTT_Engine \
    && ldd /build/services/l1-engine/build/CTT_Engine \
    && echo "Binary verified"

# ---------------------------------------------------------------------------
# Runtime stage
# ---------------------------------------------------------------------------
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libzmq5 \
        libprotobuf32 \
        netcat-openbsd \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash ctt_user

WORKDIR /app

# Copy binary from builder — exact path must match build output
COPY --from=builder --chown=ctt_user:ctt_user \
    /build/services/l1-engine/build/CTT_Engine \
    /usr/local/bin/CTT_Engine

# Copy shared libraries built from source (flecs, etc.)
COPY --from=builder /build/stage/lib/ /usr/local/lib/
RUN ldconfig

# Verify binary and libraries before switching to non-root user
RUN test -x /usr/local/bin/CTT_Engine \
    && ldd /usr/local/bin/CTT_Engine | grep -q "libzmq" \
    && ldd /usr/local/bin/CTT_Engine | grep -q "libprotobuf" \
    && ldd /usr/local/bin/CTT_Engine | grep -q "libflecs" \
    && echo "Binary verified"

USER ctt_user

# Ports:
#   5555 — telemetry PUB (bind)
#   5556 — perturbation SUB (connects to fusion)
#   27750 — Flecs REST API
EXPOSE 5555/tcp
EXPOSE 27750/tcp

# Healthcheck — verify ZMQ pub socket is listening
HEALTHCHECK --interval=5s --timeout=2s --start-period=10s --retries=5 \
    CMD nc -z localhost 5555 || exit 1

ENTRYPOINT ["/usr/local/bin/CTT_Engine"]