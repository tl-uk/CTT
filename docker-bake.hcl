// =============================================================================
// CTT Project — Docker Bake Configuration
// Phase 12b: Fixed disk bloat — cache-to disabled by default
//
// Usage:
//   CTT_IMAGE_TAG=abc123 docker buildx bake        # Build all services
//   CTT_IMAGE_TAG=abc123 docker buildx bake engine  # Build specific service
//   CTT_IMAGE_TAG=abc123 docker buildx bake --print # Preview without building
//
// Variables are overridden via environment variables (per Docker Bake spec):
//   https://docs.docker.com/build/bake/reference/#variable
//
// Cache strategy (Phase 12b FIX):
//   - cache-to is DISABLED by default (prevents ~8GB/session bloat)
//   - cache-from is still enabled for incremental builds
//   - For CI/CD where cache persistence matters, override via:
//     docker buildx bake --set "*.cache-to=type=local,dest=/tmp/cache,mode=min"
//   - Git-SHA tags prevent dangling image accumulation
// =============================================================================

variable "CTT_IMAGE_TAG" {
  default = "latest"
}

variable "CACHE_DIR" {
  default = "/tmp/ctt-docker-cache"
}

// =============================================================================
// Shared base target (inherited by all services)
// =============================================================================

target "_common" {
  labels = {
    "org.opencontainers.image.source"   = "https://github.com/ctt-project/ctt"
    "org.opencontainers.image.revision" = CTT_IMAGE_TAG
    "org.opencontainers.image.created"  = timestamp()
  }
}

// =============================================================================
// Service Targets
// Each maps to a service in docker-compose.yml
//
// Phase 12b NOTE: cache-to is intentionally omitted from all targets.
// The Makefile's bake-build target passes --set "*.cache-to=" to disable
// export entirely. For cache-enabled builds, use `make bake-build` which
// reads from cache but does not export (or set cache-to explicitly).
// =============================================================================

target "engine" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/l1-engine/Dockerfile"
  tags = ["ctt-engine:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/engine"]
  // Phase 12b: cache-to disabled by default — prevents disk bloat
  // Override via: --set "engine.cache-to=type=local,dest=...,mode=min"
}

target "harvester" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/data-pipeline/ingestor/Dockerfile"
  tags = ["ctt-harvester:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/harvester"]
}

target "interpreter" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/data-pipeline/interpreter/Dockerfile"
  tags = ["ctt-interpreter:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/interpreter"]
}

target "fusion" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/data-pipeline/fusion/Dockerfile"
  tags = ["ctt-fusion:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/fusion"]
}

target "dashboard" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/l2-bridge/Dockerfile"
  tags = ["ctt-dashboard:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/dashboard"]
}

target "orchestrator" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/l2-orchestrator/Dockerfile"
  tags = ["ctt-orchestrator:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/orchestrator"]
}

// Phase 12: L5 services share one Dockerfile (single-stage, differentiated by command)
target "l5-macro" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/l5-macro/Dockerfile"
  tags = ["ctt-l5-macro:${CTT_IMAGE_TAG}", "ctt-audit-logger:${CTT_IMAGE_TAG}", "ctt-federation-bridge:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/l5-macro"]
}

// =============================================================================
// L7 Knowledge Graph (Phase 12)
// =============================================================================

target "kg-service" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/l7-kg/Dockerfile"
  tags = ["ctt-kg:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/kg"]
}

// =============================================================================
// Build Groups
// =============================================================================

group "default" {
  targets = [
    "engine", "harvester", "interpreter", "fusion",
    "dashboard", "orchestrator",
    "l5-macro"
  ]
}

group "pipeline" {
  targets = ["harvester", "interpreter", "fusion"]
}

group "l2" {
  targets = ["dashboard", "orchestrator"]
}

group "l5" {
  targets = ["l5-macro"]
}

group "all-with-kg" {
  targets = [
    "engine", "harvester", "interpreter", "fusion",
    "dashboard", "orchestrator",
    "l5-macro",
    "kg-service"
  ]
}

// Phase 12: Minimal test group (engine + kg only)
group "phase12-test" {
  targets = ["engine", "kg-service"]
}

// =============================================================================
// Phase 14a: SUMO Spatial Service
// =============================================================================

target "sumo" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/l4-spatial/Dockerfile"
  tags = ["ctt-sumo:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/sumo"]
}

// =============================================================================
// Updated Build Groups (Phase 14)
// =============================================================================

group "default" {
  targets = [
    "engine", "harvester", "interpreter", "fusion",
    "dashboard", "orchestrator",
    "l5-macro"
  ]
}

group "pipeline" {
  targets = ["harvester", "interpreter", "fusion"]
}

group "l2" {
  targets = ["dashboard", "orchestrator"]
}

group "l5" {
  targets = ["l5-macro"]
}

group "spatial" {
  targets = ["sumo"]
}

group "all-with-kg" {
  targets = [
    "engine", "harvester", "interpreter", "fusion",
    "dashboard", "orchestrator",
    "l5-macro",
    "kg-service",
    "sumo"
  ]
}

group "all-with-spatial" {
  targets = [
    "engine", "harvester", "interpreter", "fusion",
    "dashboard", "orchestrator",
    "l5-macro",
    "kg-service",
    "sumo"
  ]
}

// Phase 14: Minimal test group (engine + sumo)
group "phase14-test" {
  targets = ["engine", "sumo"]
}
