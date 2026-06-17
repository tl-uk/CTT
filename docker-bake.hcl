// =============================================================================
// CTT Project — Docker Bake Configuration
// Phase 12: Cache-efficient multi-service builds with local cache persistence
//
// Usage:
//   CTT_IMAGE_TAG=abc123 docker buildx bake        # Build all services
//   CTT_IMAGE_TAG=abc123 docker buildx bake engine  # Build specific service
//   CTT_IMAGE_TAG=abc123 docker buildx bake --print # Preview without building
//
// Variables are overridden via environment variables (per Docker Bake spec):
//   https://docs.docker.com/build/bake/reference/#variable
//
// Cache strategy (Phase 12 FIX):
//   - mode=min: only cache final layers (not intermediate build stages)
//   - This prevents the ~7GB/session bloat from mode=max
//   - Cache survives across Colima restarts but doesn't duplicate
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
  // Phase 12 FIX: mode=min prevents intermediate layer bloat
  cache-to   = ["type=local,dest=${CACHE_DIR}/engine,mode=min"]
}

target "harvester" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/data-pipeline/ingestor/Dockerfile"
  tags = ["ctt-harvester:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/harvester"]
  cache-to   = ["type=local,dest=${CACHE_DIR}/harvester,mode=min"]
}

target "interpreter" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/data-pipeline/interpreter/Dockerfile"
  tags = ["ctt-interpreter:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/interpreter"]
  cache-to   = ["type=local,dest=${CACHE_DIR}/interpreter,mode=min"]
}

target "fusion" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/data-pipeline/fusion/Dockerfile"
  tags = ["ctt-fusion:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/fusion"]
  cache-to   = ["type=local,dest=${CACHE_DIR}/fusion,mode=min"]
}

target "dashboard" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/l2-bridge/Dockerfile"
  tags = ["ctt-dashboard:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/dashboard"]
  cache-to   = ["type=local,dest=${CACHE_DIR}/dashboard,mode=min"]
}

target "orchestrator" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/l2-orchestrator/Dockerfile"
  tags = ["ctt-orchestrator:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/orchestrator"]
  cache-to   = ["type=local,dest=${CACHE_DIR}/orchestrator,mode=min"]
}

// Phase 12: L5 services share one Dockerfile (single-stage, differentiated by command)
target "l5-macro" {
  inherits = ["_common"]
  context = "."
  dockerfile = "services/l5-macro/Dockerfile"
  tags = ["ctt-l5-macro:${CTT_IMAGE_TAG}", "ctt-audit-logger:${CTT_IMAGE_TAG}", "ctt-federation-bridge:${CTT_IMAGE_TAG}"]
  cache-from = ["type=local,src=${CACHE_DIR}/l5-macro"]
  cache-to   = ["type=local,dest=${CACHE_DIR}/l5-macro,mode=min"]
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
  cache-to   = ["type=local,dest=${CACHE_DIR}/kg,mode=min"]
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