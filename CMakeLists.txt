cmake_minimum_required(VERSION 3.25)

# 1. FORCE INTEL ARCHITECTURE (To match your /usr/local/bin/brew)
set(CMAKE_OSX_ARCHITECTURES "x86_64")

project(CTT_Engine VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 2. POINT TO THE INTEL NEIGHBORHOOD
set(BREW_PREFIX "/usr/local")
list(APPEND CMAKE_PREFIX_PATH "${BREW_PREFIX}")
set(ENV{PKG_CONFIG_PATH} "${BREW_PREFIX}/lib/pkgconfig:$ENV{PKG_CONFIG_PATH}")

# 3. LOCATE DEPENDENCIES
find_package(EnTT REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(ZMQ REQUIRED IMPORTED_TARGET libzmq cppzmq)

# 4. EXPLICITLY INCLUDE THE FOLDER WE FOUND
include_directories(include)
include_directories("${BREW_PREFIX}/include")

# 5. DEFINE THE ENGINE
add_executable(CTT_Engine src/main.cpp)

# 6. LINK THE NERVOUS SYSTEM
target_link_libraries(CTT_Engine PRIVATE 
    EnTT::EnTT 
    PkgConfig::ZMQ
)