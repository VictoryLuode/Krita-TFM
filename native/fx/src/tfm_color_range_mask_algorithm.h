#pragma once

/**
 * Pure color-range mask maths, independent from Krita's UI and paint device.
 *
 * The host filter only feeds ARGB32 pixels in and takes the resulting alpha
 * factor out, which keeps this header testable by a plain Qt program.
 */

#include "pointwise_math.h"

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace colormask {

struct Settings {
    enum class Channel {
        Gray = 0,
        Red = 1,
        Green = 2,
        Blue = 3,
        Hue = 4,
        Saturation = 5,
        Lightness = 6, // OKLab L
        Chroma = 7,    // OKLab C (colorfulness / ΔE-from-gray)
        OkHue = 8,     // OKLab hue
        DeltaE = 9,    // OKLab ΔE76 from mid-gray reference
    };
    Channel channel = Channel::Gray;
    double rangeMin = 0.0;
    double rangeMax = 1.0;
    double softness = 0.05;
    bool invert = false;
    bool preserveRgb = true;
};

inline double clamp01(double v)
{
    return std::clamp(v, 0.0, 1.0);
}

inline double smoothstep(double edge0, double edge1, double x)
{
    if (edge1 <= edge0) return x < edge0 ? 0.0 : 1.0;
    const double t = clamp01((x - edge0) / (edge1 - edge0));
    return t * t * (3.0 - 2.0 * t);
}

struct Hsv {
    double h = 0.0; // 0..1
    double s = 0.0;
    double v = 0.0;
};

inline Hsv rgbToHsv(double r, double g, double b)
{
    const double maxc = std::max({r, g, b});
    const double minc = std::min({r, g, b});
    const double delta = maxc - minc;

    Hsv out;
    out.v = maxc;
    out.s = maxc <= 0.0 ? 0.0 : delta / maxc;
    if (delta <= 0.0) {
        out.h = 0.0;
        return out;
    }
    if (maxc == r) {
        out.h = std::fmod((g - b) / delta, 6.0);
    } else if (maxc == g) {
        out.h = (b - r) / delta + 2.0;
    } else {
        out.h = (r - g) / delta + 4.0;
    }
    out.h /= 6.0;
    if (out.h < 0.0) out.h += 1.0;
    return out;
}

/// Shortest distance along the hue circle, so 0.99 and 0.01 are neighbours.
inline double hueDistance(double a, double b)
{
    const double d = std::fabs(a - b);
    return std::min(d, 1.0 - d);
}

inline double rangeDistance(double value, double lo, double hi)
{
    if (lo > hi) std::swap(lo, hi);
    if (value < lo) return lo - value;
    if (value > hi) return value - hi;
    return 0.0;
}

/// Inclusive directed interval on the hue circle; min > max crosses red.
/// Keep 0..1 as a full circle (rather than normalizing both ends to zero).
inline double hueRangeDistance(double hue, double lo, double hi)
{
    const bool inside = lo <= hi ? hue >= lo && hue <= hi
                                 : hue >= lo || hue <= hi;
    if (inside) return 0.0;
    return std::min(hueDistance(hue, lo), hueDistance(hue, hi));
}

inline tfm::pointwise::OkLab pixelOkLab(double r, double g, double b)
{
    return tfm::pointwise::linearToOkLab(tfm::pointwise::decodeRgb({r, g, b}));
}

inline double selectedChannel(double r, double g, double b, Settings::Channel channel)
{
    switch (channel) {
    case Settings::Channel::Red: return r;
    case Settings::Channel::Green: return g;
    case Settings::Channel::Blue: return b;
    case Settings::Channel::Hue: return rgbToHsv(r, g, b).h;
    case Settings::Channel::Saturation: return rgbToHsv(r, g, b).s;
    case Settings::Channel::Lightness: return clamp01(pixelOkLab(r, g, b).L);
    case Settings::Channel::Chroma: {
        // Normalize typical OKLab chroma into ~0..1 for the range UI.
        return clamp01(tfm::pointwise::okChroma(pixelOkLab(r, g, b)) / 0.4);
    }
    case Settings::Channel::OkHue: return tfm::pointwise::okHue(pixelOkLab(r, g, b));
    case Settings::Channel::DeltaE: {
        const auto lab = pixelOkLab(r, g, b);
        const tfm::pointwise::OkLab gray{0.5, 0.0, 0.0};
        return clamp01(tfm::pointwise::okDeltaE(lab, gray) / 0.75);
    }
    case Settings::Channel::Gray: return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    }
    return 0.0;
}

inline double alphaFactor(double r, double g, double b, const Settings &s)
{
    if (s.channel == Settings::Channel::Hue || s.channel == Settings::Channel::OkHue) {
        const double hue = s.channel == Settings::Channel::Hue
            ? rgbToHsv(r, g, b).h
            : tfm::pointwise::okHue(pixelOkLab(r, g, b));
        const double sat = s.channel == Settings::Channel::Hue
            ? rgbToHsv(r, g, b).s
            : tfm::pointwise::okChroma(pixelOkLab(r, g, b));
        const double distance = hueRangeDistance(hue, s.rangeMin, s.rangeMax);
        const double inside = sat > 1e-6
            ? 1.0 - smoothstep(0.0, std::max(1e-6, s.softness), distance) : 0.0;
        return clamp01(s.invert ? 1.0 - inside : inside);
    }
    const double value = selectedChannel(r, g, b, s.channel);
    const double lo = std::min(s.rangeMin, s.rangeMax);
    const double hi = std::max(s.rangeMin, s.rangeMax);
    const double edge = std::max(1e-6, s.softness);
    const double distance = rangeDistance(value, lo, hi);
    const double inside = 1.0 - smoothstep(0.0, edge, distance);
    const double factor = s.invert ? 1.0 - inside : inside;
    return clamp01(factor);
}

/// Straight ARGB32: retain RGB bytes and multiply, never replace, source alpha.
inline std::uint32_t maskArgb32(std::uint32_t pixel, const Settings &s)
{
    const double factor = alphaFactor(((pixel >> 16) & 255u) / 255.0,
                                     ((pixel >> 8) & 255u) / 255.0,
                                     (pixel & 255u) / 255.0, s);
    const int alpha = std::clamp(int(std::lround((pixel >> 24) * factor)), 0, 255);
    return (pixel & 0x00ffffffu) | (std::uint32_t(alpha) << 24);
}

} // namespace colormask
