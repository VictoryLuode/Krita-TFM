# TFM — Tool & Filter & Menu

Krita plugin for custom menus, native filters, Advance Selection, an asset library, and related tools.

Requires **Krita 5.3** on Windows (Qt5 build). Restart Krita after installing or updating.

## Install (prebuilt)

1. Close Krita.
2. Copy `pykrita/tfm/` and `pykrita/tfm.desktop` into your Krita **resource** `pykrita/` folder.
3. Copy `actions/tfm.action` into the resource `actions/` folder.
4. Copy `kritatfm.dll` and `tfm_vulkan_worker.exe` into the Krita install `lib/kritaplugins/` folder. Keep both files in the same directory.
5. Start Krita and enable **TFM** under Settings → Manage Resources → Python Plugin Manager if needed.

Settings and menu lists live under `<ResourceDirectory>/TFM/`. BiRefNet models for Background Removal are optional and go under `TFM/background-removal/models/`.

## Filter backends

- **Settings → Default filter backend**: Auto / CPU / GPU (Vulkan) for filters that support it.
- **Filters** tab → select a Vulkan-capable filter → **Compute backend** for a per-filter override.
- Background Removal keeps its own backend control in the filter dialog.

## Build from source

See `SOURCE-NOTES.md`. Filter plugin: `python native/fx/build.py`. License: GPL-3.0 (`LICENSE`); Menubelt-derived menu code: `LICENSE-MENUBELT`.
