cmake_minimum_required(VERSION 3.25)
project(CTT_Engine LANGUAGES CXX C)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)

# -----------------------------------------------------------------------------
# 0. Apple Silicon / Homebrew Auto-Detection
# -----------------------------------------------------------------------------
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

# Hardened nlohmann_json: Try local first, then fetch
find_package(nlohmann_json QUIET)
if(NOT nlohmann_json_FOUND)
    message(STATUS "nlohmann_json not found locally. Attempting fetch...")
    FetchContent_Declare(
        json
        URL https://github.com/nlohmann/json/releases/download/v3.11.2/json.tar.xz
        DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    )
    FetchContent_MakeAvailable(json)
endif()

# ZeroMQ / cppzmq
find_package(PkgConfig REQUIRED)
pkg_check_modules(ZMQ REQUIRED libzmq)

FetchContent_Declare(
    cppzmq 
    GIT_REPOSITORY https://github.com/zeromq/cppzmq.git 
    GIT_TAG v4.10.0
    GIT_SHALLOW TRUE # Added to speed up download
)
FetchContent_MakeAvailable(cppzmq)

# Flecs
FetchContent_Declare(
    flecs
    GIT_REPOSITORY https://github.com/SanderMertens/flecs.git
    GIT_TAG v3.2.11 
    GIT_SHALLOW TRUE # Added to speed up download
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

target_include_directories(CTT_Engine PRIVATE include ${ZMQ_INCLUDE_DIRS})
target_compile_definitions(CTT_Engine PRIVATE FLECS_REST)

target_link_libraries(CTT_Engine PRIVATE 
    flecs
    nlohmann_json::nlohmann_json 
    cppzmq
    Threads::Threads
    ${ZMQ_LIBRARIES}
)