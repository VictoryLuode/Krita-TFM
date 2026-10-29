# Source and license notes

TFM (Tool & Filter & Menu) unifies the menu manager (formerly Krita-Menubelt), the filter manager and native filters (formerly Krita-fxmanager), and the Advance Selection tool into a single Krita plugin.

## Architecture and paths

- Python package: `pykrita/tfm/` (`menus/`, `filters/`, `color_range*.py`, `manager.py`), registered via `pykrita/tfm.desktop` and `actions/tfm.action`.
- Action IDs: `tfm_popup`, `tfm_edit`, `tfm_color_range`, `tfm_tools_menu`.
- Native filter plugin: `native/fx/` builds `kritatfm.dll` (registering `tfm_bloom`, `tfm_filmgrain`, `tfm_lens_distortion`, `tfm_vignette`, `tfm_color_range_mask`, `tfm_clipboard_color_match`, `tfm_guided_color_match`, and `tfm_background_removal`).
- Native selection kernel: `native/color_range.c` builds `pykrita/tfm/native/tfm_color_range.dll`.
- User data and runtime directory under Krita's active `ResourceDirectory`:
  - `<ResourceDirectory>/TFM/config.json` (menu lists, shortcuts, overrides)
  - `<ResourceDirectory>/TFM/scripts/` (user scripts)
  - `<ResourceDirectory>/TFM/settings.json` (filter manager settings and defaults, shared between Python and `kritatfm.dll`)
  - `<ResourceDirectory>/TFM/background-removal/models/` and `runtime/` (BiRefNet `.gguf` models and Vulkan/GGML runtime DLLs)

## Provenance and licensing

- `pykrita/tfm/menus/` and `pykrita/tfm/scripts/luminosity_view.py` derive from Krita-Menubelt (GNU GPL v3; see `LICENSE-MENUBELT`).
- `native/fx/third_party/` embeds `vision.cpp` and `ggml` (MIT) and `stb` (MIT / public domain dual license). Retain the corresponding license notices when distributing binaries.
