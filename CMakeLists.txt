cmake_minimum_required(VERSION 3.25)
# Flecs requires a C compiler for its core, alongside CXX for its API
project(CTT_Engine LANGUAGES CXX C)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)

# -----------------------------------------------------------------------------
# 1. nlohmann_json (Digital Shadow Telemetry)
# -----------------------------------------------------------------------------
find_package(nlohmann_json QUIET)
if(NOT nlohmann_json_FOUND)
    message(STATUS "Fetching nlohmann_json for platform-agnostic build...")
    FetchContent_Declare(
        json
        URL https://github.com/nlohmann/json/releases/download/v3.11.2/json.tar.xz
    )
    FetchContent_MakeAvailable(json)
endif()

# -----------------------------------------------------------------------------
# 2. ZeroMQ / cppzmq (Messaging Layer)
# -----------------------------------------------------------------------------
find_package(cppzmq REQUIRED)

# -----------------------------------------------------------------------------
# 3. Flecs (Multi-scale ECS & Digital Twin Explorer)
# -----------------------------------------------------------------------------
# Enable the built-in REST API and Web Dashboard for real-time twin observability
set(FLECS_REST ON CACHE BOOL "Enable Flecs REST API" FORCE)
set(FLECS_EXPLORER ON CACHE BOOL "Enable Flecs Web Explorer" FORCE)

FetchContent_Declare(
    flecs
    GIT_REPOSITORY https://github.com/SanderMertens/flecs.git
    GIT_TAG v3.2.11  # Latest stable release
)
FetchContent_MakeAvailable(flecs)

# -----------------------------------------------------------------------------
# 4. Target Definition
# -----------------------------------------------------------------------------
add_executable(CTT_Engine
    src/main.cpp
    src/SimulationEngine.cpp
    src/DataBridge.cpp
)

target_include_directories(CTT_Engine PRIVATE include)

# Link Libraries (Replace EnTT with flecs)
target_link_libraries(CTT_Engine PRIVATE 
    cppzmq 
    nlohmann_json::nlohmann_json 
    flecs
)

# -----------------------------------------------------------------------------
# 5. Platform-Specific Tweaks
# -----------------------------------------------------------------------------
if(MSVC)
    target_compile_definitions(CTT_Engine PRIVATE NOMINMAX)
endif()