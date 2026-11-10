cmake_minimum_required(VERSION 3.16)
project(TFM LANGUAGES CXX)

# Point this at the Krita 5.3.4 source tree when configuring the plugin.
# The plugin uses Krita's in-tree kis_add_library() helper because Krita's
# internal image and UI libraries are not a stable standalone SDK.
set(KRITA_SOURCE_DIR "" CACHE PATH "Krita 5.3.4 source directory")

if (NOT KRITA_SOURCE_DIR)
    message(FATAL_ERROR "Set KRITA_SOURCE_DIR to the Krita 5.3.4 source tree")
endif()

if (NOT EXISTS "${KRITA_SOURCE_DIR}/CMakeLists.txt")
    message(FATAL_ERROR "KRITA_SOURCE_DIR does not contain a Krita source tree")
endif()

# This file is intended to be included by Krita's top-level build. For an
# external configure, include Krita's plugin helper and targets when available.
if (NOT COMMAND kis_add_library)
    include("${KRITA_SOURCE_DIR}/cmake/kde_macro/KDEInstallDirs.cmake" OPTIONAL)
    include("${KRITA_SOURCE_DIR}/cmake/kis_macros.cmake" OPTIONAL)
endif()

if (NOT COMMAND kis_add_library)
    message(FATAL_ERROR "TFM must be configured from a Krita build tree or a build that exports kis_add_library")
endif()

add_subdirectory(src)
