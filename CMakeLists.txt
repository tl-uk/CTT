cmake_minimum_required(VERSION 3.25)
project(CTT_Engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)

# -----------------------------------------------------------------------------
# 1. nlohmann_json (Digital Shadow Telemetry)
# -----------------------------------------------------------------------------
# We try to find it on the system first. 
# On macOS, this looks in /opt/homebrew. On Windows, it looks in vcpkg/conan paths.
find_package(nlohmann_json QUIET)

if(NOT nlohmann_json_FOUND)
    message(STATUS "nlohmann_json not found locally. Fetching from GitHub for platform-agnostic build...")
    FetchContent_Declare(
        json
        URL https://github.com/nlohmann/json/releases/download/v3.11.2/json.tar.xz
    )
    FetchContent_MakeAvailable(json)
endif()

# -----------------------------------------------------------------------------
# 2. ZeroMQ / cppzmq (Messaging Layer)
# -----------------------------------------------------------------------------
# ZeroMQ usually requires a system-level install (libzmq).
find_package(cppzmq REQUIRED)

# -----------------------------------------------------------------------------
# 3. EnTT (Agent ECS Registry)
# -----------------------------------------------------------------------------
# Since EnTT is header-only and small, we always fetch it to ensure 
# version consistency across your M3 Max and M3 Laptop.
FetchContent_Declare(
    entt
    GIT_REPOSITORY https://github.com/skypjack/entt.git
    GIT_TAG v3.13.0
)
FetchContent_MakeAvailable(entt)

# -----------------------------------------------------------------------------
# 4. Target Definition
# -----------------------------------------------------------------------------
add_executable(CTT_Engine
    src/main.cpp
    src/SimulationEngine.cpp
    src/DataBridge.cpp
)

target_include_directories(CTT_Engine PRIVATE include)

# Link using namespaced targets (Universal across OS)
target_link_libraries(CTT_Engine PRIVATE 
    cppzmq 
    nlohmann_json::nlohmann_json 
    EnTT::EnTT
)

# -----------------------------------------------------------------------------
# 5. Platform-Specific Tweaks
# -----------------------------------------------------------------------------
if(MSVC)
    # Windows-specific: Disable min/max macros that interfere with C++ std
    target_compile_definitions(CTT_Engine PRIVATE NOMINMAX)
endif()