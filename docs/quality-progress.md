# Quality candidate delivery ledger

Work is isolated on `codex/quality-20261109`. The starting tracked and untracked
changes were copied into the isolated checkout and retained in the baseline.
This candidate changes no release version and is not a daily deployment.

## Final candidate record

Final batch: `cc0dce47dc45012ab04715e45a2d523124cfe99e7084e91d2f1bac3036d29dab`.
Candidate ZIP: `dist/TFM-quality-candidate-20261109.zip` (1.65 MiB).
ZIP SHA-256: `774508be5bbd71ca1f5b8051268637ca77a9c97aa8188e3e67a5ff76256b9641`.

| Final suite | Result |
|---|---|
| Unit, English | 260 passed; 3 host checks intentionally deselected |
| Unit, Chinese | 260 passed; 3 host checks intentionally deselected |
| Installed Qt offline, English | 3 passed |
| Installed Qt offline, Chinese | 3 passed |
| Native production / GPU / actual inference | 35 passed |
| Complete candidate staging / injected rollback / ZIP verification | Passed; 83 installed files, 102 package members |

No selected production test was skipped. The validation status is explicitly
`passed_with_live_host_gap`; the outstanding checks below are not counted as
passed. Original checkout comparison covered 1268 baseline entries, preserving
the two already-deleted files and all original content.

## Phase status

| Phase | Implemented result | Acceptance boundary |
|---|---|---|
| 1. Baseline/testing | Python 3.13 + Qt5 runner, separate unit/offline/native/experimental suites, both languages, import isolation, production algorithm tests | Final aggregate results are in the batch-bound validation report |
| 2. Image correctness | Skin protection and CPU tint fixes; all 17 registered filters audited; high-depth float paths, precise alpha, identity returns, staged/snapshot processing | Actual device, GPU, inference and ICC checks passed; live preview/application remains unverified |
| 3. Lifecycle | Cancellable bounded worker IPC, structured outcomes, owned-process cleanup, search generations/deadlines, asynchronous close | Fault-injection and local-network checks passed; real external providers remain unverified |
| 4. Performance | Async bounded thumbnail pool/cache, visible priority, lazy directories, pipeline/buffer cache, calibrated Auto thresholds, scoped CPU waits, stable status layout | Fixed-fixture measurements and interaction regressions recorded in quality-performance.md |
| 5. Structure | Menu editor/model/shortcuts/scripts, asset views/operations/drag-drop, action/persistence separation; canonical parameter metadata; shared diagnostics | Existing catalog contract, 17 factories/111 parameters, presets and compatibility exports tested |
| 6. Delivery | Deterministic generation checks, immutable complete batches, shared file inventory, licenses, source/binary/package hash validation, isolated staging and rollback | Candidate package and final verification record; actual-host gate explicitly outstanding |

## Correctness evidence

- 48 pointwise combinations: four filters, U8/U16/F16/F32 and three profiles.
  Zero-effect byte identity, alpha, high-depth gradients, HDR/negative values and
  full/tiled output are checked against actual production paint devices.
- 36 spatial combinations: nine modes across four depths and both tile orders.
  All nine U8 raw outputs remain byte-identical to preserved original sources.
  Cancellation before and during a large operation leaves original data intact.
- 36 colour-transfer combinations and 16 focus/motion combinations exercise
  precision, identities, transparency and full/tiled consistency.
- Actual F32 motion GPU errors are below 4.4e-6. Real pointwise worker dispatches
  are checked against CPU. Shader compilation is executed, including rejection
  of stale embedded SPIR-V after changing the source.
- Real BiRefNet-lite inference exercises mask-only and refined composition.
  Model files are explicit test inputs and are not bundled with the candidate.
- Custom matrix/TRC ICC tests cover ClayRGB gamma 2.2/sRGB and custom primaries
  with gamma 1.8/Rec.709 curves in F16/F32. Raw F32 AOV handling is separately
  tested; non-F32 storage cannot be mistaken for raw float channels.
- Skin protection and CPU temperature tint are intentional U8 algorithm fixes.
  Temperature at zero tint, grain, vignette and nine spatial U8 modes retain
  preserved outputs. Unsupported nonlinear LUT ICC HDR conversion is refused
  with a diagnostic, preserving original pixels. See quality-compatibility.md.

## Lifecycle and interaction evidence

The real GPU client is compiled against fault-injection peers: stalled startup,
send backpressure, stalled result, short reads, disconnect, malformed protocol,
unavailable device, cancellation while waiting, restart and idle cleanup.
Default deadlines are 10 seconds startup and 120 seconds dispatch; positive
`TFM_VULKAN_STARTUP_TIMEOUT_MS` and `TFM_VULKAN_DISPATCH_TIMEOUT_MS` overrides are
bounded to one hour. User cancellation does not start a CPU retry.

Search tasks carry generation IDs and total deadlines. Qt replies abort, queued
work stops submitting, and stale results are rejected. Close uses asynchronous
cleanup; application exit has a shared three-second budget. History/favourites
are saved before shutdown, while regenerable thumbnail jobs can be abandoned.
Browser process termination is restricted to owned processes.

Asset regression covers corrupt/large files, fast directory changes, selection,
scroll restoration, rename and internal MIME movement. A refresh scroll jump
found during final integration was fixed and included in the final measurement.
QImage work stays in two background workers; QPixmap/Icon updates stay on the GUI
thread. The cache is bounded to 64 MiB and invalidated by file identity/size/time.

## Performance evidence

On the fixed 1000-item mixed-asset fixture, directory-switch median changed
411.7 to 80.2 ms, P95 654.0 to 141.0 ms, and peak process working set 134.1 to
55.1 MiB. GUI heartbeat P95 changed 551.3 to 12.2 ms. These are offline fixture
measurements, not a promise for every disk or live document.

All 32 worker-cache comparison outputs remained byte-identical. Shader/pipeline
LRU capacity is 16; buffers reuse capacity within the existing 128 MiB limit.
The two-second worker idle lifetime is retained. Auto backend thresholds use
actual end-to-end measurements; unsupported/high-depth paths explain CPU fallback.
Manual GPU choice remains available where the backend supports it.

## Delivery records

- `build/test-results/candidate-validation.json`: exact batch ID, suite counts,
  skips, durations, and explicit live-host/provider gaps. Included as
  `VALIDATION.json` in the ZIP.
- `build/candidate-evidence/delivery-validation.json`: package SHA-256, full
  staging checks, rollback after a final native-file failure, overwrite refusal,
  ZIP inventory/hashes and absence of developer-machine paths.
- `build/candidate-evidence/visual-comparison.html`: portable embedded before/after
  synthetic previews, with raw numeric metrics in the adjacent JSON. Display PNGs
  are not HDR proof and do not replace raw comparisons.
- `build/quality-baseline/`: input hashes, original changes, source snapshots,
  binary and numeric baselines. Development evidence is not installed as a plugin.
- `docs/candidate-install.md`: installation and complete-batch rollback procedure.

## Outstanding live-host acceptance

A copied Krita executable did not provide profile isolation: Windows Qt5 Known
Folders ignored APPDATA/LOCALAPPDATA overrides, so the probe did not load. That
attempt was stopped. The normal configuration, display and shortcut files kept
their pre-attempt modification times; this is not a blanket claim about all logs.
The launcher now refuses that environment before opening the GUI.

Live preview/apply, undo/redo, preset reopening, asset canvas insertion, native
panel integration and external search/browser provider smoke tests remain
unverified. A separate OS user/test environment is required to run the isolated
live-host probe. Offline checks are not substituted for this acceptance.
Existing Focus Blur F32 filter-mask limits and unsupported nonlinear ICC cases
are documented in quality-compatibility.md. Formal deployment, versioning and
release remain separate user decisions.
