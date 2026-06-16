// =============================================================================
// CTT Project — Docker Bake Configuration
// Phase 11: Cache-efficient multi-service builds with local cache persistence
//
// Usage:
//   CTT_IMAGE_TAG=abc123 docker buildx bake        # Build all services
//   CTT_IMAGE_TAG=abc123 docker buildx bake engine  # Build specific service
//   CTT_IMAGE_TAG=abc123 docker buildx bake --print # Preview without building
//
// Variables are overridden via environment variables (per Docker Bake spec):
//   https://docs.docker.com/build/bake/reference/#variable
//
// Cache strategy:
//   - Local cache directory: /tmp/ctt-docker-cache (per service)
//   - mode=max caches all intermediate layers
//   - Cache survives across Colima restarts
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
// =============================================================================

target "engine" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/l1-engine/Dockerfile"
  tags = ["ctt-engine:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/engine"]
  cache-to   = ["type=local,dest=${CACHE_DIR}/engine,mode=max"]
}

target "harvester" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/data-pipeline/ingestor/Dockerfile"
  tags = ["ctt-harvester:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/harvester"]
  cache-to   = ["type=local,dest=${CACHE_DIR}/harvester,mode=max"]
}

target "interpreter" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/data-pipeline/interpreter/Dockerfile"
  tags = ["ctt-interpreter:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/interpreter"]
  cache-to   = ["type=local,dest=${CACHE_DIR}/interpreter,mode=max"]
}

target "fusion" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/data-pipeline/fusion/Dockerfile"
  tags = ["ctt-fusion:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/fusion"]
  cache-to   = ["type=local,dest=${CACHE_DIR}/fusion,mode=max"]
}

target "dashboard" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/l2-bridge/Dockerfile"
  tags = ["ctt-dashboard:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/dashboard"]
  cache-to   = ["type=local,dest=${CACHE_DIR}/dashboard,mode=max"]
}

target "orchestrator" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/l2-orchestrator/Dockerfile"
  tags = ["ctt-orchestrator:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/orchestrator"]
  cache-to   = ["type=local,dest=${CACHE_DIR}/orchestrator,mode=max"]
}

target "audit-logger" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/l5-macro/Dockerfile"
  target = "audit-logger"
  tags = ["ctt-audit-logger:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/audit-logger"]
  cache-to   = ["type=local,dest=${CACHE_DIR}/audit-logger,mode=max"]
}

target "federation-bridge" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/l5-macro/Dockerfile"
  target = "federation-bridge"
  tags = ["ctt-federation-bridge:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/federation-bridge"]
  cache-to   = ["type=local,dest=${CACHE_DIR}/federation-bridge,mode=max"]
}

// =============================================================================
// L7 Knowledge Graph (Phase 11)
// =============================================================================

target "kg-service" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/l7-kg/Dockerfile"
  tags = ["ctt-kg:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/kg"]
  cache-to   = ["type=local,dest=${CACHE_DIR}/kg,mode=max"]
}

// =============================================================================
// Build Groups
// =============================================================================

group "default" {
  targets = [
    "engine", "harvester", "interpreter", "fusion",
    "dashboard", "orchestrator",
    "audit-logger", "federation-bridge"
  ]
}

group "pipeline" {
  targets = ["harvester", "interpreter", "fusion"]
}

group "l2" {
  targets = ["dashboard", "orchestrator"]
}

group "l5" {
  targets = ["audit-logger", "federation-bridge"]
}

group "all-with-kg" {
  targets = [
    "engine", "harvester", "interpreter", "fusion",
    "dashboard", "orchestrator",
    "audit-logger", "federation-bridge",
    "kg-service"
  ]
}
