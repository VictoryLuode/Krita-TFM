"""Catalog of the filters TFM manages.

This is a registry view, not a usage menu: the panel lists what the C++ plugin
registers, whether Krita actually picked it up, and which settings the filter
exposes. Applying a filter stays in Krita's own filter menu and layer stack.
"""

FILTERS = [
    {
        "id": "tfm_bloom",
        "label": "Bloom",
        "description": "Soft highlight glow around bright areas.",
        "category": "Artistic",
        "settings": [
            {"key": "threshold", "label": "Threshold", "min": 0.0, "max": 1.0, "default": 0.7},
            {"key": "radius", "label": "Radius", "min": 1.0, "max": 64.0, "default": 12.0},
            {"key": "strength", "label": "Strength", "min": 0.0, "max": 2.0, "default": 0.65},
        ],
    },
    {
        "id": "tfm_filmgrain",
        "label": "Film Grain",
        "description": "Procedural monochrome grain for film texture.",
        "category": "Artistic",
        "settings": [
            {"key": "preset", "label": "Preset", "default": "super_8", "options": [
                ["8mm_caffenol", "8 mm Caffenol"],
                ["8mm_home_movie", "8 mm Home Movie"],
                ["super_8", "Super 8 mm"],
                ["16mm_broadcast", "16 mm Broadcast"],
                ["16mm_indie_cinema", "16 mm Indie Cinema"],
                ["35mm_portra_400", "35 mm Portra 400"],
                ["super_35", "Super 35 mm"],
                ["70mm_cinema", "70 mm Cinema"],
                ["custom", "Custom"],
            ]},
            {"key": "amount", "label": "Amount", "min": 0.0, "max": 1.0, "default": 0.18},
            {"key": "size", "label": "Size", "min": 0.5, "max": 8.0, "default": 2.0},
            {"key": "seed", "label": "Seed", "type": "integer", "min": 0, "max": 999, "default": 17},
            {"key": "monochrome", "label": "Monochrome", "default": True},
        ],
    },
    {
        "id": "tfm_lens_distortion",
        "label": "Lens Distortion",
        "description": "Single-centre radial distortion or horizontal chromatic dispersion.",
        "category": "Artistic",
        "settings": [
            {"key": "mode", "label": "Mode", "default": "radial", "options": ["radial", "horizontal"]},
            {"key": "distortion", "label": "Distortion", "min": -1.0, "max": 1.0, "default": 0.0},
            {"key": "dispersion", "label": "Dispersion", "min": 0.0, "max": 1.0, "default": 0.0},
            {"key": "jitter", "label": "Jitter", "default": False},
            {"key": "fit", "label": "Fit", "default": False},
        ],
    },
    {
        "id": "tfm_vignette",
        "label": "Vignette",
        "description": "Blender-style vignette with factor, feather, shape and transform controls.",
        "category": "Artistic",
        "settings": [
            {"key": "factor", "label": "Factor", "min": 0.0, "max": 1.0, "default": 1.0},
            {"key": "feather", "label": "Feather", "min": 0.0, "max": 1.0, "default": 0.4},
            {"key": "corner_roundness", "label": "Corner Roundness", "min": 0.0, "max": 1.0, "default": 1.0},
            {"key": "scale_x", "label": "Scale X", "min": 0.0001, "max": 4.0, "default": 0.8},
            {"key": "scale_y", "label": "Scale Y", "min": 0.0001, "max": 4.0, "default": 0.8},
            {"key": "offset_x", "label": "Offset X", "min": -2.0, "max": 2.0, "default": 0.0},
            {"key": "offset_y", "label": "Offset Y", "min": -2.0, "max": 2.0, "default": 0.0},
            {"key": "angle", "label": "Angle", "min": -180.0, "max": 180.0, "default": 0.0},
        ],
    },
    {
        "id": "tfm_clipboard_color_match",
        "label": "Statistical Color Match",
        "description": "Statistical Lab colour transfer from a clipboard image or file. The reference is analysed by the filter configuration; the target image is not modified until Krita applies the filter.",
        "category": "Colors",
        "settings": [
            {"key": "reference_source", "label": "Source", "type": "enum", "default": "clipboard", "options": [
                ["clipboard", "Clipboard"], ["file", "File"]
            ]},
            {"key": "refresh_reference", "label": "Refresh", "type": "action"},
            {"key": "choose_reference_file", "label": "Choose File…", "type": "action"},
            {"key": "match_strength", "label": "Match Strength", "type": "number", "min": 0.0, "max": 1.0, "default": 1.0},
            {"key": "luminance", "label": "Luminance", "type": "number", "min": 0.0, "max": 2.0, "default": 1.0},
            {"key": "color_intensity", "label": "Color Intensity", "type": "number", "min": 0.0, "max": 2.0, "default": 1.0},
            {"key": "fade", "label": "Fade", "type": "number", "min": 0.0, "max": 1.0, "default": 0.0},
            {"key": "preserve_alpha", "label": "Preserve Alpha", "type": "bool", "default": True, "editable": False},
            {"key": "tone_distribution", "label": "Tone Distribution", "type": "slider", "min": 0.0, "max": 1.0, "default": 0.0},
            {"key": "tonal_color", "label": "Tonal Color", "type": "slider", "min": 0.0, "max": 1.0, "default": 0.0},
            {"key": "color_correlation", "label": "Color Correlation", "type": "slider", "min": 0.0, "max": 1.0, "default": 0.0},
            {"key": "gain_limit", "label": "Gain Limit", "type": "number", "min": 1.0, "max": 8.0, "default": 2.0},
            {"key": "shift_limit", "label": "Color Shift Limit", "type": "number", "min": 0.0, "max": 100.0, "default": 51.0},
            {"key": "variance_floor", "label": "Variance Floor", "type": "number", "min": 0.1, "max": 10.0, "default": 2.55},
            {"key": "gamut_protection", "label": "sRGB Gamut Protection", "type": "bool", "default": False},
            {"key": "reanalyze_target", "label": "Re-analyze Target", "type": "action"},
        ],
    },
    {
        "id": "tfm_guided_color_match",
        "label": "Guided Color Match",
        "description": "Point guided colour transfer with a smooth 33 cubed LUT and neutral protection.",
        "category": "Colors",
        "settings": [
            {"key": "match_strength", "label": "Match Strength", "min": 0.0, "max": 1.0, "default": 1.0},
            {"key": "luminance", "label": "Luminance", "min": 0.0, "max": 1.0, "default": 0.0},
            {"key": "chroma", "label": "Chroma", "min": 0.0, "max": 2.0, "default": 1.0},
            {"key": "shadow_color", "label": "Shadow Color", "min": 0.0, "max": 1.0, "default": 1.0},
            {"key": "highlight_warmth", "label": "Highlight Warmth", "min": 0.0, "max": 2.0, "default": 1.0},
            {"key": "neutral_protection", "label": "Neutral Protection", "min": 0.0, "max": 1.0, "default": 0.0},
            {"key": "smoothness", "label": "Smoothness", "min": 0.0, "max": 1.0, "default": 0.35},
        ],
    },
    {
        "id": "tfm_background_removal",
        "label": "Background Removal",
        "description": "Remove image backgrounds with BiRefNet. Choose a model, compute backend, and foreground refinement mode in Krita's native filter configuration.",
        "category": "Segmentation",
        "settings": [
            {"key": "model", "label": "Model", "default": "BiRefNet-lite-F16.gguf", "options": [
                ["BiRefNet-lite-F16.gguf", "BiRefNet Lite"],
                ["BiRefNet-dynamic-F16.gguf", "BiRefNet Dynamic"],
            ]},
            {"key": "backend", "label": "Backend", "default": "cpu", "options": ["cpu", "gpu"]},
            {"key": "foreground_mode", "label": "Foreground", "default": "refined_foreground", "options": [
                ["fast_mask", "Fast Mask"],
                ["refined_foreground", "Refined Foreground"],
            ]},
            {"key": "output_mode", "label": "Output", "default": "cutout", "options": [
                ["cutout", "Cutout"], ["grayscale_mask", "Grayscale Mask"]
            ]},
            {"key": "preserve_foreground", "label": "Preserve Foreground", "type": "integer", "min": 0, "max": 100, "default": 0},
            {"key": "mask_contrast", "label": "Mask Contrast", "type": "integer", "min": -100, "max": 100, "default": 0},
        ],
    },
    {
        "id": "tfm_color_range_mask",
        "label": "Color Range Mask",
        "description": "Alpha-only mask driven by a selected grayscale or RGB channel range; it changes alpha while preserving RGB when enabled.",
        "category": "Artistic",
        "settings": [
            {"key": "channel", "label": "Channel", "default": "gray"},
            {"key": "range_min", "label": "Range Min", "min": 0.0, "max": 1.0, "default": 0.0},
            {"key": "range_max", "label": "Range Max", "min": 0.0, "max": 1.0, "default": 1.0},
            {"key": "softness", "label": "Softness", "min": 0.0, "max": 0.5, "default": 0.05},
            {"key": "invert", "label": "Invert", "default": False},
            {"key": "preserve_rgb", "label": "Preserve RGB", "default": True, "editable": False},
        ],
    },
    {
        "id": "tfm_motion_blur_circular",
        "label": "Circular Motion Blur",
        "description": "Rotational motion blur around a configurable focal center (GEGL motion-blur-circular).",
        "category": "Blur",
        "settings": [
            {"key": "center_x", "label": "Center X", "min": -1.0, "max": 2.0, "default": 0.5},
            {"key": "center_y", "label": "Center Y", "min": -1.0, "max": 2.0, "default": 0.5},
            {"key": "angle", "label": "Angle", "min": 0.0, "max": 360.0, "default": 20.0},
        ],
    },
    {
        "id": "tfm_motion_blur_zoom",
        "label": "Zoom Motion Blur",
        "description": "Fixed document-coordinate radial sampling with bounded support; extreme factors may exceed the processing limit.",
        "category": "Blur",
        "settings": [
            {"key": "center_x", "label": "Center X", "min": -1.0, "max": 2.0, "default": 0.5},
            {"key": "center_y", "label": "Center Y", "min": -1.0, "max": 2.0, "default": 0.5},
            {"key": "factor", "label": "Blurring Factor", "min": -10.0, "max": 1.0, "default": 0.1},
        ],
    },
    {
        "id": "tfm_focus_blur",
        "label": "Focus Blur",
        "description": "Native CPU depth-of-field / tilt-shift blur. F32 filter masks may show small boundary differences; use a paint layer or adjustment layer for F32 documents.",
        "category": "Blur",
        "settings": [
            {"key": "blur_type", "label": "Blur Type", "default": "gaussian", "options": [
                ["gaussian", "Gaussian Blur"],
                ["lens", "Lens Blur"],
            ]},
            {"key": "blur_radius", "label": "Blur Radius", "min": 0.0, "max": 200.0, "default": 25.0},
            {"key": "highlight_factor", "label": "Highlight Factor", "min": 0.0, "max": 1.0, "default": 0.0},
            {"key": "highlight_threshold_low", "label": "Highlight Threshold (Low)", "min": 0.0, "max": 1.0, "default": 0.0},
            {"key": "highlight_threshold_high", "label": "Highlight Threshold (High)", "min": 0.0, "max": 1.0, "default": 1.0},
            {"key": "shape", "label": "Shape", "default": "circle", "options": [
                ["circle", "Circle"],
                ["square", "Square"],
                ["diamond", "Diamond"],
                ["horizontal", "Horizontal"],
                ["vertical", "Vertical"],
            ]},
            {"key": "x", "label": "Center X", "min": -1.0, "max": 2.0, "default": 0.5},
            {"key": "y", "label": "Center Y", "min": -1.0, "max": 2.0, "default": 0.5},
            {"key": "radius", "label": "Outer Radius", "min": 0.0, "max": 3.0, "default": 0.75},
            {"key": "focus", "label": "Sharpness (Focus)", "min": 0.0, "max": 1.0, "default": 0.25},
            {"key": "midpoint", "label": "Transition Midpoint", "min": 0.0, "max": 1.0, "default": 0.5},
            {"key": "aspect_ratio", "label": "Aspect Ratio", "min": -1.0, "max": 1.0, "default": 0.0},
            {"key": "rotation", "label": "Rotation", "min": -180.0, "max": 180.0, "default": 0.0},
            {"key": "high_quality", "label": "High Quality", "default": False},
        ],
    },
]


# Only configuration parameters, never reference images, profiles or statistics.
FILTER_DEFAULT_SPECS = {}
for _entry in FILTERS:
    _specs = [dict(spec) for spec in _entry["settings"]
              if spec.get("editable", True) and spec.get("type") != "action"
              and ("options" in spec or ("min" in spec and "max" in spec)
                   or isinstance(spec.get("default"), bool))]
    FILTER_DEFAULT_SPECS[_entry["id"]] = _specs
FILTER_DEFAULT_SPECS["tfm_bloom"].extend([
    {"key": "diffusion", "label": "Diffusion", "min": 0.0, "max": 1.0, "default": 1.0},
    {"key": "softness", "label": "Softness", "min": 0.0, "max": 1.0, "default": 0.0},
])
FILTER_DEFAULT_SPECS["tfm_color_range_mask"].insert(0, {
    "key": "channel", "label": "Channel", "default": "gray",
    "options": ["gray", "r", "g", "b", "hue", "saturation"]})
