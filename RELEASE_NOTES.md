# TFM 0.1.6

- Run Vulkan filter compute in `tfm_vulkan_worker.exe` beside `kritatfm.dll`, so Krita itself does not load `vulkan-1.dll` for those filters.
- Guided Color Match stores a compact grade, rebuilds the LUT on apply, keeps a light preview path, and can still use Vulkan per tile.
- Choose Auto / CPU / GPU per filter under Filters → Compute backend, with a global default in Settings.
- Advance Selection: longer preview debounce, window-sized preview, more reliable canvas overlay binding.
- Filter manager: cache registry inspect; brush tags read `resourcecache.sqlite` from the resource directory.
