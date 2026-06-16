# CTT Project — macOS Dependencies (Phase 11)
# Usage: brew bundle
#
# Phase 11 additions:
#   - docker-buildx (for docker-bake.hcl support)
#   - qemu (for VM disk compaction)
#   - git (for SHA tagging)
#   - nmap (for port checking, replaces nc)
#
# Install: brew bundle --file=Brewfile

# =============================================================================
# Core Build Tools
# =============================================================================
brew "cmake"
brew "ninja"
brew "pkg-config"
brew "git"           # Required for SHA tagging in docker-bake.hcl

# =============================================================================
# C++ Dependencies
# =============================================================================
brew "zeromq"
brew "protobuf"
brew "grpc"

# =============================================================================
# Python Environment
# =============================================================================
brew "python@3.13"
brew "uv"            # Preferred Python package manager (faster than pip)

# =============================================================================
# Kafka / Redpanda Client Libraries (for native Python development)
# =============================================================================
brew "librdkafka"

# =============================================================================
# Docker / Container Runtime (Colima instead of Docker Desktop)
# =============================================================================
brew "colima"
brew "docker"
brew "docker-compose"
brew "docker-buildx"   # Phase 11: Required for docker-bake.hcl support

# =============================================================================
# Phase 11: Disk Management & VM Tools
# =============================================================================
brew "qemu"            # Required for 'make docker-compact' (VM disk compaction)
                       # qemu-img convert rewrites QCOW2, reclaiming sparse space

# =============================================================================
# Optional: CLI Utilities
# =============================================================================
brew "jq"              # JSON parsing for API responses and config files
brew "nmap"            # Port checking (nc alternative, more reliable on macOS)

# =============================================================================
# Optional: IDE
# =============================================================================
cask "visual-studio-code" unless File.exist?("/Applications/Visual Studio Code.app")
