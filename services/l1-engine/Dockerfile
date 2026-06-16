# services/l1-engine/Dockerfile
# CTT L1 Engine — Multi-stage build with PCH and ccache support
# Phase 12: Added services/l7-kg/include/ to build context for SSN_Experience_Component

# =============================================================================
# Builder stage
# =============================================================================
FROM debian:bookworm-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build pkg-config \
    libzmq3-dev protobuf-compiler libprotobuf-dev \
    git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Phase 12: Copy L7-KG headers and L1 engine source together
# This ensures Docker invalidates the build layer when EITHER changes
COPY services/l7-kg/include/ /build/services/l7-kg/include/
COPY services/l1-engine/ /build/services/l1-engine/
COPY api/ /build/api/
COPY Makefile /build/

# Force CMake reconfigure by touching a marker file that includes both paths
# This ensures cmake detects header changes even if build/ directory is cached
RUN touch /build/services/l7-kg/include/ssn_experience_component.h && \
    cmake -B /build/services/l1-engine/build -S /build/services/l1-engine -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    && cmake --build /build/services/l1-engine/build --parallel $(nproc)

# =============================================================================
# Runtime stage
# =============================================================================
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libzmq5 libprotobuf32 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash ctt_user

WORKDIR /app

COPY --from=builder /build/services/l1-engine/build/CTT_Engine /app/CTT_Engine
COPY --from=builder /build/services/l1-engine/build/_deps/flecs-src/include/ /app/include/

USER ctt_user

EXPOSE 5555 27750

CMD ["./CTT_Engine"]
