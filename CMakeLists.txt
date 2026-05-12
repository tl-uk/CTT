cmake_minimum_required(VERSION 3.25)

set(CMAKE_POLICY_VERSION_MINIMUM 3.5)

# project() must enable C for the Flecs core, alongside CXX for its API
project(CTT_Engine LANGUAGES CXX C)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)

# -----------------------------------------------------------------------------
# 1. Flecs Global Configuration (Must be set BEFORE FetchContent_MakeAvailable)
# -----------------------------------------------------------------------------
# These variables ensure the modules needed for the Digital Twin are compiled.
set(FLECS_REST ON CACHE BOOL "Enable Flecs REST API" FORCE)
set(FLECS_MONITOR ON CACHE BOOL "Enable Flecs Monitor Module" FORCE)
set(FLECS_SYSTEM ON CACHE BOOL "Enable Flecs System Module" FORCE)
set(FLECS_CPP ON CACHE BOOL "Enable Flecs C++ API" FORCE)

# -----------------------------------------------------------------------------
# 2. Dependencies
# -----------------------------------------------------------------------------

# Threads is required for ZeroMQ and the Flecs REST server background threads
find_package(Threads REQUIRED)

# nlohmann_json (Digital Shadow Telemetry)
find_package(nlohmann_json QUIET)
if(NOT nlohmann_json_FOUND)
    message(STATUS "Fetching nlohmann_json...")
    FetchContent_Declare(
        json
        URL https://github.com/nlohmann/json/releases/download/v3.11.2/json.tar.xz
    )
    FetchContent_MakeAvailable(json)
endif()

# ZeroMQ / cppzmq (Messaging Layer)
find_package(cppzmq REQUIRED)

# Flecs (Multi-scale ECS & Digital Twin Explorer)
FetchContent_Declare(
    flecs
    GIT_REPOSITORY https://github.com/SanderMertens/flecs.git
    GIT_TAG v3.2.11 
)
FetchContent_MakeAvailable(flecs)

# -----------------------------------------------------------------------------
# 3. Target Definition
# -----------------------------------------------------------------------------
add_executable(CTT_Engine
    src/main.cpp
    src/SimulationEngine.cpp
    src/DataBridge.cpp
)

target_include_directories(CTT_Engine PRIVATE include)

# --- THE FIX: Apply this to ALL platforms (M3, Linux, Windows) ---
target_compile_definitions(CTT_Engine PRIVATE FLECS_REST)

target_link_libraries(CTT_Engine PRIVATE 
    flecs
    nlohmann_json::nlohmann_json 
    cppzmq
    Threads::Threads
)

# -----------------------------------------------------------------------------
# 4. Platform-Specific Tweaks
# -----------------------------------------------------------------------------
if(MSVC)
    # This ensures the REST types are visible in your C++ code on all platforms
    target_compile_definitions(CTT_Engine PRIVATE FLECS_REST)
endif()