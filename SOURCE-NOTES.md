# Source and license notes

TFM (Tool & Filter & Menu) combines custom menus, the filter manager and native filters, and the Advance Selection tool into a single Krita plugin.

## Architecture and paths

- Python package: `pykrita/tfm/` (`menus/`, `filters/`, `assets/`, `color_range*.py`, `manager.py`), registered via `pykrita/tfm.desktop` and `actions/tfm.action`.
- Quick Image Search tool package: `pykrita/quick_image_search/` (imported by `tfm/search.py`; no separate `.desktop`).
- Action IDs: `tfm_popup`, `tfm_edit`, `tfm_color_range`, `tfm_assets`, `tfm_save_asset`, `tfm_image_search`, `tfm_convert_color_space`, `tfm_tools_menu`.

- Native filter plugin: `native/fx/` builds `kritatfm.dll` plus `tfm_vulkan_worker.exe` (same folder as the DLL). Vulkan compute for supported filters runs in the worker process over a local pipe; `kritatfm.dll` must not load `vulkan-1.dll`.
- Registered filters: `tfm_bloom`, `tfm_filmgrain`, `tfm_lens_distortion`, `tfm_vignette`, `tfm_color_temperature`, `tfm_vibrance`, `tfm_kuwahara`, `tfm_halation`, `tfm_lens_flare`, `tfm_anamorphic_flare`, `tfm_light_rays`, `tfm_light_leaks`, `tfm_light_patch`, `tfm_color_range_mask`, `tfm_clipboard_color_match`, `tfm_guided_color_match`, `tfm_background_removal`, `tfm_motion_blur_circular`, `tfm_motion_blur_zoom`, and `tfm_focus_blur`.
- Native selection kernel: `native/color_range.c` builds `pykrita/tfm/native/tfm_color_range.dll`.
- User data under Krita's active `ResourceDirectory`:
  - `<ResourceDirectory>/TFM/config.json` (menu lists, shortcuts, overrides)
  - `<ResourceDirectory>/TFM/scripts/` (user scripts)
  - `<ResourceDirectory>/TFM/settings.json` (global backend, per-filter `filter_backends`, defaults; shared by Python and `kritatfm.dll`)
  - `<ResourceDirectory>/TFM/background-removal/models/` and `runtime/` (BiRefNet `.gguf` models and optional Vulkan/GGML runtime DLLs)

## Provenance and licensing

- Project license: GNU GPL v3 (`LICENSE`).
- `native/fx/third_party/` embeds `vision.cpp` and `ggml` (MIT) and `stb` (MIT / public domain dual license). Retain the corresponding license notices when distributing binaries.
- BiRefNet model files and GIMP/GEGL redistributable DLLs are not part of the default TFM zip; see `docs/gegl-isolated-runtime.md` before bundling them.

## Build notes

- Filters / Vulkan worker (Krita closed): `python native/fx/build.py`
- Color-range kernel (Advance Selection):
  `clang -shared -O2 -ffast-math -o pykrita/tfm/native/tfm_color_range.dll native/color_range.c`
  (llvm-mingw / clang on PATH).
- Local install when Krita is closed: `python deploy.py` (machine-local script; not shipped in the public tree).
