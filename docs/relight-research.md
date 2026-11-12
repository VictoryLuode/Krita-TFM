# Relight research (experimental)

Relight is **not** a shipped TFM filter. It stays behind research harnesses and
`--run-experimental` pytest collection so production installs do not register
or advertise it.

## What is covered

- Pure-Python Position-space / point-light math: `tests/test_relight_space.py`
- Optional OpenEXR position dump checks: `tests/test_relight_position_exr.py`
- Optional native math harness: `native/fx/tests/run_relight_math.py`
  (skips cleanly when `tests/test_relight.cpp` is absent)

## Hardening rules for this experimental path

1. Keep Relight out of `KisFilterRegistry` and the Filters catalog until a
   product decision lands a stable id, UI, and depth/colour contract.
2. Do not load Relight shaders or workers from the production `kritatfm.dll`
   startup path.
3. Experimental tests must opt in (`pytest --run-experimental`); default CI
   stays green without Relight assets.
4. Demo inputs (`test-kra/test-relight.kra`, Position EXR dumps) are local
   fixtures, not redistributable product content.
5. Any future productization needs: documented AOV layout, float GPU/CPU
   parity tests, Auto-backend policy, and a non-experimental catalog entry.

## Status

Research / harden-in-place. Prefer fixing math and harness skips over exposing
a half-finished Filter menu item.
