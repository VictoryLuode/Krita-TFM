# Filter precision and compatibility

The canonical parameter description is `schema/filters.json` (version 1).
`scripts/generate_filter_metadata.py` generates the Python catalog and C++
metadata. All 16 filter IDs, legacy aliases, defaults, options and visible
parameter ranges are preserved. The pre-refactor public catalog has a frozen
contract hash; actual production factory defaults and override validation are
tested against the generated parameter metadata. Special native layouts and
historical preset fallback rules remain handwritten. Halation's legacy
fractional quality override is explicitly retained even though its editor
presents an integer.

## Processing paths

All rows have CPU U8/U16/F16/F32 paths. “Float” describes the intermediate, not
a change to the original profile or user configuration. U8 uses the compatibility
path. High-depth algorithms retain their existing required colour encoding.

| Filters | High-depth intermediate / output | Vulkan support |
|---|---|---|
| Vibrance, Color Temperature, Film Grain, Vignette | Extended encoded sRGB float; precise original alpha | U8 and high-depth float GPU (`pointwise_float`); else CPU |
| Bloom (legacy and diffusion), Halation, Kuwahara | Float colour data and staged result | U8 + float Vulkan (legacy/diffusion bloom, kuwahara,halation) when requested; CPU fallback on reject |
| Lens Flare, Anamorphic Flare, Lens Distortion (both modes) | Float colour sampling; snapshot plus staged output | U8 + float Vulkan when requested; CPU fallback on reject |
| Color Range Mask | Float mask calculation; original raw RGB retained, precise alpha | U8 + float pointwise GPU when requested; CPU fallback on reject |
| Guided Color Match | Float LUT sampling plus out-of-range residual; identity early return | U8 + float LUT GPU when requested; CPU fallback on reject |
| Circular / Zoom Motion Blur | Linear float snapshot and output | U8/U16/F16/F32 through float worker buffers |
| Focus Blur | Existing native float processing | CPU |
| Background Removal | Model may use U8; precise original colour/alpha composition | Separate model backend; main Vulkan-worker policy does not apply |

Manual GPU selection is respected where supported. Unsupported float GPU paths
report a CPU fallback; no high-depth image is quantized to U8 to claim GPU
success. The per-buffer GPU limit defaults to 1024 MiB and is tunable in Settings
(`gpu_memory_mb` / `TFM_VULKAN_MEMORY_MB`, clamped 128–8192). Idle worker exit
defaults to thirty seconds (`TFM_VULKAN_IDLE_MS`). High-depth float GPU covers motion blur, pointwise filters (including Color
Range Mask), Guided LUT, Bloom (legacy + diffusion), flares, Kuwahara, Halation
and Lens Distortion. Unsupported paths still fall back with an explicit CPU
reason. Focus Blur filter masks are allowed; they share the snapshot + staged
core path with paint devices (neededRect/halo for edge tiles).
AI model files and optional external GPU inference runtimes are not in the zip.
Place BiRefNet `.gguf` models under `TFM/background-removal/models/` and optional
runtime DLLs under `…/runtime/` (Configure TFM → Filters can open either folder
and seed a local README).

## Image checks

- Pointwise: 48 combinations of four filters, four depths and three standard
  profiles; zero-effect identity, alpha, >512 high-depth gradient levels, signed/HDR values,
  and full/tiled byte equality.
- Spatial: nine modes across four depths, two tile traversal orders, zero tile
  differences and cancellation before/during execution. Preserved U8 baselines
  for these nine modes compare byte-for-byte.
- Colour transfer: guided cases cover profiles/depths and identity
  configurations. Focus/motion cover all depths; actual F32 circular/zoom GPU
  comparisons have maximum errors below 4.4e-6 on the measured fixture.
- Actual CPU BiRefNet mask-only and refined inference preserve source colour
  precision and multiply original alpha by the model mask.
- Actual pointwise worker output is compared against CPU; separate lifecycle
  tests compile the real client and inject stalled, corrupt and crashing peers.
- Additional ICC tests cover ClayRGB gamma 2.2, ClayRGB sRGB TRC and custom
  primaries with gamma 1.8 / Rec.709 TRC in F16 and F32. Maximum measured roundtrip
  error is below 4.8e-7, alpha unchanged, with in-range values independently
  checked against Krita's colour engine.
- Raw RGBA F32 AOV data bypasses ICC entirely; other storage types are explicitly
  rejected by the raw-data interface rather than mistaken for float bytes.

## Intentional changes and limits

Color Temperature's CPU tint uses the same /100 scale as its documented
range/GPU path. Vibrance no longer applies skin protection. Temperature with
zero tint, grain, vignette and the nine spatial U8 modes retain their
preserved baseline outputs where still applicable.

Standard sRGB float uses an analytic extended transfer. Matrix/TRC RGB profiles
use their actual colourant matrices; standard gamma curves use signed extensions.
For other normalized matrix TRCs, the endpoint tangent extends values above one,
negative values use a signed extension, and the actual forward curve is inverted
numerically to avoid a 16-bit inverse lookup. ICC does not define arbitrary HDR
extrapolation for every profile, so these extension rules are explicit.

HDR input/output using a LUT-based or otherwise unsupported non-linear ICC
profile is refused with a diagnostic and original pixels retained. It is not
silently clipped or advertised as supported. Custom CMYK/other colour models
and every possible ICC profile have not been exhaustively verified.

Focus Blur may be used as a filter mask; paint or adjustment layers remain
available alternatives. Real Krita preview/application,
undo/redo, preset reopening, canvas insertion and external provider integration
remain a separate live-host gate; see `quality-testing.md`.

Representative before/after display previews and raw gradient metrics are
generated by `scripts/visual_comparison.py` under the candidate evidence folder.
They are synthetic numeric fixtures, not an artistic photo-quality assessment.
