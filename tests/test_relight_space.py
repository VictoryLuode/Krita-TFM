"""Pure-Python checks for Relight Position-space / point-light placement math."""

from __future__ import annotations

import math


def fit_isotropic(min_xyz, max_xyz, target_radius):
    cx = tuple((a + b) * 0.5 for a, b in zip(min_xyz, max_xyz))
    half = max((b - a) * 0.5 for a, b in zip(min_xyz, max_xyz))
    half = max(half, 1e-6)
    scale = target_radius / half
    return cx, scale


def to_lighting(raw, origin, scale):
    return tuple((v - o) * scale for v, o in zip(raw, origin))


def point_light_from_surface(surface, above, normal=(0.0, 0.0, 1.0)):
    length = math.sqrt(sum(v * v for v in normal)) or 1.0
    n = tuple(v / length for v in normal)
    return tuple(s + n_i * above for s, n_i in zip(surface, n))


def shade_point(normal, position, light_pos, falloff, intensity=1.0):
    to = tuple(a - b for a, b in zip(light_pos, position))
    dist = math.sqrt(sum(v * v for v in to))
    if dist < 1e-8:
        direction = (0.0, 0.0, 1.0)
        atten = 1.0
    else:
        direction = tuple(v / dist for v in to)
        ratio = dist / max(falloff, 1e-6)
        atten = 1.0 / (1.0 + ratio * ratio)
    ndotl = max(0.0, sum(a * b for a, b in zip(normal, direction)))
    return ndotl * atten * intensity


def test_isotropic_fit_equalizes_axes():
    # Raw position AABB is elongated in X; after fit, unit box half-extents match.
    origin, scale = fit_isotropic((-10.0, -1.0, -1.0), (10.0, 1.0, 1.0), target_radius=100.0)
    assert origin == (0.0, 0.0, 0.0)
    corner = to_lighting((10.0, 1.0, 1.0), origin, scale)
    # Largest raw half-extent was 10 → maps to 100; Y half 1 → maps to 10.
    assert abs(corner[0] - 100.0) < 1e-9
    assert abs(corner[1] - 10.0) < 1e-9


def test_point_light_on_flat_plane_is_circular():
    # Flat ground z=0, light above origin. Equal radial samples should match.
    origin, scale = fit_isotropic((-1.0, -1.0, -0.01), (1.0, 1.0, 0.01), 100.0)
    surface = to_lighting((0.0, 0.0, 0.0), origin, scale)
    light = point_light_from_surface(surface, above=40.0)
    normal = (0.0, 0.0, 1.0)
    falloff = 120.0
    samples = []
    for angle in (0.0, 45.0, 90.0, 135.0, 180.0):
        rad = math.radians(angle)
        raw = (math.cos(rad) * 0.25, math.sin(rad) * 0.25, 0.0)
        pos = to_lighting(raw, origin, scale)
        samples.append(shade_point(normal, pos, light, falloff))
    assert max(samples) - min(samples) < 1e-9


def test_surface_sampled_light_matches_position_ridge():
    # Floor in raw Position has nearly constant Y; lights must sit on that ridge.
    origin, scale = fit_isotropic((-2.0, 5.0, -2.0), (2.0, 5.2, 2.0), 100.0)
    surface_center = to_lighting((0.0, 5.1, 0.0), origin, scale)
    good_light = point_light_from_surface(surface_center, 80.0)
    # Old screen-UV placement used image XY and ignored the Position ridge → far in Y.
    bad_light = (0.0, -120.0, 80.0)

    def dist(a, b):
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    assert dist(surface_center, good_light) == 80.0
    assert dist(surface_center, bad_light) > 100.0
    normal = (0.0, 0.0, 1.0)
    xs = [-1.0, -0.5, 0.0, 0.5, 1.0]
    good = [shade_point(normal, to_lighting((x, 5.1, 0.0), origin, scale), good_light, 150.0) for x in xs]
    bad = [shade_point(normal, to_lighting((x, 5.1, 0.0), origin, scale), bad_light, 150.0) for x in xs]
    assert good[2] == max(good)
    assert good[2] > bad[2]
