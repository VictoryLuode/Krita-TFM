# TFM — Tool & Filter & Menu

Krita plugin for custom menus, native filters, Advance Selection, an asset library, and related tools.

Requires **Krita 5.3** on Windows (Qt5 build). Restart Krita after installing or updating.

<p align="center">
  <video src="https://github.com/VictoryLuode/Krita-TFM/releases/download/0.1.6/tfm-demo-1.mp4" poster="docs/images/tfm-demo-1.jpg" controls preload="metadata" width="720">
    <a href="https://github.com/VictoryLuode/Krita-TFM/releases/download/0.1.6/tfm-demo-1.mp4">Demo 1</a>
  </video>
  <br>
  <video src="https://github.com/VictoryLuode/Krita-TFM/releases/download/0.1.6/tfm-demo-2.mp4" poster="docs/images/tfm-demo-2.jpg" controls preload="metadata" width="720">
    <a href="https://github.com/VictoryLuode/Krita-TFM/releases/download/0.1.6/tfm-demo-2.mp4">Demo 2</a>
  </video>
</p>

Open **Tools → TFM → Configure TFM** for menus, filters, tools, and backends. **Select → Advance Selection…** (also on the Quick Tool popup) for luminance / color-range selections.

## Install (prebuilt)

Close Krita first. From a release zip (`python package_release.py` builds `dist/TFM-<version>.zip`):

1. Copy everything under `resource/` into your Krita **resource** directory.
2. Copy `kritaplugins/kritatfm.dll` and `kritaplugins/tfm_vulkan_worker.exe` into the Krita install `lib/kritaplugins/` folder. Keep both files in the same directory.
3. Start Krita and enable **TFM** under Settings → Manage Resources → Python Plugin Manager if needed.

Settings and menu lists live under `<ResourceDirectory>/TFM/`. BiRefNet models for Background Removal are optional and go under `TFM/background-removal/models/`.

## Release helpers

- `python verify.py` — `__version__` must match the newest `X.Y.Z` git tag.
- `python package_release.py` — zip resource files plus the current `build/native-5.3/bin` DLL and worker.

## Filter backends

- **Settings → Default filter backend**: Auto / CPU / GPU (Vulkan) for filters that support it.
- **Filters** tab → select a Vulkan-capable filter → **Compute backend** for a per-filter override.
- Background Removal keeps its own backend control in the filter dialog.

## Build from source

See `SOURCE-NOTES.md`. Filter plugin: `python native/fx/build.py`. License: GPL-3.0 (`LICENSE`); Menubelt-derived menu code: `LICENSE-MENUBELT`.
