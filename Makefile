# =============================================================================
# CTT Project — Hardened Root Makefile
# Microservices build orchestration for Apple Silicon (M3)
# =============================================================================

.PHONY: help all check-deps configure-engine build-engine run-engine run-engine-fast         clean-engine setup-python setup-l3 run-dashboard clean-all         run-explorer run-explorer-bg         run-harvester run-interpreter run-fusion         run-harvester-bg run-interpreter-bg run-fusion-bg         test-bridge test-e2e test-pipeline stop-pipeline healthcheck         check-ports proto proto-clean fmt-engine lint-engine

# Detect CPU cores for parallel builds (macOS/Linux)
NPROCS := $(shell sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4)

# Service directories
L1_DIR     := services/l1-engine
L2_DIR     := services/l2-bridge
L3_DIR     := services/l3-analytics
BUILD_DIR  := $(L1_DIR)/build
CONFIG_DIR := services/config

# =============================================================================
# Help
# =============================================================================

help: ## Show this help message
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║           CTT Project — Build & Run Commands                 ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | 		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Quick start (development):"
	@echo "  1. make check-deps     → Verify Homebrew dependencies"
	@echo "  2. make build-engine   → Compile the C++ L1 Engine"
	@echo "  3. make run-engine     → Build & launch the Engine"
	@echo "  4. make setup-python   → Prepare L2 Bridge environment"
	@echo "  5. make test-e2e       → Verify full pipeline (engine must be running)"
	@echo ""
	@echo "Production pipeline:"
	@echo "  make test-pipeline     → Start all components, run E2E test, stop"
	@echo ""

# =============================================================================
# Internal Helpers
# =============================================================================

# Check if a TCP port is already in use on macOS/Linux
# Usage: $(call check-port-free,5560,harvester)
define check-port-free
	@if lsof -i :$(1) >/dev/null 2>&1; then 		echo "❌ Port $(1) already in use. Run 'make stop-pipeline' first."; 		exit 1; 	else 		echo "✅ Port $(1) is free for $(2)"; 	fi
endef

# Wait until a process binds to a TCP port (timeout 5s)
# Usage: $(call wait-for-port,5560,harvester)
define wait-for-port
	@echo "⏳ Waiting for $(2) to bind port $(1)..."
	@for i in $$(seq 1 25); do 		if nc -z localhost $(1) 2>/dev/null; then 			echo "✅ $(2) is listening on $(1)"; 			exit 0; 		fi; 		sleep 0.2; 	done; 	echo "❌ $(2) failed to bind port $(1) within 5s"; 	exit 1
endef

# Verify a background PID is alive
# Usage: $(call check-pid-alive,PID,name)
define check-pid-alive
	@if ! kill -0 $(1) 2>/dev/null; then 		echo "❌ $(2) (PID $(1)) died immediately. Check logs."; 		exit 1; 	fi
endef

# =============================================================================
# L1 Engine — C++ Flecs Core
# =============================================================================

check-deps: ## Verify macOS system dependencies (cmake, ninja, pkg-config, zeromq)
	@echo "🔍 Checking system dependencies..."
	@which cmake >/dev/null 2>&1 || (echo "❌ cmake not found. Run: brew install cmake ninja" && exit 1)
	@which ninja >/dev/null 2>&1 || (echo "❌ ninja not found. Run: brew install ninja" && exit 1)
	@which pkg-config >/dev/null 2>&1 || (echo "❌ pkg-config not found. Run: brew install pkg-config" && exit 1)
	@test -d /opt/homebrew/opt/zeromq/lib || (echo "❌ zeromq not found. Run: brew install zeromq" && exit 1)
	@echo "✅ All system dependencies found"

configure-engine: check-deps ## Configure CMake for L1 Engine (clean configure)
	@echo "⚙️  Configuring L1 Engine..."
	@rm -rf $(BUILD_DIR)
	@cmake -B $(BUILD_DIR) -S $(L1_DIR) -G Ninja 		-DCMAKE_BUILD_TYPE=Release 		-DCMAKE_OSX_ARCHITECTURES=arm64 		-DCMAKE_POLICY_VERSION_MINIMUM=3.5
	@echo "✅ Configure complete"

build-engine: configure-engine ## Build the C++ L1 Engine with all cores
	@echo "🔨 Building L1 Engine with $(NPROCS) cores..."
	@cmake --build $(BUILD_DIR) --parallel $(NPROCS)
	@echo ""
	@echo "✅ Build complete: $(BUILD_DIR)/CTT_Engine"
	@echo "   Verify binary:   file $(BUILD_DIR)/CTT_Engine"
	@echo ""

run-engine: build-engine ## Build and run the L1 Engine (blocks terminal)
	@echo "🚀 Starting CTT L1 Engine..."
	@echo "   REST API:    http://localhost:27750"
	@echo "   ZMQ Pub:     tcp://localhost:5555  (telemetry)"
	@echo "   ZMQ Sub:     tcp://localhost:5556  (perturbations — Fusion binds here)"
	@echo ""
	@./$(BUILD_DIR)/CTT_Engine

run-engine-fast: ## Run L1 Engine WITHOUT rebuilding (blocks terminal)
	@if [ ! -f $(BUILD_DIR)/CTT_Engine ]; then 		echo "❌ Engine not built. Run 'make build-engine' first."; 		exit 1; 	fi
	@echo "🚀 Starting CTT L1 Engine (fast mode, no rebuild)..."
	@./$(BUILD_DIR)/CTT_Engine

clean-engine: ## Remove L1 Engine build artifacts
	@echo "🧹 Cleaning L1 Engine build..."
	@rm -rf $(BUILD_DIR)
	@echo "✅ Clean complete"

# =============================================================================
# L2 Bridge — Python Telemetry & Dashboard
# =============================================================================

setup-python: ## Create Python venv and install L2 Bridge dependencies
	@echo "🐍 Setting up Python environment for L2 Bridge..."
	@cd $(L2_DIR) && uv venv --python 3.13
	@cd $(L2_DIR) && . .venv/bin/activate && uv pip install -r requirements.txt
	@echo "✅ Python environment ready in $(L2_DIR)/.venv"

run-dashboard: ## Run the L2 Bridge dashboard (requires engine running)
	@echo "📊 Starting L2 Bridge dashboard..."
	@cd $(L2_DIR) && . .venv/bin/activate && PYTHONPATH="$(CONFIG_DIR)" python dashboard.py

# =============================================================================
# L3 Analytics — Python Data Science & ML
# =============================================================================

setup-l3: ## Setup L3 Analytics environment
	@echo "🐍 Setting up L3 Analytics..."
	@cd $(L3_DIR) && uv venv --python 3.13
	@cd $(L3_DIR) && . .venv/bin/activate && uv pip install -r requirements.txt

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
	@for port in 5555 5556 5560 5561; do 		if nc -z localhost $$port 2>/dev/null; then 			status="✅ UP"; 		else 			status="⬜ DOWN"; 		fi; 		case $$port in 			5555) echo "L1 Engine (telemetry) | 5555 | $$status" ;; 			5556) echo "Fusion (perturbations)| 5556 | $$status" ;; 			5560) echo "Harvester (raw data)  | 5560 | $$status" ;; 			5561) echo "Interpreter (mapped)  | 5561 | $$status" ;; 		esac; 	done
	@echo "────────────────────────────────────────"

test-e2e: ## Run end-to-end pipeline test (requires engine running)
	@echo "🧪 Running end-to-end pipeline test..."
	@cd $(L2_DIR) && . .venv/bin/activate && PYTHONPATH="$(CONFIG_DIR):../data-pipeline/fusion" python ../../scripts/test_e2e.py --mode standalone

test-bridge: ## Launch full data pipeline in background + run E2E test
	@echo "🔄 Launching pipeline for integration test..."
	@make stop-pipeline >/dev/null 2>&1 || true
	@sleep 0.5
	@make run-harvester-bg
	@make run-interpreter-bg
	@make run-fusion-bg
	@echo ""
	@echo "✅ Pipeline active. Running E2E test in 2s..."
	@sleep 2
	@make test-e2e || (echo "\n💥 Test failed. Cleaning up..." && make stop-pipeline && exit 1)
	@make stop-pipeline
	@echo ""
	@echo "🎉 Full pipeline test complete."

test-pipeline: test-bridge ## Alias for test-bridge

stop-pipeline: ## Kill all background pipeline processes
	@echo "🛑 Stopping pipeline..."
	@pkill -f "harvester.py" 2>/dev/null || true
	@pkill -f "semantic_agent.py" 2>/dev/null || true
	@pkill -f "fusion_engine.py" 2>/dev/null || true
	@pkill -f "dashboard.py" 2>/dev/null || true
	@sleep 0.5
	@echo "✅ Pipeline stopped"
	@make healthcheck

# =============================================================================
# Flecs Explorer — Local UI
# =============================================================================

EXPLORER_DIR := $(HOME)/explorer

run-explorer: ## Host Flecs Explorer on http://localhost:8000
	@if [ ! -d $(EXPLORER_DIR)/etc ]; then 		echo "🌐 Flecs Explorer not found. Cloning to $(EXPLORER_DIR)..."; 		git clone --depth 1 https://github.com/flecs-hub/explorer.git $(EXPLORER_DIR); 	fi
	@echo "🌐 Starting Flecs Explorer at http://localhost:8000"
	@cd $(EXPLORER_DIR)/etc && python3 -m http.server 8000

run-explorer-bg: ## Start Flecs Explorer in background
	@if [ ! -d $(EXPLORER_DIR)/etc ]; then 		git clone --depth 1 https://github.com/flecs-hub/explorer.git $(EXPLORER_DIR); 	fi
	@cd $(EXPLORER_DIR)/etc && nohup python3 -m http.server 8000 > /tmp/ctt_explorer.log 2>&1 &
	@echo "🌐 Explorer backgrounded (log: /tmp/ctt_explorer.log)"

# =============================================================================
# Protobuf Generation
# =============================================================================

PROTO_FILE := api/proto/ctt_messages.proto
PROTO_OUT  := services/data-pipeline/fusion

proto: ## Generate Python protobuf module using venv-matched protoc
	@echo "🧬 Generating Protobuf bindings..."
	@$(L2_DIR)/.venv/bin/python -m grpc_tools.protoc 		--python_out=$(PROTO_OUT) 		-Iapi/proto 		$(PROTO_FILE)
	@echo "✅ Generated: $(PROTO_OUT)/ctt_messages_pb2.py"

proto-clean: ## Remove generated protobuf files
	@rm -f $(PROTO_OUT)/ctt_messages_pb2.py
	@echo "🧹 Protobuf bindings cleaned"

# =============================================================================
# Global Utilities
# =============================================================================

fmt-engine: ## Format C++ source files (requires clang-format)
	@echo "🎨 Formatting C++ sources..."
	@find $(L1_DIR)/src $(L1_DIR)/include -name '*.cpp' -o -name '*.hpp' | 		xargs clang-format -i -style=file 2>/dev/null || 		echo "⚠️  clang-format not installed. Run: brew install clang-format"

clean-all: clean-engine ## Clean everything (builds + Python envs)
	@echo "🧹 Cleaning Python environments..."
	@rm -rf $(L2_DIR)/.venv $(L3_DIR)/.venv 2>/dev/null || true
	@echo "✅ All artifacts cleaned"

all: build-engine setup-python ## Build engine + setup Python (full onboarding)
