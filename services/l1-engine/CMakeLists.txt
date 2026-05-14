cmake_minimum_required(VERSION 3.25...3.31)
project(CTT_Engine LANGUAGES CXX C)

# Generate compile_commands.json for IDE integration
set(CMAKE_EXPORT_COMPILE_COMMANDS ON CACHE BOOL "" FORCE)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# --- Force old fetched dependencies to work with modern CMake ---
set(CMAKE_POLICY_VERSION_MINIMUM 3.5)

# --- Suppress ranlib "no symbols" warnings on macOS ---
if(APPLE)
    set(CMAKE_C_ARCHIVE_FINISH   "<CMAKE_RANLIB> -no_warning_for_no_symbols <TARGET>")
    set(CMAKE_CXX_ARCHIVE_FINISH "<CMAKE_RANLIB> -no_warning_for_no_symbols <TARGET>")
endif()

include(FetchContent)

# -----------------------------------------------------------------------------
# 0. Apple Silicon / Homebrew Auto-Detection
# -----------------------------------------------------------------------------
if(APPLE AND CMAKE_HOST_SYSTEM_PROCESSOR MATCHES "arm64")
    message(STATUS "Apple Silicon detected. Adding /opt/homebrew to search paths.")
    list(APPEND CMAKE_PREFIX_PATH "/opt/homebrew")
    if(EXISTS "/opt/homebrew/opt/protobuf")
        list(APPEND CMAKE_PREFIX_PATH "/opt/homebrew/opt/protobuf")
    endif()
    if(EXISTS "/opt/homebrew/opt/zeromq")
        list(APPEND CMAKE_PREFIX_PATH "/opt/homebrew/opt/zeromq")
    endif()
endif()

# -----------------------------------------------------------------------------
# 1. Flecs Global Configuration
# -----------------------------------------------------------------------------
set(FLECS_REST ON CACHE BOOL "Enable Flecs REST API" FORCE)
# v4: monitor addon renamed to stats
set(FLECS_STATS ON CACHE BOOL "Enable Flecs Stats Module" FORCE)
set(FLECS_SYSTEM ON CACHE BOOL "Enable Flecs System Module" FORCE)
set(FLECS_CPP ON CACHE BOOL "Enable Flecs C++ API" FORCE)

# -----------------------------------------------------------------------------
# 2. Dependencies
# -----------------------------------------------------------------------------
find_package(Threads REQUIRED)

# Hardened nlohmann_json: Try local first, then fetch
find_package(nlohmann_json QUIET)
if(NOT nlohmann_json_FOUND)
    message(STATUS "nlohmann_json not found locally. Fetching v3.12.0...")
    FetchContent_Declare(
        json
        URL https://github.com/nlohmann/json/releases/download/v3.12.0/json.tar.xz
        DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    )
    FetchContent_MakeAvailable(json)
endif()

# --- ZeroMQ / cppzmq (Multi-platform) ---
# Try CMake config first (works with vcpkg, conda, manual installs)
find_package(ZeroMQ QUIET)

if(NOT ZeroMQ_FOUND)
    # Fall back to pkg-config (Linux package managers, macOS Homebrew)
    find_package(PkgConfig QUIET)
    if(PkgConfig_FOUND)
        # Help macOS Homebrew find the .pc file
        if(APPLE AND EXISTS "/opt/homebrew/opt/zeromq/lib/pkgconfig")
            set(ENV{PKG_CONFIG_PATH} "/opt/homebrew/opt/zeromq/lib/pkgconfig:$ENV{PKG_CONFIG_PATH}")
        endif()
        
        pkg_check_modules(ZeroMQ QUIET libzmq)
    endif()
endif()

if(NOT ZeroMQ_FOUND)
    message(FATAL_ERROR 
        "ZeroMQ not found.\n"
        "Install instructions:\n"
        "  macOS:   brew install pkg-config zeromq\n"
        "  Ubuntu:  sudo apt install pkg-config libzmq3-dev\n"
        "  Windows: vcpkg install zeromq\n"
        "  Or set ZeroMQ_DIR to the directory containing ZeroMQConfig.cmake"
    )
endif()

# cppzmq expects a 'libzmq' target. If we found ZeroMQ via pkg-config, create one.
if(ZeroMQ_FOUND AND NOT TARGET libzmq)
    if(ZeroMQ_LINK_LIBRARIES OR ZeroMQ_LIBRARIES)
        add_library(libzmq INTERFACE IMPORTED)
        target_link_libraries(libzmq INTERFACE ${ZeroMQ_LINK_LIBRARIES} ${ZeroMQ_LIBRARIES})
        target_include_directories(libzmq INTERFACE ${ZeroMQ_INCLUDE_DIRS})
        if(ZeroMQ_LIBRARY_DIRS)
            target_link_directories(libzmq INTERFACE ${ZeroMQ_LIBRARY_DIRS})
        endif()
    endif()
endif()

# --- Prevent cppzmq from building tests/examples (avoids Catch2 fetch) ---
set(CPPZMQ_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(CPPZMQ_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)

FetchContent_Declare(
    cppzmq 
    GIT_REPOSITORY https://github.com/zeromq/cppzmq.git 
    GIT_TAG v4.10.0
    GIT_SHALLOW TRUE
)
FetchContent_MakeAvailable(cppzmq)

# -----------------------------------------------------------------------------
# Protobuf Generation
# -----------------------------------------------------------------------------
find_package(Protobuf REQUIRED)

set(PROTO_FILE ${CMAKE_CURRENT_SOURCE_DIR}/../../api/proto/ctt_messages.proto)
get_filename_component(PROTO_DIR ${PROTO_FILE} DIRECTORY)

set(PROTO_SRC ${CMAKE_CURRENT_BINARY_DIR}/ctt_messages.pb.cc)
set(PROTO_HDR ${CMAKE_CURRENT_BINARY_DIR}/ctt_messages.pb.h)

add_custom_command(
    OUTPUT ${PROTO_SRC} ${PROTO_HDR}
    COMMAND ${Protobuf_PROTOC_EXECUTABLE}
    ARGS --cpp_out=${CMAKE_CURRENT_BINARY_DIR} -I${PROTO_DIR} ${PROTO_FILE}
    DEPENDS ${PROTO_FILE}
    COMMENT "Generating C++ from ctt_messages.proto"
    VERBATIM
)

add_custom_target(ctt_proto_gen DEPENDS ${PROTO_SRC} ${PROTO_HDR})

# Flecs v4.1.5
FetchContent_Declare(
    flecs
    GIT_REPOSITORY https://github.com/SanderMertens/flecs.git
    GIT_TAG v4.1.5 
    GIT_SHALLOW TRUE
)
FetchContent_MakeAvailable(flecs)

# -----------------------------------------------------------------------------
# 3. Target Definition
# -----------------------------------------------------------------------------
add_executable(CTT_Engine
    src/main.cpp
    src/SimulationEngine.cpp
    src/DataBridge.cpp
    ${PROTO_SRC}
)

add_dependencies(CTT_Engine ctt_proto_gen)

target_include_directories(CTT_Engine PRIVATE 
    include 
    ${CMAKE_CURRENT_BINARY_DIR}
)

# Suppress C++20 deprecated-literal-operator warnings from cppzmq headers
target_compile_options(CTT_Engine PRIVATE 
    $<$<CXX_COMPILER_ID:AppleClang,Clang,GNU>:-Wno-deprecated-literal-operator>
)

target_link_libraries(CTT_Engine PRIVATE 
    flecs
    nlohmann_json::nlohmann_json 
    cppzmq
    Threads::Threads
    protobuf::libprotobuf
)