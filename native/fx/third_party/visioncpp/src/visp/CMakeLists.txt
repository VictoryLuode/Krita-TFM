add_library(visioncpp STATIC)

target_sources(visioncpp PRIVATE
  arch/birefnet.cpp
  arch/swin.cpp
  image.cpp
  ml.cpp
  nn.cpp
  platform.cpp
  vision_birefnet.cpp
)
target_compile_features(visioncpp PUBLIC cxx_std_20)
target_compile_definitions(visioncpp PUBLIC VISP_STATIC PRIVATE ${VISP_ASSERT} ${VISP_DEFINITIONS})
target_compile_options(visioncpp PRIVATE ${VISP_WARNINGS} ${VISP_COMP_OPTIONS})
target_include_directories(visioncpp PUBLIC
  $<BUILD_INTERFACE:${PROJECT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
  PRIVATE ..
)
target_link_options(visioncpp PRIVATE ${VISP_LINK_OPTIONS})
target_link_libraries(visioncpp
  PUBLIC ggml
  PRIVATE stb ${VISP_FMT_LINK}
)
set_target_properties(visioncpp PROPERTIES
  VERSION ${PROJECT_VERSION}
  SOVERSION ${PROJECT_VERSION_MAJOR}
)

if (MSVC AND VISP_TESTS AND NOT VISP_PACKAGE)
  set_target_properties(visioncpp PROPERTIES WINDOWS_EXPORT_ALL_SYMBOLS ON)
endif()
