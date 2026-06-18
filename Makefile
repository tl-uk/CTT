# =============================================================================
# CTT Project — Cross-Platform Build Orchestration (macOS / Linux / Docker)
# Phase 12: Docker Bake integration, cache-efficient builds, disk management
# =============================================================================

.PHONY: help all check-deps configure-engine build-engine run-engine run-engine-fast         run-engine-bg clean-engine setup-python setup-l3 run-dashboard run-dashboard-bg         run-explorer run-explorer-bg         run-harvester run-interpreter run-fusion         run-harvester-bg run-interpreter-bg run-fusion-bg         test-bridge test-e2e test-pipeline stop-pipeline stop-native healthcheck         check-ports proto proto-clean fmt-engine lint-engine docker-engine         compose-build compose-up compose-down compose-logs compose-ps         bake-build bake-list bake-prune docker-compact colima-compact         compose-up-bake compose-up-kg test-multi-domain

# Detect CPU cores for parallel builds
NPROCS := $(shell nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)

# =============================================================================
# Phase 11: Git-SHA Image Tagging (prevents dangling accumulation)
# =============================================================================
GIT_SHA := $(shell git rev-parse --short HEAD 2>/dev/null || echo "unknown")
CTT_IMAGE_TAG ?= $(GIT_SHA)
BAKE_FILE := docker-bake.hcl
CACHE_DIR := /tmp/ctt-docker-cache

# =============================================================================
# Service directories
# NOTE: Directory names predate the formal 5-layer architecture.
#       L1_DIR  = physical path services/l1-engine  → conceptually Layer 3 (Cognitive Core)
#       L2_DIR  = physical path services/l2-bridge  → conceptually Layer 2 (Orchestration)
#       L3_DIR  = physical path services/l3-analytics → conceptually Layer 5 (Macro Analytics)
# =============================================================================
L1_DIR     := services/l1-engine
L2_DIR     := services/l2-bridge
L3_DIR     := services/l3-analytics
L4_DIR     := services/l4-spatial
L5_DIR     := services/l5-macro
L7_DIR     := services/l7-kg
BUILD_DIR  := $(L1_DIR)/build
CONFIG_DIR := services/config

# =============================================================================
# Platform Detection (macOS vs Linux/Docker)
# =============================================================================
UNAME_S := $(shell uname -s)
UNAME_M := $(shell uname -m)

ifeq ($(UNAME_S),Darwin)
    CMAKE_PLATFORM_ARGS := -DCMAKE_OSX_ARCHITECTURES=$(UNAME_M)
    ifeq ($(UNAME_M),arm64)
        ZMQ_PREFIX ?= /opt/homebrew/opt/zeromq
    else
        ZMQ_PREFIX ?= /usr/local/opt/zeromq
    endif
    CMAKE_EXTRA := -DCMAKE_PREFIX_PATH=$(ZMQ_PREFIX)
else
    # Linux / Docker — standard system paths via pkg-config
    CMAKE_PLATFORM_ARGS :=
    CMAKE_EXTRA :=
endif

# =============================================================================
# Python Tooling Detection (uv preferred, falls back to venv+pip)
# =============================================================================
HAS_UV := $(shell which uv 2>/dev/null)
PYTHON_VENV_CMD  := $(if $(HAS_UV),uv venv --python 3.13,python3 -m venv .venv)
PYTHON_PIP_CMD   := $(if $(HAS_UV),uv pip install,.venv/bin/pip install)
PYTHON_BIN       := $(L2_DIR)/.venv/bin/python

# =============================================================================
# Help
# =============================================================================

help: ## Show this help message
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║           CTT Project — Build & Run Commands                 ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "═══ Native Build ═══"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \		awk 'BEGIN {FS = ":.*?## "}; {printf "  \\033[36m%-24s\\033[0m %s\\n", $$1, $$2}' | grep -E "(check-deps|build-engine|run-engine|setup-python|setup-l3|setup-l5|setup-l7)"
	@echo ""
	@echo "═══ Docker / Bake (Phase 11) ═══"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \		awk 'BEGIN {FS = ":.*?## "}; {printf "  \\033[36m%-24s\\033[0m %s\\n", $$1, $$2}' | grep -E "(bake-|docker-|compose-|colima-)"
	@echo ""
	@echo "═══ Testing ═══"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \		awk 'BEGIN {FS = ":.*?## "}; {printf "  \\033[36m%-24s\\033[0m %s\\n", $$1, $$2}' | grep -E "(test-|healthcheck|check-ports)"
	@echo ""
	@echo "═══ Disk Management ═══"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \		awk 'BEGIN {FS = ":.*?## "}; {printf "  \\033[36m%-24s\\033[0m %s\\n", $$1, $$2}' | grep -E "(prune|compact|nuke|df)"
	@echo ""
	@echo "Quick start (native):"
	@echo "  1. make check-deps     → Verify dependencies"
	@echo "  2. make build-engine   → Compile the C++ L1 Engine"
	@echo "  3. make run-engine-bg  → Launch Engine in background"
	@echo "  4. make setup-python   → Prepare L2 Bridge environment"
	@echo "  5. make test-e2e       → Verify full pipeline"
	@echo ""
	@echo "Docker / Bake (cache-efficient):"
	@echo "  make bake-build        → Build all services via docker-bake.hcl"
	@echo "  make compose-up-bake   → Launch full stack with baked images"
	@echo "  make test-multi-domain → Run multi-domain E2E with smart builds"
	@echo ""
	@echo "Disk management:"
	@echo "  make docker-df         → Show disk usage"
	@echo "  make docker-compact    → Compact Colima VM disk (non-destructive)"
	@echo "  make colima-nuke       → Nuclear reset (destructive, reclaims all)"
	@echo ""

# =============================================================================
# Internal Helpers
# =============================================================================

define check-port-free
	@if lsof -i :$(1) >/dev/null 2>&1; then echo "❌ Port $(1) already in use. Run make stop-native first."; exit 1; else echo "✅ Port $(1) is free for $(2)"; fi
endef

define wait-for-port
	@echo "⏳ Waiting for $(2) to bind port $(1)..."
	@for i in $$(seq 1 25); do if nc -z localhost $(1) 2>/dev/null; then echo "✅ $(2) is listening on $(1)"; exit 0; fi; sleep 0.2; done; echo "❌ $(2) failed to bind port $(1) within 5s"; exit 1
endef

# =============================================================================
# Phase 12: Docker Bake Targets (Cache-Efficient Builds)
# =============================================================================

bake-list: ## List all bake targets and groups
	@echo "📋 Docker Bake targets:"
	@docker buildx bake -f $(BAKE_FILE) --list=targets 2>/dev/null || \		echo "   (docker buildx not available or bake file missing)"

# Phase 12 FIX: Per-service cache directories with mode=min to prevent bloat
# mode=min only caches final layers, not intermediate build stages
BAKE_SERVICES := engine harvester interpreter fusion dashboard orchestrator l5-macro kg-service

bake-build: ## Build all services via docker-bake.hcl (cache-efficient, mode=min)
	@echo "🔨 Building CTT services with docker-bake.hcl..."
	@echo "   Tag: $(CTT_IMAGE_TAG)"
	@echo "   Cache: $(CACHE_DIR) (mode=min — no intermediate layer bloat)"
	@echo "   Tip: If headers changed but build is cached, run: make bake-build-force"
	@mkdir -p $(CACHE_DIR)/engine $(CACHE_DIR)/harvester $(CACHE_DIR)/interpreter \		$(CACHE_DIR)/fusion $(CACHE_DIR)/dashboard $(CACHE_DIR)/orchestrator \		$(CACHE_DIR)/audit-logger $(CACHE_DIR)/federation-bridge $(CACHE_DIR)/kg-service
	@docker buildx bake -f $(BAKE_FILE) --load \		--allow=fs=/private/tmp \		--set "*.args.CTT_IMAGE_TAG=$(CTT_IMAGE_TAG)"
	@echo "✅ Bake build complete (tag: $(CTT_IMAGE_TAG))"

# Phase 12 FIX: Force rebuild with explicit target list (avoids empty target error)
bake-build-force: ## Force rebuild all services (no cache — use after header changes)
	@echo "🔨 Force-building CTT services (no cache)..."
	@rm -rf $(CACHE_DIR)/*
	@docker buildx bake -f $(BAKE_FILE) --load --set "*.no-cache=true" --set "*.cache-from=" --allow=fs=/private/tmp --set "*.args.CTT_IMAGE_TAG=$(CTT_IMAGE_TAG)" all-with-kg
	@echo "✅ Force build complete (tag: $(CTT_IMAGE_TAG))"
bake-build-%: ## Build specific service via bake (e.g., make bake-build-engine)
	@echo "🔨 Building service: $* (tag: $(CTT_IMAGE_TAG))"
	@mkdir -p $(CACHE_DIR)/$*
	@docker buildx bake -f $(BAKE_FILE) --load $* \		--allow=fs=/private/tmp \		--set "$*.args.CTT_IMAGE_TAG=$(CTT_IMAGE_TAG)"
	@echo "✅ $* built (tag: $(CTT_IMAGE_TAG))"


# Phase 12 NEW: Validate engine image has required runtime dependencies
validate-engine-image: ## Verify ctt-engine image has nc and libflecs.so
	@echo "🔍 Validating ctt-engine image..."
	@nc_check=$$(docker run --rm ctt-engine:$(CTT_IMAGE_TAG) which nc 2>/dev/null) || true
	@flecs_check=$$(docker run --rm ctt-engine:$(CTT_IMAGE_TAG) ldd /app/CTT_Engine 2>/dev/null | grep flecs) || true
	@if [ -z "$$nc_check" ]; then echo "❌ nc MISSING"; echo "   Run: make bake-build-force"; exit 1; fi
	@if [ -z "$$flecs_check" ]; then echo "❌ libflecs.so MISSING"; echo "   Run: make bake-build-force"; exit 1; fi
	@echo "✅ Engine validated: nc=$$nc_check, flecs=$$flecs_check"

# Phase 12 FIX: Prune only removes unused cache; does not touch bake cache dirs
bake-prune: ## Prune Docker builder cache (frees disk without destroying images)
	@echo "🧹 Pruning Docker builder cache..."
	@docker builder prune -f --filter unused-for=24h
	@echo "✅ Builder cache pruned"

# Phase 12 NEW: Deep cache cleanup — removes ALL build cache + bake cache dirs
bake-prune-deep: ## Deep prune: remove ALL build cache + bake cache dirs (emergency)
	@echo "💥 Deep pruning ALL build cache..."
	@docker builder prune -f
	@docker system prune -f --volumes 2>/dev/null || true
	@rm -rf $(CACHE_DIR)/*
	@echo "✅ All build cache removed (builder + bake dirs + dangling)"
	@make docker-df
# =============================================================================
# Phase 11: Docker Compose with Bake Integration
# =============================================================================

COMPOSE_FILE := deploy/docker-compose.yml

compose-up-bake: bake-build ## Build via bake, then launch full stack
	@echo "🚀 Starting CTT stack with pre-built images (tag: $(CTT_IMAGE_TAG))..."
	@CTT_IMAGE_TAG=$(CTT_IMAGE_TAG) docker-compose -f $(COMPOSE_FILE) up -d
	@echo "✅ Stack started. Dashboard: http://localhost:5001"

compose-up-kg: bake-build-force ## Build via bake (force, no cache), then launch
	@echo "🚀 Starting CTT stack + L7 Knowledge Graph (tag: $(CTT_IMAGE_TAG))..."
	@docker buildx bake -f $(BAKE_FILE) --load kg-service --set "kg-service.args.CTT_IMAGE_TAG=$(CTT_IMAGE_TAG)"
	@CTT_IMAGE_TAG=$(CTT_IMAGE_TAG) docker-compose -f $(COMPOSE_FILE) build --no-cache engine
	@CTT_IMAGE_TAG=$(CTT_IMAGE_TAG) docker-compose -f $(COMPOSE_FILE) up -d
	@echo "✅ Stack + KG started. Dashboard: http://localhost:5001"
# Phase 12 FIX: compose-down now auto-prunes to prevent disk bloat
compose-down: ## Stop and remove CTT stack + prune builder cache
	@echo "🛑 Stopping CTT stack..."
	@docker-compose -f $(COMPOSE_FILE) down
	@echo "🧹 Pruning builder cache..."
	@docker builder prune -f --filter unused-for=24h
	@rm -rf $(CACHE_DIR)/*
	@echo "✅ Stack stopped + cache pruned"
compose-build: ## Build all services via docker-compose (fallback, no bake)
	@echo "🔨 Building CTT stack via docker-compose..."
	@CTT_IMAGE_TAG=$(CTT_IMAGE_TAG) docker-compose -f $(COMPOSE_FILE) build

compose-up: ## Start CTT stack in detached mode (uses compose build)
	@echo "🚀 Starting CTT stack..."
	@CTT_IMAGE_TAG=$(CTT_IMAGE_TAG) docker-compose -f $(COMPOSE_FILE) up -d

compose-logs: ## Tail fusion logs
	@docker-compose -f $(COMPOSE_FILE) logs -f fusion

compose-ps: ## Show running services
	@docker-compose -f $(COMPOSE_FILE) ps

# ---------------------------------------------------------------------------
# Phase 11: Multi-Domain E2E Test with Smart Builds
# ---------------------------------------------------------------------------

test-multi-domain: ## Run multi-domain E2E with cache-efficient builds
	@echo "🧪 Running multi-domain E2E (Phase 11 smart builds)..."
	@cd scripts && PYTHONPATH="../services/config" python test_multi_domain.py \		--domain-a domain-dft --domain-b domain-dhl \		--tag $(CTT_IMAGE_TAG)

# ---------------------------------------------------------------------------
# Docker Compose — Redpanda variant (disk rescue)
# ---------------------------------------------------------------------------
COMPOSE_REDPANDA := deploy/docker-compose-redpanda.yml

compose-up-redpanda: ## Start CTT stack with Redpanda instead of Kafka+Zookeeper
	@echo "🚀 Starting CTT stack (Redpanda variant)..."
	@docker-compose -f $(COMPOSE_REDPANDA) up --build -d

compose-down-redpanda: ## Stop Redpanda variant stack
	@echo "🛑 Stopping CTT stack (Redpanda variant)..."
	@docker-compose -f $(COMPOSE_REDPANDA) down

compose-logs-redpanda: ## Tail Redpanda variant logs
	@docker-compose -f $(COMPOSE_REDPANDA) logs -f

# =============================================================================
# L1 Engine — C++ Flecs Core
# =============================================================================

check-deps: ## Verify system dependencies (cmake, ninja, pkg-config, zeromq)
	@echo "🔍 Checking system dependencies..."
	@which cmake >/dev/null 2>&1 || (echo "❌ cmake not found. Install: apt install cmake ninja-build pkg-config" && exit 1)
	@which ninja >/dev/null 2>&1 || (echo "❌ ninja not found. Install: apt install ninja-build" && exit 1)
	@which pkg-config >/dev/null 2>&1 || (echo "❌ pkg-config not found. Install: apt install pkg-config" && exit 1)
ifeq ($(UNAME_S),Darwin)
	@test -d $(ZMQ_PREFIX)/lib || (echo "❌ zeromq not found at $(ZMQ_PREFIX). Run: brew install zeromq" && exit 1)
else
	@pkg-config --exists libzmq || (echo "❌ libzmq not found. Run: apt install libzmq3-dev" && exit 1)
endif
	@echo "✅ All system dependencies found"

configure-engine: check-deps ## Configure CMake for L1 Engine (clean configure)
	@echo "⚙️  Configuring L1 Engine..."
	@echo "   L1_DIR     = '$(L1_DIR)'"
	@echo "   BUILD_DIR  = '$(BUILD_DIR)'"
	@if [ -z "$(BUILD_DIR)" ]; then \		echo "❌ BUILD_DIR is empty. Aborting."; \		exit 1; \	fi
	@if [ "$(BUILD_DIR)" = "$(L1_DIR)" ]; then \		echo "❌ BUILD_DIR equals L1_DIR. Refusing to delete source tree."; \		exit 1; \	fi
	@if [ -L "$(BUILD_DIR)" ]; then \		echo "⚠️  $(BUILD_DIR) is a symlink. Removing symlink only."; \		rm -f "$(BUILD_DIR)"; \	elif [ -e "$(BUILD_DIR)" ]; then \		echo "   Removing existing build directory..."; \		rm -rf "$(BUILD_DIR)"; \	fi
	@cmake -B "$(BUILD_DIR)" -S "$(L1_DIR)" -G Ninja \		-DCMAKE_BUILD_TYPE=Release \		$(CMAKE_PLATFORM_ARGS) \		$(CMAKE_EXTRA) \		-DCMAKE_POLICY_VERSION_MINIMUM=3.5
	@echo "✅ Configure complete"

build-engine: configure-engine ## Build the C++ L1 Engine with all cores
	@echo "🔨 Building L1 Engine with $(NPROCS) cores..."
	@cmake --build "$(BUILD_DIR)" --parallel $(NPROCS)
	@echo ""
	@echo "✅ Build complete: $(BUILD_DIR)/CTT_Engine"
	@echo ""

run-engine: build-engine ## Build and run the L1 Engine (blocks terminal)
	@echo "🚀 Starting CTT L1 Engine..."
	@echo "   REST API:    http://localhost:27750"
	@echo "   ZMQ Pub:     tcp://localhost:5555  (telemetry)"
	@echo "   ZMQ Sub:     tcp://localhost:5556  (perturbations — Fusion binds here)"
	@echo ""
	@./$(BUILD_DIR)/CTT_Engine

run-engine-bg: build-engine ## Run L1 Engine in background (logs to /tmp)
	$(call check-port-free,5555,engine)
	$(call check-port-free,27750,engine-rest)
	@nohup ./$(BUILD_DIR)/CTT_Engine > /tmp/ctt_engine.log 2>&1 &
	@echo "🚀 Engine backgrounded (log: /tmp/ctt_engine.log)"
	@$(call wait-for-port,5555,engine)

run-engine-fast: ## Run L1 Engine WITHOUT rebuilding (blocks terminal)
	@if [ ! -f $(BUILD_DIR)/CTT_Engine ]; then \		echo "❌ Engine not built. Run 'make build-engine' first."; \		exit 1; \	fi
	@echo "🚀 Starting CTT L1 Engine (fast mode, no rebuild)..."
	@./$(BUILD_DIR)/CTT_Engine

clean-engine: ## Remove L1 Engine build artifacts (defensive)
	@echo "🧹 Cleaning L1 Engine build..."
	@echo "   BUILD_DIR = '$(BUILD_DIR)'"
	@echo "   L1_DIR    = '$(L1_DIR)'"
	@if [ -z "$(BUILD_DIR)" ]; then \		echo "❌ BUILD_DIR is empty. Aborting."; \		exit 1; \	fi
	@if [ "$(BUILD_DIR)" = "$(L1_DIR)" ]; then \		echo "❌ BUILD_DIR equals L1_DIR. Refusing to delete source tree."; \		exit 1; \	fi
	@if [ -L "$(BUILD_DIR)" ]; then \		echo "⚠️  $(BUILD_DIR) is a symlink. Removing symlink only."; \		rm -f "$(BUILD_DIR)"; \	elif [ -e "$(BUILD_DIR)" ]; then \		rm -rf "$(BUILD_DIR)"; \	else \		echo "   Build directory does not exist — nothing to clean."; \	fi
	@echo "✅ Clean complete"

docker-engine: ## Build L1 Engine Docker image (legacy, use bake-build instead)
	@echo "⚠️  Consider using 'make bake-build-engine' for cache efficiency"
	@which docker >/dev/null 2>&1 || { \		echo "❌ Docker binary not found in PATH."; \		echo "   macOS:  brew install docker colima"; \		echo "   Linux:  https://docs.docker.com/get-docker/"; \		echo "   Or build natively: make build-engine"; \		exit 1; \	}
	@docker info >/dev/null 2>&1 || { \		echo "❌ Docker daemon is not running."; \		echo ""; \		echo "   If you use Colima:"; \		echo "      colima start --cpu 4 --memory 8"; \		echo ""; \		echo "   If you use Docker Desktop:"; \		echo "      Open Docker Desktop from Applications and wait for the whale icon."; \		echo ""; \		echo "   Or build natively: make build-engine"; \		exit 1; \	}
	@echo "🐳 Building L1 Engine Docker image..."
	@docker build -f $(L1_DIR)/Dockerfile -t ctt-engine:$(CTT_IMAGE_TAG) .
	@echo "✅ Docker image ctt-engine:$(CTT_IMAGE_TAG) built"

# =============================================================================
# L2 Bridge — Python Telemetry & Dashboard
# =============================================================================

setup-python: ## Create Python venv and install L2 Bridge dependencies
	@echo "🐍 Setting up Python environment for L2 Bridge..."
	@cd $(L2_DIR) && $(PYTHON_VENV_CMD)
	@cd $(L2_DIR) && $(PYTHON_PIP_CMD) -r requirements.txt
	@echo "✅ Python environment ready in $(L2_DIR)/.venv"

run-dashboard: ## Run the L2 Bridge dashboard (requires engine running)
	@echo "📊 Starting L2 Bridge dashboard..."
	@cd $(L2_DIR) && . .venv/bin/activate && PYTHONPATH="$(CONFIG_DIR)" python dashboard.py

run-dashboard-bg: ## Run the L2 Bridge dashboard in background (logs to /tmp)
	$(call check-port-free,5001,dashboard)
	@cd $(L2_DIR) && . .venv/bin/activate && PYTHONPATH="$(CONFIG_DIR)" nohup python dashboard.py > /tmp/ctt_dashboard.log 2>&1 &
	@echo "📊 Dashboard backgrounded (log: /tmp/ctt_dashboard.log)"
	@$(call wait-for-port,5001,dashboard)

# L2 Orchestrator (separate container or native)
# ---------------------------------------------------------------------------
run-orchestrator-bg: ## Run L2 Orchestrator in background (native)
	@echo "🧠 Starting L2 Orchestrator..."
	@cd $(L2_DIR) && . .venv/bin/activate && PYTHONPATH="$(CONFIG_DIR)" nohup python orchestrator.py > /tmp/ctt_orchestrator.log 2>&1 &
	@echo "🧠 Orchestrator backgrounded (log: /tmp/ctt_orchestrator.log)"

# =============================================================================
# L3 Analytics — Python Data Science & ML
# =============================================================================

setup-l3: ## Setup L3 Analytics environment
	@echo "🐍 Setting up L3 Analytics..."
	@cd $(L3_DIR) && $(PYTHON_VENV_CMD)
	@cd $(L3_DIR) && $(PYTHON_PIP_CMD) -r requirements.txt

# =============================================================================
# L5 Macro — Native Python (for debugging outside Docker)
# =============================================================================
setup-l5: ## Setup L5 Macro Python environment
	@echo "🐍 Setting up L5 Macro environment..."
	@cd services/l5-macro && $(PYTHON_VENV_CMD)
	@cd services/l5-macro && $(PYTHON_PIP_CMD) -r requirements.txt

run-audit-logger: ## Run audit logger natively (requires Kafka/Redpanda running)
	@echo "📝 Starting Audit Logger..."
	@cd services/l5-macro && . .venv/bin/activate && PYTHONPATH="$(CONFIG_DIR):." python audit_logger.py

run-federation-bridge: ## Run federation bridge natively
	@echo "🏛️ Starting Federation Bridge..."
	@cd services/l5-macro && . .venv/bin/activate && PYTHONPATH="$(CONFIG_DIR):." python federation_bridge.py

# =============================================================================
# L7 Knowledge Graph — Setup & Run
# =============================================================================

setup-l7: ## Setup L7 Knowledge Graph Python environment
	@echo "🧠 Setting up L7 Knowledge Graph..."
	@cd $(L7_DIR) && $(PYTHON_VENV_CMD)
	@cd $(L7_DIR) && $(PYTHON_PIP_CMD) -r requirements.txt
	@echo "✅ L7 environment ready"

run-kg-bridge: ## Run L7 KG bridge natively (requires engine running)
	@echo "🌉 Starting L7 KG Bridge..."
	@cd $(L7_DIR) && . .venv/bin/activate && PYTHONPATH="$(CONFIG_DIR):." python kg_bridge.py

run-learn-mod: ## Run L7 Emergent Learning Module
	@echo "📊 Starting L7 Learning Module..."
	@cd $(L7_DIR) && . .venv/bin/activate && PYTHONPATH="$(CONFIG_DIR):." python learn_mod.py

# =============================================================================
# Data Pipeline — Inbound Refinery
# =============================================================================

run-harvester: ## Run the mock SME Harvester (Ingestor) — foreground
	@echo "📡 Starting SME Harvester..."
	@cd $(L2_DIR) && . .venv/bin/activate && PYTHONPATH="$(CONFIG_DIR)" python ../data-pipeline/ingestor/harvester.py

run-interpreter: ## Run the Semantic Agent (Interpreter) — foreground
	@echo "🧠 Starting Semantic Interpreter..."
	@cd $(L2_DIR) && . .venv/bin/activate && PYTHONPATH="$(CONFIG_DIR)" python ../data-pipeline/interpreter/semantic_agent.py

run-fusion: ## Run the Fusion Engine (Command & Control) — foreground
	@echo "⚡ Starting Fusion Engine..."
	@cd $(L2_DIR) && . .venv/bin/activate && PYTHONPATH="$(CONFIG_DIR):../data-pipeline/fusion" python ../data-pipeline/fusion/fusion_engine.py

# Background variants with port conflict checks and startup verification
run-harvester-bg: ## Run harvester in background (logs to /tmp)
	$(call check-port-free,5560,harvester)
	@cd $(L2_DIR) && . .venv/bin/activate && PYTHONPATH="$(CONFIG_DIR)" nohup python ../data-pipeline/ingestor/harvester.py > /tmp/ctt_harvester.log 2>&1 &
	@echo "📡 Harvester backgrounded (log: /tmp/ctt_harvester.log)"
	@$(call wait-for-port,5560,harvester)

run-interpreter-bg: ## Run interpreter in background
	$(call check-port-free,5561,interpreter)
	@cd $(L2_DIR) && . .venv/bin/activate && PYTHONPATH="$(CONFIG_DIR)" nohup python ../data-pipeline/interpreter/semantic_agent.py > /tmp/ctt_interpreter.log 2>&1 &
	@echo "🧠 Interpreter backgrounded (log: /tmp/ctt_interpreter.log)"
	@$(call wait-for-port,5561,interpreter)

run-fusion-bg: ## Run fusion in background
	$(call check-port-free,5556,fusion)
	@cd $(L2_DIR) && . .venv/bin/activate && PYTHONPATH="$(CONFIG_DIR):../data-pipeline/fusion" nohup python ../data-pipeline/fusion/fusion_engine.py > /tmp/ctt_fusion.log 2>&1 &
	@echo "⚡ Fusion backgrounded (log: /tmp/ctt_fusion.log)"
	@$(call wait-for-port,5556,fusion)

# =============================================================================
# Testing & Verification
# =============================================================================

check-ports: ## Validate Python/C++ port configs are synchronized
	@echo "🔍 Validating port configuration sync..."
	@cd $(L2_DIR) && . .venv/bin/activate && PYTHONPATH="$(CONFIG_DIR)" python $(CONFIG_DIR)/validate_ports.py

healthcheck: ## Quick check: are all expected ports listening?
	@echo "🏥 CTT Healthcheck"
	@echo "────────────────────────────────────────"
	@echo "Component          | Port | Status"
	@echo "────────────────────────────────────────"
	@for port in 5555 5556 5560 5561 5001; do if nc -z localhost $$port 2>/dev/null; then status="✅ UP"; else status="⬜ DOWN"; fi; case $$port in 5555) echo "L1 Engine (telemetry) | 5555 | $$status" ;; 5556) echo "Fusion (perturbations)| 5556 | $$status" ;; 5560) echo "Harvester (raw data)  | 5560 | $$status" ;; 5561) echo "Interpreter (mapped)  | 5561 | $$status" ;; 5001) echo "Dashboard (REST API)  | 5001 | $$status" ;; esac; done
	@echo "────────────────────────────────────────"
test-e2e: ## Run end-to-end pipeline test (requires engine running)
	@echo "🧪 Running end-to-end pipeline test..."
	@cd $(L2_DIR) && . .venv/bin/activate && PYTHONPATH="$(CONFIG_DIR):../data-pipeline/fusion" python ../../scripts/test_e2e.py --mode standalone

test-bridge: ## Launch full data pipeline in background + run E2E test
	@echo "🔄 Launching pipeline for integration test..."
	@make stop-native >/dev/null 2>&1 || true
	@sleep 1
	@make run-engine-bg
	@make run-interpreter-bg
	@make run-fusion-bg
	@echo ""
	@echo "✅ Pipeline active (engine + interpreter + fusion). Stabilizing for 5s..."
	@sleep 5
	@make test-e2e || (echo "💥 Test failed. Cleaning up..." && make stop-native && exit 1)
	@make stop-native
	@echo ""
	@echo "🎉 Full pipeline test complete."

test-pipeline: test-bridge ## Alias for test-bridge

stop-pipeline: ## Kill all background pipeline processes (engine and dashboard NOT included)
	@echo "🛑 Stopping pipeline..."
	@pkill -f "harvester.py" 2>/dev/null || true
	@pkill -f "semantic_agent.py" 2>/dev/null || true
	@pkill -f "fusion_engine.py" 2>/dev/null || true
	@sleep 0.5
	@echo "✅ Pipeline stopped"
	@make healthcheck

stop-native: stop-pipeline ## Kill ALL native background processes (engine + dashboard + pipeline)
	@echo "🛑 Stopping native engine & dashboard..."
	@pkill -f "CTT_Engine" 2>/dev/null || true
	@pkill -f "dashboard.py" 2>/dev/null || true
	@pkill -f "orchestrator.py" 2>/dev/null || true
	@sleep 0.5
	@echo "✅ Native stack stopped"
	@make healthcheck

# =============================================================================
# Flecs Explorer — Local UI
# =============================================================================

EXPLORER_DIR := $(HOME)/explorer

run-explorer: ## Host Flecs Explorer on http://localhost:8000
	@if [ ! -d $(EXPLORER_DIR)/etc ]; then \		echo "🌐 Flecs Explorer not found. Cloning to $(EXPLORER_DIR)..."; \		git clone --depth 1 https://github.com/flecs-hub/explorer.git $(EXPLORER_DIR); \	fi
	@echo "🌐 Starting Flecs Explorer at http://localhost:8000"
	@cd $(EXPLORER_DIR)/etc && python3 -m http.server 8000

run-explorer-bg: ## Start Flecs Explorer in background
	@if [ ! -d $(EXPLORER_DIR)/etc ]; then \		git clone --depth 1 https://github.com/flecs-hub/explorer.git $(EXPLORER_DIR); \	fi
	@cd $(EXPLORER_DIR)/etc && nohup python3 -m http.server 8000 > /tmp/ctt_explorer.log 2>&1 &
	@echo "🌐 Explorer backgrounded (log: /tmp/ctt_explorer.log)"

# =============================================================================
# Protobuf Generation
# =============================================================================

PROTO_FILE := api/proto/ctt_messages.proto
PROTO_OUT  := services/data-pipeline/fusion

proto: ## Generate Python protobuf module
	@echo "🧬 Generating Protobuf bindings..."
	@$(PYTHON_BIN) -m grpc_tools.protoc \		--python_out=$(PROTO_OUT) \		-Iapi/proto \		$(PROTO_FILE)
	@echo "✅ Generated: $(PROTO_OUT)/ctt_messages_pb2.py"

proto-clean: ## Remove generated protobuf files
	@rm -f $(PROTO_OUT)/ctt_messages_pb2.py
	@echo "🧹 Protobuf bindings cleaned"

# =============================================================================
# Phase 11: Docker Diagnostics & Disk Management
# =============================================================================

docker-df: ## Show Docker disk usage (images, containers, volumes, build cache)
	@echo "🐳 Docker Disk Usage Report"
	@echo "═══════════════════════════════════════════════════════════════"
	@docker system df
	@echo ""
	@echo "📊 Image breakdown (top 10 by size):"
	@docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}" | sort -k3 -rh | head -10
	@echo ""
	@echo "🧹 Reclaimable space:"
	@docker system df -v 2>/dev/null | grep -E "RECLAIMABLE|Images|Containers|Volumes|Build Cache" || docker system df

docker-prune: ## Aggressive cleanup: remove dangling images, stopped containers, unused volumes
	@echo "🧹 Pruning Docker system..."
	@docker system prune -a --volumes -f
	@echo "✅ Prune complete"
	@make docker-df

docker-prune-soft: ## Soft prune: only dangling images and unused build cache
	@echo "🧹 Soft pruning Docker (safe)..."
	@docker image prune -f
	@docker builder prune -f --filter unused-for=24h
	@echo "✅ Soft prune complete"
	@make docker-df

# =============================================================================
# Phase 11: Colima Disk Compaction (Non-Destructive)
# =============================================================================

docker-compact: ## ⚠️ Compact Colima VM disk (known to INCREASE size — use colima-nuke)
	@echo "💾 Colima VM disk compaction"
	@echo ""
	@echo "   ⚠️  KNOWN ISSUE: Previous runs showed disk INCREASE (16.74GB → 19.75GB)."
	@echo "   qemu-img convert created a non-sparse copy alongside the original."
	@echo ""
	@echo "   RECOMMENDED: Use 'make colima-nuke' for guaranteed cleanup."
	@echo "   Current disk state:"
	@du -sh ~/.colima/_lima/_disks/ 2>/dev/null || echo "   (Lima disks not found)"
	@echo ""
	@echo "   To nuke and start fresh (DESTRUCTIVE but reliable):"
	@echo "      make colima-nuke"
	@false

colima-status: ## Check Colima VM status and resource usage
	@echo "🖥️  Colima Status"
	@colima status 2>/dev/null || echo "❌ Colima not running. Start with: make colima-reset"
	@echo ""
	@echo "💾 Lima disk usage:"
	@du -sh ~/.colima/_lima/_disks 2>/dev/null || echo "   (Lima disks not found)"
	@echo ""
	@make docker-df

colima-reset: ## Reset Colima VM to reclaim disk space (destructive)
	@echo "🛑 Stopping and deleting Colima VM..."
	@colima stop 2>/dev/null || true
	@colima delete 2>/dev/null || true
	@echo "🚀 Starting fresh Colima VM (15 GB disk)..."
	@colima start --cpu 4 --memory 8 --disk 15
	@echo "✅ Colima reset complete. Rebuild with: docker-compose up --build -d"

colima-nuke: ## Full Lima store reset (fixes _disks bloat)
	@echo "🛑 Stopping Colima..."
	@colima stop 2>/dev/null || true
	@echo "💥 Deleting Lima disks + instances..."
	@rm -rf ~/.colima/_lima/_disks
	@rm -rf ~/.colima/_lima/colima
	@echo "🚀 Starting fresh Colima..."
	@colima start --cpu 4 --memory 8 --disk 30
	@echo "✅ Nuclear reset complete. Rebuild with: docker-compose up --build -d"

# =============================================================================
# Global Utilities
# =============================================================================

fmt-engine: ## Format C++ source files (requires clang-format)
	@echo "🎨 Formatting C++ sources..."
	@find $(L1_DIR)/src $(L1_DIR)/include -type f \\( -name '*.cpp' -o -name '*.h' -o -name '*.hpp' \\) | \		xargs clang-format -i -style=file 2>/dev/null || \		echo "⚠️  clang-format not installed."

clean-all: clean-engine ## Clean everything (builds + Python envs + Docker cache)
	@echo "🧹 Cleaning Python environments..."
	@rm -rf $(L2_DIR)/.venv $(L3_DIR)/.venv services/l5-macro/.venv $(L7_DIR)/.venv 2>/dev/null || true
	@echo "🧹 Cleaning Docker build cache..."
	@docker builder prune -f 2>/dev/null || true
	@echo "🧹 Cleaning source hash tracking..."
	@rm -f .ctt_source_hashes.json
	@echo "✅ All artifacts cleaned"

all: build-engine setup-python ## Build engine + setup Python (full onboarding)
