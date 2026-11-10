set(KRITA_TFM_SOURCES
    tfm_plugin.cpp
    tfm_birefnet.cpp
    tfm_background_removal.cpp
    tfm_processing.cpp
    tfm_vulkan.cpp
    tfm_motion_gpu.cpp
    tfm_pointwise_gpu.cpp
    tfm_lens_gpu.cpp
    tfm_bloom_gpu.cpp
    tfm_guided_gpu.cpp
    tfm_kuwahara_gpu.cpp
    tfm_halation_gpu.cpp
    tfm_flare_gpu.cpp
    tfm_bloom.cpp
    tfm_film_grain.cpp
    tfm_lens_distortion.cpp
    tfm_lens_distortion_widget.cpp
    tfm_vignette.cpp
    tfm_vignette_widget.cpp
    tfm_color_temperature.cpp
    tfm_vibrance.cpp
    tfm_kuwahara.cpp
    tfm_halation.cpp
    tfm_flare.cpp
    tfm_filter_widget.cpp
    tfm_drag_spinbox.cpp
    tfm_color_range_mask.cpp
    tfm_color_range_mask_widget.cpp
    tfm_clipboard_color_match.cpp
    tfm_clipboard_color_match.h
    tfm_statistical_transfer.h
    tfm_statistical_profile.h

    tfm_clipboard_color_match_widget.cpp
    tfm_clipboard_color_match_widget.h
    tfm_guided_color_match.h
    tfm_guided_widget.h
    tfm_guided_color_match_filter.cpp
    tfm_guided_color_match_filter.h
    tfm_blur_point_preview.h
    tfm_gegl_motion_blur.cpp
    tfm_gegl_motion_blur.h
    tfm_gegl_focus_blur.cpp
    tfm_gegl_focus_blur.h
    focus_native.cpp
    focus_native.h
    tfm_plugin.h
    tfm_processing.h
    tfm_bloom.h
    tfm_film_grain.h
    tfm_lens_distortion.h
    tfm_lens_distortion_widget.h
    tfm_vignette.h
    tfm_vignette_widget.h
    tfm_color_temperature.h
    tfm_vibrance.h
    tfm_kuwahara.h
    tfm_kuwahara_gpu.h
    tfm_halation.h
    tfm_halation_gpu.h
    tfm_flare.h
    tfm_flare_gpu.h
    tfm_filter_widget.h
    tfm_color_range_mask.h
    tfm_color_range_mask_widget.h
    tfm_color_range_mask_algorithm.h
    tfm_birefnet.h
    tfm_background_removal.h
)

set(TFM_VISIONCPP_ROOT "" CACHE PATH "Pinned vision.cpp source tree")
set(TFM_GGML_ROOT "" CACHE PATH "Pinned ggml source tree")
# Compat with older cache names from the FxManager-era build.
if (NOT TFM_VISIONCPP_ROOT AND DEFINED FXMANAGER_VISIONCPP_ROOT AND FXMANAGER_VISIONCPP_ROOT)
    set(TFM_VISIONCPP_ROOT "${FXMANAGER_VISIONCPP_ROOT}")
endif()
if (NOT TFM_GGML_ROOT AND DEFINED FXMANAGER_GGML_ROOT AND FXMANAGER_GGML_ROOT)
    set(TFM_GGML_ROOT "${FXMANAGER_GGML_ROOT}")
endif()
if (NOT TFM_VISIONCPP_ROOT OR NOT TFM_GGML_ROOT)
    message(FATAL_ERROR "TFM requires TFM_VISIONCPP_ROOT and TFM_GGML_ROOT")
endif()

# Keep Krita's BUILD_SHARED_LIBS untouched. Third-party options live only in
# this function's directory scope, including when the host cache says TRUE.
function(tfm_add_inference)
    if (TARGET ggml OR TARGET visioncpp OR TARGET stb)
        message(FATAL_ERROR "TFM inference target collision; refusing to reuse an unknown ggml ABI")
    endif()
    set(BUILD_SHARED_LIBS OFF)
    set(GGML_BACKEND_DL OFF)
    set(GGML_CPU ON)
    set(GGML_OPENMP OFF)
    set(GGML_BUILD_TESTS OFF)
    set(GGML_BUILD_EXAMPLES OFF)
    set(GGML_NATIVE OFF)
    add_subdirectory("${TFM_GGML_ROOT}" "${CMAKE_BINARY_DIR}/tfm-ggml")
    add_subdirectory("${TFM_VISIONCPP_ROOT}" "${CMAKE_BINARY_DIR}/tfm-visioncpp")
    add_library(stb ALIAS filtermanager_stb)
endfunction()
tfm_add_inference()

kis_add_library(kritatfm MODULE ${KRITA_TFM_SOURCES})
find_package(Python3 COMPONENTS Interpreter REQUIRED)
get_filename_component(TFM_REPO_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../.." ABSOLUTE)
add_custom_target(tfm_generated_files
    COMMAND "${Python3_EXECUTABLE}" "${TFM_REPO_ROOT}/scripts/generate_filter_metadata.py"
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/../compile_shaders.py" --all
    COMMAND "${Python3_EXECUTABLE}" "${TFM_REPO_ROOT}/scripts/generate_filter_metadata.py" --check
    VERBATIM)
add_dependencies(kritatfm tfm_generated_files)
add_executable(tfm_vulkan_worker tfm_vulkan_worker.cpp tfm_vulkan_device.cpp)
target_compile_features(tfm_vulkan_worker PRIVATE cxx_std_17)
target_include_directories(tfm_vulkan_worker PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/vulkan-headers/include")
install(TARGETS tfm_vulkan_worker RUNTIME DESTINATION ${KRITA_PLUGIN_INSTALL_DIR})
target_link_libraries(kritatfm PRIVATE kritaui visioncpp)
target_include_directories(visioncpp PUBLIC
    "${TFM_VISIONCPP_ROOT}/include"
    "${TFM_VISIONCPP_ROOT}/src"
    "${TFM_VISIONCPP_ROOT}/depend/stb"
)
target_link_libraries(visioncpp PRIVATE filtermanager_stb)
target_include_directories(kritatfm PRIVATE "${TFM_VISIONCPP_ROOT}/include")
target_include_directories(kritatfm PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/vulkan-headers/include")
install(TARGETS kritatfm DESTINATION ${KRITA_PLUGIN_INSTALL_DIR})
