cmake_minimum_required(VERSION 3.25)
project(CTT_Engine LANGUAGES CXX C)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)

# -----------------------------------------------------------------------------
# 0. Apple Silicon / Homebrew Auto-Detection (IDE-Proofing)
# -----------------------------------------------------------------------------
# This ensures VS Code and other IDEs automatically find Homebrew libraries 
# on your M3 and M3 Max without manual command-line flags. Safely ignored on Windows/Linux.
if(APPLE AND CMAKE_HOST_SYSTEM_PROCESSOR MATCHES "arm64")
    message(STATUS "Apple Silicon detected. Adding /opt/homebrew to search paths.")
    list(APPEND CMAKE_PREFIX_PATH "/opt/homebrew")
endif()

# -----------------------------------------------------------------------------
# 1. Flecs Global Configuration
# -----------------------------------------------------------------------------
set(FLECS_REST ON CACHE BOOL "Enable Flecs REST API" FORCE)
set(FLECS_MONITOR ON CACHE BOOL "Enable Flecs Monitor Module" FORCE)
set(FLECS_SYSTEM ON CACHE BOOL "Enable Flecs System Module" FORCE)
set(FLECS_CPP ON CACHE BOOL "Enable Flecs C++ API" FORCE)

# -----------------------------------------------------------------------------
# 2. Dependencies
# -----------------------------------------------------------------------------
find_package(Threads REQUIRED)

# nlohmann_json
FetchContent_Declare(json URL https://github.com/nlohmann/json/releases/download/v3.11.2/json.tar.xz)
FetchContent_MakeAvailable(json)

# ZeroMQ (Multi-Platform Resolution Strategy)
# Strategy: Try PkgConfig first (Mac/Linux), fallback to standard find_package (Windows)
find_package(PkgConfig QUIET)
if(PKG_CONFIG_FOUND)
    pkg_check_modules(ZMQ QUIET libzmq)
endif()

if(NOT ZMQ_FOUND)
    message(STATUS "PkgConfig did not find ZeroMQ. Falling back to standard find_package (Windows/vcpkg mode).")
    find_package(ZeroMQ REQUIRED)
endif()

# Fetch cppzmq headers to ensure they are present regardless of local setup
FetchContent_Declare(cppzmq GIT_REPOSITORY https://github.com/zeromq/cppzmq.git GIT_TAG v4.10.0)
FetchContent_MakeAvailable(cppzmq)

# Flecs (Digital Twin Engine)
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

# Base include directories
target_include_directories(CTT_Engine PRIVATE include)

# Conditionally add ZMQ includes if found via PkgConfig
if(ZMQ_FOUND)
    target_include_directories(CTT_Engine PRIVATE ${ZMQ_INCLUDE_DIRS})
endif()

# THE FIX: Apply REST definitions to ALL platforms (Fixes namespace errors on M3/Clang/GCC/MSVC)
target_compile_definitions(CTT_Engine PRIVATE FLECS_REST)

# Link core libraries
target_link_libraries(CTT_Engine PRIVATE 
    flecs
    nlohmann_json::nlohmann_json 
    cppzmq
    Threads::Threads
)

# Link ZeroMQ conditionally based on how the system found it
if(ZMQ_FOUND)
    target_link_libraries(CTT_Engine PRIVATE ${ZMQ_LIBRARIES}) # Mac/Linux
else()
    target_link_libraries(CTT_Engine PRIVATE libzmq) # Windows
endif()