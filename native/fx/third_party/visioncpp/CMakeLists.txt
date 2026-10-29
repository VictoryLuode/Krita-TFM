cmake_minimum_required(VERSION 3.28)

add_library(filtermanager_stb STATIC depend/stb/stb.cpp)
target_include_directories(filtermanager_stb PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/depend/stb)
set_target_properties(filtermanager_stb PROPERTIES POSITION_INDEPENDENT_CODE ON)

add_subdirectory(src/visp)

