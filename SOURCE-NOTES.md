# Source and license notes

TFM (Tool & Filter & Menu) unifies the menu manager (formerly Krita-Menubelt), the filter manager and native filters (formerly Krita-fxmanager), and the Advance Selection tool into a single Krita plugin.

## Architecture and paths

- Python package: `pykrita/tfm/` (`menus/`, `filters/`, `color_range*.py`, `manager.py`), registered via `pykrita/tfm.desktop` and `actions/tfm.action`.
- Action IDs: `tfm_popup`, `tfm_edit`, `tfm_color_range`, `tfm_tools_menu`.
- Native filter plugin: `native/fx/` builds `kritatfm.dll`. Registered filters: `tfm_bloom`, `tfm_filmgrain`, `tfm_lens_distortion`, `tfm_vignette`, `tfm_color_temperature`, `tfm_vibrance`, `tfm_kuwahara`, `tfm_halation`, `tfm_lens_flare`, `tfm_anamorphic_flare`, `tfm_light_rays`, `tfm_light_leaks`, `tfm_light_patch`, `tfm_color_range_mask`, `tfm_clipboard_color_match`, `tfm_guided_color_match`, `tfm_background_removal`, `tfm_motion_blur_circular`, `tfm_motion_blur_zoom`, and `tfm_focus_blur`.
- Native selection kernel: `native/color_range.c` builds `pykrita/tfm/native/tfm_color_range.dll`.
- User data and runtime directory under Krita's active `ResourceDirectory`:
  - `<ResourceDirectory>/TFM/config.json` (menu lists, shortcuts, overrides)
  - `<ResourceDirectory>/TFM/scripts/` (user scripts)
  - `<ResourceDirectory>/TFM/settings.json` (filter manager settings and defaults, shared between Python and `kritatfm.dll`)
  - `<ResourceDirectory>/TFM/background-removal/models/` and `runtime/` (BiRefNet `.gguf` models and Vulkan/GGML runtime DLLs)

## Provenance and licensing

- `pykrita/tfm/menus/` and `pykrita/tfm/scripts/luminosity_view.py` derive from Krita-Menubelt (GNU GPL v3; see `LICENSE-MENUBELT`).
- `native/fx/third_party/` embeds `vision.cpp` and `ggml` (MIT) and `stb` (MIT / public domain dual license). Retain the corresponding license notices when distributing binaries.

## Build notes

- Color-range kernel (Advance Selection):
  `clang -shared -O2 -ffast-math -o pykrita/tfm/native/tfm_color_range.dll native/color_range.c`
  (llvm-mingw / clang on PATH). Deploy with `python deploy.py` when Krita is closed.

