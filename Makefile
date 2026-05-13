# =============================================================================
# CTT Project — Root Makefile
# Microservices build orchestration for Apple Silicon (M3)
# =============================================================================

.PHONY: help all check-deps configure-engine build-engine run-engine         clean-engine setup-python run-dashboard clean-all run-explorer         fmt-engine lint-engine         run-explorer run-harvester run-interpreter run-fusion \
         test-bridge stop-pipeline

# Detect CPU cores for parallel builds (macOS/Linux)
NPROCS := $(shell sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4)

# Service directories
L1_DIR     := services/l1-engine
L2_DIR     := services/l2-bridge
L3_DIR     := services/l3-analytics
BUILD_DIR  := $(L1_DIR)/build

# =============================================================================
# Help
# =============================================================================

help: ## Show this help message
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║           CTT Project — Build & Run Commands                 ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | 		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", \$$1, \$$2}'
	@echo ""
	@echo "Quick start:"
	@echo "  1. make check-deps     → Verify Homebrew dependencies"
	@echo "  2. make build-engine   → Compile the C++ L1 Engine"
	@echo "  3. make run-engine     → Build & launch the Engine"
	@echo "  4. make setup-python   → Prepare L2 Bridge environment"
	@echo "  5. make run-dashboard  → Start Python telemetry consumer"
	@echo ""

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

run-engine: build-engine ## Build and run the L1 Engine
	@echo "🚀 Starting CTT L1 Engine..."
	@echo "   REST API:    http://localhost:27750"
	@echo "   ZMQ Pub:     tcp://localhost:5555"
	@echo ""
	@cd $(L1_DIR) && ../../$(BUILD_DIR)/CTT_Engine

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
	@cd $(L2_DIR) && . .venv/bin/activate && python dashboard.py

# =============================================================================
# L3 Analytics — Python Data Science & ML
# =============================================================================
setup-l3: ## Setup L3 Analytics environment
	@echo "🐍 Setting up L3 Analytics..."
	@cd $(L3_DIR) && uv venv --python 3.13
	@cd $(L3_DIR) && . .venv/bin/activate && uv pip install -r requirements.txt


# =============================================================================
# Data Pipeline — Inbound Refinery (Test Network)
# =============================================================================

run-harvester: ## Run the mock SME Harvester (Ingestor)
	@echo "📡 Starting SME Harvester..."
	@cd $(L2_DIR) && . .venv/bin/activate && python ../data-pipeline/ingestor/harvester.py

run-interpreter: ## Run the Semantic Agent (Interpreter)
	@echo "🧠 Starting Semantic Interpreter..."
	@cd $(L2_DIR) && . .venv/bin/activate && python ../data-pipeline/interpreter/semantic_agent.py

run-fusion: ## Run the Fusion Engine (Command & Control)
	@echo "⚡ Starting Fusion Engine..."
	@cd $(L2_DIR) && . .venv/bin/activate && python ../data-pipeline/fusion/fusion_engine.py

# Background variants (for single-terminal use)
run-harvester-bg: ## Run harvester in background (logs to /tmp)
	@cd $(L2_DIR) && . .venv/bin/activate && nohup python ../data-pipeline/ingestor/harvester.py > /tmp/ctt_harvester.log 2>&1 &
	@echo "📡 Harvester backgrounded (log: /tmp/ctt_harvester.log)"

run-interpreter-bg: ## Run interpreter in background
	@cd $(L2_DIR) && . .venv/bin/activate && nohup python ../data-pipeline/interpreter/semantic_agent.py > /tmp/ctt_interpreter.log 2>&1 &
	@echo "🧠 Interpreter backgrounded (log: /tmp/ctt_interpreter.log)"

run-fusion-bg: ## Run fusion in background
	@cd $(L2_DIR) && . .venv/bin/activate && nohup python ../data-pipeline/fusion/fusion_engine.py > /tmp/ctt_fusion.log 2>&1 &
	@echo "⚡ Fusion backgrounded (log: /tmp/ctt_fusion.log)"

test-bridge: ## Launch full data pipeline (backgrounded)
	@echo "🔄 Launching pipeline..."
	@make run-harvester-bg
	@sleep 1
	@make run-interpreter-bg
	@sleep 1
	@make run-fusion-bg
	@echo ""
	@echo "✅ Pipeline active. View logs:"
	@echo "   tail -f /tmp/ctt_*.log"
	@echo "   Stop with: make stop-pipeline"

stop-pipeline: ## Kill all background pipeline processes
	@pkill -f "harvester.py" 2>/dev/null || true
	@pkill -f "semantic_agent.py" 2>/dev/null || true
	@pkill -f "fusion_engine.py" 2>/dev/null || true
	@echo "🛑 Pipeline stopped"

# =============================================================================
# Flecs Explorer — Local UI
# =============================================================================

EXPLORER_DIR := $(HOME)/explorer

run-explorer: ## Host Flecs Explorer on http://localhost:8000
	@if [ ! -d $(EXPLORER_DIR)/etc ]; then \
		echo "🌐 Flecs Explorer not found. Cloning to $(EXPLORER_DIR)..."; \
		git clone --depth 1 https://github.com/flecs-hub/explorer.git $(EXPLORER_DIR); \
	fi
	@echo "🌐 Starting Flecs Explorer at http://localhost:8000"
	@cd $(EXPLORER_DIR)/etc && python3 -m http.server 8000
	
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
