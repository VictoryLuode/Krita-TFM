set(KRITA_FXMANAGER_SOURCES
    fxmanager_plugin.cpp
    fxmanager_birefnet.cpp
    fxmanager_background_removal.cpp
    fxmanager_processing.cpp
    fxmanager_vulkan.cpp
    tfm_motion_gpu.cpp
    tfm_pointwise_gpu.cpp
    tfm_lens_gpu.cpp
    tfm_bloom_gpu.cpp
    tfm_guided_gpu.cpp
    tfm_kuwahara_gpu.cpp
    tfm_halation_gpu.cpp
    tfm_flare_gpu.cpp
    fxmanager_bloom.cpp
    fxmanager_film_grain.cpp
    fxmanager_lens_distortion.cpp
    fxmanager_lens_distortion_widget.cpp
    fxmanager_vignette.cpp
    fxmanager_vignette_widget.cpp
    fxmanager_color_temperature.cpp
    fxmanager_vibrance.cpp
    fxmanager_kuwahara.cpp
    fxmanager_halation.cpp
    fxmanager_flare.cpp
    fxmanager_light_effects.cpp
    fxmanager_filter_widget.cpp
    fxmanager_drag_spinbox.cpp
    fxmanager_color_range_mask.cpp
    fxmanager_color_range_mask_widget.cpp
    fxmanager_clipboard_color_match.cpp
    fxmanager_clipboard_color_match.h
    fxmanager_statistical_transfer.h
    fxmanager_statistical_profile.h

    fxmanager_clipboard_color_match_widget.cpp
    fxmanager_clipboard_color_match_widget.h
    fxmanager_guided_color_match.h
    fxmanager_guided_widget.h
    fxmanager_guided_color_match_filter.cpp
    fxmanager_guided_color_match_filter.h
    fxm_blur_point_preview.h
    fxm_gegl_motion_blur.cpp
    fxm_gegl_motion_blur.h
    fxm_gegl_focus_blur.cpp
    fxm_gegl_focus_blur.h
    focus_native.cpp
    focus_native.h
    fxmanager_plugin.h
    fxmanager_processing.h
    fxmanager_bloom.h
    fxmanager_film_grain.h
    fxmanager_lens_distortion.h
    fxmanager_lens_distortion_widget.h
    fxmanager_vignette.h
    fxmanager_vignette_widget.h
    fxmanager_color_temperature.h
    fxmanager_vibrance.h
    fxmanager_kuwahara.h
    tfm_kuwahara_gpu.h
    fxmanager_halation.h
    tfm_halation_gpu.h
    fxmanager_flare.h
    tfm_flare_gpu.h
    fxmanager_light_effects.h
    fxmanager_filter_widget.h
    fxmanager_color_range_mask.h
    fxmanager_color_range_mask_widget.h
    fxmanager_color_range_mask_algorithm.h
    fxmanager_birefnet.h
    fxmanager_background_removal.h
)

set(FXMANAGER_VISIONCPP_ROOT "" CACHE PATH "Pinned vision.cpp source tree")
set(FXMANAGER_GGML_ROOT "" CACHE PATH "Pinned ggml source tree")
if (NOT FXMANAGER_VISIONCPP_ROOT OR NOT FXMANAGER_GGML_ROOT)
    message(FATAL_ERROR "FxManager requires FXMANAGER_VISIONCPP_ROOT and FXMANAGER_GGML_ROOT")
endif()

# Keep Krita's BUILD_SHARED_LIBS untouched. Third-party options live only in
# this function's directory scope, including when the host cache says TRUE.
function(fxmanager_add_inference)
    if (TARGET ggml OR TARGET visioncpp OR TARGET stb)
        message(FATAL_ERROR "FxManager inference target collision; refusing to reuse an unknown ggml ABI")
    endif()
    set(BUILD_SHARED_LIBS OFF)
    set(GGML_BACKEND_DL OFF)
    set(GGML_CPU ON)
    set(GGML_OPENMP OFF)
    set(GGML_BUILD_TESTS OFF)
    set(GGML_BUILD_EXAMPLES OFF)
    set(GGML_NATIVE OFF)
    add_subdirectory("${FXMANAGER_GGML_ROOT}" "${CMAKE_BINARY_DIR}/fxmanager-ggml")
    add_subdirectory("${FXMANAGER_VISIONCPP_ROOT}" "${CMAKE_BINARY_DIR}/fxmanager-visioncpp")
    add_library(stb ALIAS filtermanager_stb)
endfunction()
fxmanager_add_inference()

kis_add_library(kritatfm MODULE ${KRITA_FXMANAGER_SOURCES})
target_link_libraries(kritatfm PRIVATE kritaui visioncpp)
target_include_directories(visioncpp PUBLIC
    "${FXMANAGER_VISIONCPP_ROOT}/include"
    "${FXMANAGER_VISIONCPP_ROOT}/src"
    "${FXMANAGER_VISIONCPP_ROOT}/depend/stb"
)
target_link_libraries(visioncpp PRIVATE filtermanager_stb)
target_include_directories(kritatfm PRIVATE "${FXMANAGER_VISIONCPP_ROOT}/include")
target_include_directories(kritatfm PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/vulkan-headers/include")
install(TARGETS kritatfm DESTINATION ${KRITA_PLUGIN_INSTALL_DIR})
