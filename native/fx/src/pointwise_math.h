#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

// Production colour math shared by the U8/float paths and native regression
// probes. Inputs use encoded sRGB; storage conversion is deliberately separate.
namespace tfm::pointwise {
struct Rgb { double r=0, g=0, b=0; };
constexpr double kReferenceKelvin=6500.0;

inline double smoothRange(double e0, double e1, double x) {
    if (e1<=e0) return x<e0 ? 0.0 : 1.0;
    const double t=std::clamp((x-e0)/(e1-e0),0.0,1.0);
    return t*t*(3.0-2.0*t);
}
// Sign-symmetric extended sRGB transfer retains negative and HDR values.
inline float encode(float linear) {
    const double v=std::abs(double(linear));
    return float(std::copysign(v<=0.0031308 ? 12.92*v : 1.055*std::pow(v,1.0/2.4)-0.055,linear));
}
inline float decode(float encoded) {
    const double v=std::abs(double(encoded));
    return float(std::copysign(v<=0.04045 ? v/12.92 : std::pow((v+0.055)/1.055,2.4),encoded));
}
inline Rgb decodeRgb(Rgb c) { return {decode(float(c.r)), decode(float(c.g)), decode(float(c.b))}; }
inline Rgb encodeRgb(Rgb c) { return {encode(float(c.r)), encode(float(c.g)), encode(float(c.b))}; }

// OKLab (Björn Ottosson). Linear sRGB in, OKLab out.
struct OkLab { double L=0, a=0, b=0; };
inline OkLab linearToOkLab(Rgb c) {
    const double l=0.4122214708*c.r+0.5363325363*c.g+0.0514459929*c.b;
    const double m=0.2119034982*c.r+0.6806995451*c.g+0.1073969566*c.b;
    const double s=0.0883024619*c.r+0.2817188376*c.g+0.6299787005*c.b;
    const double l_=std::cbrt(l), m_=std::cbrt(m), s_=std::cbrt(s);
    return {
        0.2104542553*l_+0.7936177850*m_-0.0040720468*s_,
        1.9779984951*l_-2.4285922050*m_+0.4505937099*s_,
        0.0259040371*l_+0.7827717662*m_-0.8086757660*s_
    };
}
inline Rgb okLabToLinear(OkLab lab) {
    const double l_=lab.L+0.3963377774*lab.a+0.2158037573*lab.b;
    const double m_=lab.L-0.1055613458*lab.a-0.0638541728*lab.b;
    const double s_=lab.L-0.0894841775*lab.a-1.2914855480*lab.b;
    const double l=l_*l_*l_, m=m_*m_*m_, s=s_*s_*s_;
    return {
        +4.0767416621*l-3.3077115913*m+0.2309699292*s,
        -1.2684380046*l+2.6097574011*m-0.3413193965*s,
        -0.0041960863*l-0.7034186147*m+1.7076147010*s
    };
}
inline double okChroma(OkLab lab) { return std::hypot(lab.a, lab.b); }
inline double okHue(OkLab lab) {
    const double h=std::atan2(lab.b, lab.a) / (2.0 * 3.14159265358979323846);
    return h < 0.0 ? h + 1.0 : h;
}
inline double okDeltaE(OkLab a, OkLab b) {
    return std::sqrt((a.L-b.L)*(a.L-b.L)+(a.a-b.a)*(a.a-b.a)+(a.b-b.b)*(a.b-b.b));
}

struct VibranceParams { double vibrance, saturation, protect, blend; };
inline Rgb vibrance(Rgb c,const VibranceParams &p,bool clip) {
    // Work in OKLab on a linearised view of the encoded input so chroma moves
    // more perceptually than the old RGB-luma pivot.
    const Rgb linear = decodeRgb(c);
    OkLab lab = linearToOkLab(linear);
    const double chroma = okChroma(lab);
    double amount = p.vibrance * (1.0 - std::min(chroma / 0.4, 1.0));
    if (p.protect > 0) amount *= 1.0 + (0.0 - 1.0) * smoothRange(0.70, 1.0, lab.L) * p.protect;
    const double gain = std::max(0.0, 1.0 + amount + p.saturation);
    lab.a *= gain;
    lab.b *= gain;
    Rgb outLin = okLabToLinear(lab);
    Rgb out = encodeRgb(outLin);
    auto mix=[&](double a,double b) {
        const double v=a+(b-a)*p.blend;
        return clip ? std::clamp(v,0.0,1.0) : v;
    };
    return {mix(c.r,out.r),mix(c.g,out.g),mix(c.b,out.b)};
}

inline Rgb kelvin(double value) {
    const double t=std::clamp(value,1000.0,40000.0)/100.0;
    double r,g,b;
    if(t<=66.0) {
        r=255.0; g=99.4708025861*std::log(t)-161.1195681661;
        b=t<=19.0 ? 0.0 : 138.5177312231*std::log(t-10.0)-305.0447927307;
    } else {
        r=329.698727446*std::pow(t-60.0,-0.1332047592);
        g=288.1221695283*std::pow(t-60.0,-0.0755148492); b=255.0;
    }
    return {std::clamp(r/255.0,0.0,1.0),std::clamp(g/255.0,0.0,1.0),std::clamp(b/255.0,0.0,1.0)};
}
inline Rgb temperatureGains(double temperature,double tint) {
    // Ratios of black-body colours, with green/magenta tint on the middle channel.
    // Applied in linear light by temperature() below (von Kries-style).
    const auto target=kelvin(temperature), reference=kelvin(kReferenceKelvin);
    return {target.r/std::max(1e-4,reference.r),
        target.g/std::max(1e-4,reference.g)*(1.0+(tint/100.0)*0.2),
        target.b/std::max(1e-4,reference.b)};
}
inline Rgb temperature(Rgb c,Rgb gain,double blend,bool preserve,bool clip) {
    const Rgb lin = decodeRgb(c);
    Rgb out{lin.r*gain.r, lin.g*gain.g, lin.b*gain.b};
    if(preserve) {
        const double before=0.2126*lin.r+0.7152*lin.g+0.0722*lin.b;
        const double after=0.2126*out.r+0.7152*out.g+0.0722*out.b;
        if(after>1e-5) { const double scale=before/after; out.r*=scale; out.g*=scale; out.b*=scale; }
    }
    out = encodeRgb(out);
    auto mix=[&](double a,double b) { const double v=a+(b-a)*blend; return clip ? std::clamp(v,0.0,1.0) : v; };
    return {mix(c.r,out.r),mix(c.g,out.g),mix(c.b,out.b)};
}

// Value-noise grain: bilinear lattice interpolation + film-like tone response.
inline double hashNoise(int x, int y, int seed, int channel) {
    const std::uint32_t ux = std::uint32_t(x);
    const std::uint32_t uy = std::uint32_t(y);
    const std::uint32_t us = std::uint32_t(seed);
    const std::uint32_t uc = std::uint32_t(channel);
    std::uint32_t h = ux * 374761393u + uy * 668265263u + us * 2246822519u + uc * 3266489917u;
    h = (h ^ (h >> 13)) * 1274126177u;
    h ^= h >> 16;
    return (double(h % 10000u) / 5000.0) - 1.0;
}
inline double valueNoise(double x, double y, int seed, int channel) {
    const int x0 = int(std::floor(x)), y0 = int(std::floor(y));
    const double fx = x - x0, fy = y - y0;
    const double sx = fx * fx * (3.0 - 2.0 * fx);
    const double sy = fy * fy * (3.0 - 2.0 * fy);
    const double n00 = hashNoise(x0, y0, seed, channel);
    const double n10 = hashNoise(x0 + 1, y0, seed, channel);
    const double n01 = hashNoise(x0, y0 + 1, seed, channel);
    const double n11 = hashNoise(x0 + 1, y0 + 1, seed, channel);
    const double nx0 = n00 + (n10 - n00) * sx;
    const double nx1 = n01 + (n11 - n01) * sx;
    return nx0 + (nx1 - nx0) * sy;
}
// More grain in shadows/midtones, less in specular highlights.
inline double grainResponse(double encodedLuma) {
    const double shadows = 1.0 - smoothRange(0.0, 0.18, encodedLuma) * 0.15;
    const double highlights = 1.0 - smoothRange(0.55, 0.95, encodedLuma) * 0.75;
    return std::clamp(shadows * highlights, 0.15, 1.15);
}
inline double filmGrainSample(double gx, double gy, double size, int seed, int channel, bool monochrome) {
    const double cell = std::max(0.5, size);
    const double nx = gx / cell, ny = gy / cell;
    if (monochrome) return valueNoise(nx, ny, seed, 0);
    // Soft mono carrier plus a little chroma chatter.
    return valueNoise(nx, ny, seed, 0) * 0.72 + valueNoise(nx, ny, seed, channel) * 0.28;
}

} // namespace tfm::pointwise
