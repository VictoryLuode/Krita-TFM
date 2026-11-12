# TFM 0.1.10

- Remove Statistical Color Match; Guided Color Match remains the color-transfer path.
- Auto/GPU: prefer Vulkan for every supported filter; fall back to CPU only when the worker cannot run the job (no size thresholds).
- Algorithm polish: value-noise film grain + tone response; OKLab vibrance (no skin protect); linear chromatic-adaptation temperature; multi-scale bloom; OKLab color-range channels; Guided LUT residual smoothing; cos⁴ vignette; adaptive motion samples; flare centroid refine; lens cubic term; softer halation falloff.
- Float Vulkan paths for Guided/Flare/Bloom(legacy+diffusion)/Kuwahara/Halation/Lens/pointwise filters; regenerated float shaders.
- GPU memory budget is Settings-tunable (`gpu_memory_mb`, default 1024 MiB, 128–8192); host injects `TFM_VULKAN_MEMORY_MB` and restarts the worker when the budget changes.
- CPU thread count re-reads `TFM/settings.json` on the next filter run; filter enable hot-sync clears stale Filter menu actions; Focus Blur masks allowed.
- Manager tools/settings splits; BiRefNet model-folder CTA; GEGL policy is local GIMP discovery only (never ship GEGL/GIMP in the TFM zip); Relight experimental (`docs/relight-research.md`); search smoke (`TFM_SEARCH_LIVE=1` optional).

# TFM 0.1.9

- Finish Menubelt/FxManager → TFM branding: native `tfm_*` sources, `TFM_*` CMake/env knobs with legacy fallbacks, and documented keep-migration for old installs.
- Configure Filters/Settings bilingual UI, stronger Save Filters → restart affordance, and BiRefNet models-folder onboarding (local README seed).
- Split popup theme and menu-row painting out of the menus extension; keep Relight research behind `--run-experimental` with a skipping native harness.
- Document 30s Vulkan idle TTL, Auto warm Vibrance threshold, and motion-only high-depth float GPU boundary.

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
