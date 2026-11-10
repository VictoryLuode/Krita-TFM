"""Offline Relight checks against demo Position.exr (OpenEXR X/Y/Z channels)."""

from __future__ import annotations

import math
from pathlib import Path

import Imath
import numpy as np
import OpenEXR
import pytest

ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / "test-kra" / "render"


def load_xyz(path: Path):
    f = OpenEXR.InputFile(str(path))
    header = f.header()
    channels = header["channels"]
    assert "X" in channels and "Y" in channels and "Z" in channels
    dw = header["dataWindow"]
    width = dw.max.x - dw.min.x + 1
    height = dw.max.y - dw.min.y + 1
    pt = Imath.PixelType(Imath.PixelType.FLOAT)

    def ch(name):
        return np.frombuffer(f.channel(name, pt), dtype=np.float32).reshape(height, width)

    return width, height, ch("X"), ch("Y"), ch("Z")


def fit_isotropic(xs, ys, zs, target_radius):
    mask = np.isfinite(xs) & np.isfinite(ys) & np.isfinite(zs)
    # Ignore empty background (all ~0 is rare; use finite + non-all-zero neighbourhood later)
    samples_x = xs[mask]
    samples_y = ys[mask]
    samples_z = zs[mask]
    # Drop pure zeros which are usually unwritten background in this demo.
    nonzero = ~((samples_x == 0) & (samples_y == 0) & (samples_z == 0))
    samples_x, samples_y, samples_z = samples_x[nonzero], samples_y[nonzero], samples_z[nonzero]
    min_xyz = np.array([samples_x.min(), samples_y.min(), samples_z.min()], dtype=np.float64)
    max_xyz = np.array([samples_x.max(), samples_y.max(), samples_z.max()], dtype=np.float64)
    origin = (min_xyz + max_xyz) * 0.5
    half = np.maximum((max_xyz - min_xyz) * 0.5, 1e-6)
    scale = target_radius / float(half.max())
    if half[2] <= half[0] and half[2] <= half[1]:
        up = np.array([0.0, 0.0, 1.0])
    elif half[1] <= half[0]:
        up = np.array([0.0, 1.0, 0.0])
    else:
        up = np.array([1.0, 0.0, 0.0])
    return origin, scale, up, min_xyz, max_xyz


def to_lighting(raw, origin, scale):
    return (raw - origin) * scale


def shade(normal, position, light_pos, falloff, intensity=1.0, ambient=0.15):
    to = light_pos - position
    dist = float(np.linalg.norm(to)) or 1e-8
    direction = to / dist
    ratio = dist / max(falloff, 1e-6)
    atten = 1.0 / (1.0 + ratio * ratio)
    ndotl = max(0.0, float(np.dot(normal, direction)))
    return ambient + ndotl * atten * intensity


@pytest.fixture(scope="module")
def position_maps():
    path = RENDER / "Position.exr"
    if not path.is_file():
        pytest.skip("demo Position.exr missing")
    return load_xyz(path)


def test_demo_position_up_axis_is_z(position_maps):
    width, height, xs, ys, zs = position_maps
    origin, scale, up, min_xyz, max_xyz = fit_isotropic(xs, ys, zs, max(width, height) * 0.5)
    half = (max_xyz - min_xyz) * 0.5
    assert half[2] < half[0] and half[2] < half[1]
    assert np.allclose(up, [0, 0, 1])
    assert scale > 0


def test_demo_point_light_ring_is_roundish(position_maps):
    width, height, xs, ys, zs = position_maps
    origin, scale, up, _min_xyz, _max_xyz = fit_isotropic(xs, ys, zs, max(width, height) * 0.5)

    # Prefer a ground pixel near lower-centre (demo framing).
    cx, cy = width // 2, int(height * 0.68)
    raw = np.array([xs[cy, cx], ys[cy, cx], zs[cy, cx]], dtype=np.float64)
    if np.allclose(raw, 0):
        # Search nearby for a non-zero Position sample.
        found = False
        for y in range(cy - 40, cy + 41, 4):
            for x in range(cx - 40, cx + 41, 4):
                if not (0 <= x < width and 0 <= y < height):
                    continue
                cand = np.array([xs[y, x], ys[y, x], zs[y, x]], dtype=np.float64)
                if not np.allclose(cand, 0):
                    cx, cy, raw = x, y, cand
                    found = True
                    break
            if found:
                break
    assert not np.allclose(raw, 0), "no Position sample near click"

    surface = to_lighting(raw, origin, scale)
    light = surface + up * 80.0
    # Flat-ish shading normal along up for ground falloff shape check.
    normal = up.copy()

    spreads = []
    means = []
    for radius in (12, 36, 72, 120):
        vals = []
        for angle_deg in range(0, 360, 15):
            ang = math.radians(angle_deg)
            x = int(cx + math.cos(ang) * radius)
            y = int(cy + math.sin(ang) * radius)
            if not (0 <= x < width and 0 <= y < height):
                continue
            raw_p = np.array([xs[y, x], ys[y, x], zs[y, x]], dtype=np.float64)
            if np.allclose(raw_p, 0):
                continue
            pos = to_lighting(raw_p, origin, scale)
            vals.append(shade(normal, pos, light, falloff=260.0, intensity=1.6))
        assert len(vals) >= 8, f"too few ring samples at r={radius}"
        spreads.append(max(vals) - min(vals))
        means.append(sum(vals) / len(vals))

    # A true point light should not vary wildly around a ring on a flat ground.
    assert spreads[0] < 0.35
    assert spreads[1] < 0.45
    # And mean intensity should fall off with radius.
    assert means[0] > means[2]
    assert means[1] > means[3]


def test_surface_sampled_light_is_near_the_clicked_surface(position_maps):
    width, height, xs, ys, zs = position_maps
    origin, scale, up, _min_xyz, _max_xyz = fit_isotropic(xs, ys, zs, max(width, height) * 0.5)
    cx, cy = width // 2, int(height * 0.68)
    raw = np.array([xs[cy, cx], ys[cy, cx], zs[cy, cx]], dtype=np.float64)
    if np.allclose(raw, 0):
        pytest.skip("centre sample empty")
    surface = to_lighting(raw, origin, scale)
    good = surface + up * 80.0
    bad = np.array([(cx / (width - 1) - 0.5) * (width - 1), (cy / (height - 1) - 0.5) * (height - 1), 80.0])
    assert float(np.linalg.norm(good - surface)) == pytest.approx(80.0)
    assert float(np.linalg.norm(bad - surface)) > 200.0
    # Surface-sampled light actually illuminates the clicked neighbourhood.
    near = shade(up, surface, good, falloff=260.0, intensity=1.6)
    far = shade(up, surface, bad, falloff=260.0, intensity=1.6)
    assert near > far + 0.2
