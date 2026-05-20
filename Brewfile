# CTT Project — macOS Dependencies
# Usage: brew bundle

# Core build tools
brew "cmake"
brew "ninja"
brew "pkg-config"
brew "git"

# C++ dependencies
brew "zeromq"
brew "protobuf"
brew "grpc"

# Python environment
brew "python@3.13"
brew "uv"

# Docker / Container runtime (Colima instead of Docker Desktop)
brew "colima"
brew "docker"
brew "docker-compose"

# Optional: CLI utilities
brew "jq"
brew "ncat"

# VS Code (optional, or use Cursor)
cask "visual-studio-code" unless File.exist?("/Applications/Visual Studio Code.app")