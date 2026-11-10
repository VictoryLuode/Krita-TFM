# TFM 0.1.8

- Preserve U16/F16/F32 processing precision, original alpha and supported HDR/negative values; retain U8 compatibility except the intentional skin-protection and CPU temperature-tint fixes.
- Use snapshot inputs, staged outputs and identity shortcuts; unsupported high-depth GPU paths explain their CPU fallback.
- Add cancellable worker I/O, bounded startup/compute deadlines and restart after worker faults; cancelled work does not restart on CPU.
- Unify search task cancellation, network deadlines and asynchronous shutdown; reject stale results and stabilize status layouts.
- Load asset thumbnails asynchronously with bounded caches and lazy folders; preserve selection, scroll and drag/drop behavior.
- Reuse GPU shaders/pipelines/buffers, scope CPU waits, and calibrate Auto backend choices from measured production operations.
- Separate menu/asset responsibilities, unify filter parameter metadata, and record actionable errors.
- Build complete immutable native batches; verify shader generation, sources, binaries, dependency notices, installation and package hashes.
- Validation: Chinese/English unit and installed-Qt offline checks, real native/GPU/AI regressions. Live Krita interaction and external search-provider acceptance remain for user testing; see `docs/quality-testing.md` and `docs/quality-compatibility.md` for limitations.

# TFM 0.1.7

- Follow Krita’s UI language (Chinese / English) for docks, Tools, menus, and search chrome.
- First-run Quick Tool sample (shortcut Q), Configure welcome guide, and clearer Tools vs Filters restart notes.
- Advanced Selection naming unified; selection actions relabeled Add / Subtract / Clear / Replace with a stale-source cue.
- Quick Image Search: Verify / Reset profile actions, status text beside the icon, dock id aligned for show/hide.
- Asset Library status bar restored; empty states and iconized view toggles.
- Filter backend failures and missing BiRefNet models show actionable tips; Configure Menus/Filters tabs load lazily.
- UI polish: compact menu settings strip, host-palette warnings, pie selection highlight, selection preview frame.

# TFM 0.1.6

- Run Vulkan filter compute in `tfm_vulkan_worker.exe` beside `kritatfm.dll`, so Krita itself does not load `vulkan-1.dll` for those filters.
- Guided Color Match stores a compact grade, rebuilds the LUT on apply, keeps a light preview path, and can still use Vulkan per tile.
- Choose Auto / CPU / GPU per filter under Filters → Compute backend, with a global default in Settings.
- Advanced Selection: longer preview debounce, window-sized preview, more reliable canvas overlay binding.
- Filter manager: cache registry inspect; brush tags read `resourcecache.sqlite` from the resource directory.
