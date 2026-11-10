#pragma once

#include <algorithm>
#include <cmath>

// Production colour math shared by the U8/float paths and native regression
// probes. Inputs use encoded sRGB; storage conversion is deliberately separate.
namespace fxmanager::pointwise {
struct Rgb { double r=0, g=0, b=0; };
constexpr double kReferenceKelvin=6500.0;

inline double smoothRange(double e0, double e1, double x) {
    if (e1<=e0) return x<e0 ? 0.0 : 1.0;
    const double t=std::clamp((x-e0)/(e1-e0),0.0,1.0);
    return t*t*(3.0-2.0*t);
}
inline double hueDistance(double a,double b) {
    const double d=std::abs(a-b);
    return std::min(d,1.0-d);
}
inline double hueOf(double r,double g,double b) {
    const double mx=std::max(r,std::max(g,b)), mn=std::min(r,std::min(g,b));
    const double d=mx-mn;
    if(d<=0) return 0;
    double h=mx==r ? std::fmod((g-b)/d,6.0) : mx==g ? (b-r)/d+2.0 : (r-g)/d+4.0;
    h/=6.0;
    return h<0 ? h+1.0 : h;
}
inline double skinWeight(double hue,double chroma) {
    return (1.0-smoothRange(0.05,0.18,hueDistance(hue,0.07))) * smoothRange(0.04,0.20,chroma);
}
struct VibranceParams { double vibrance, saturation, skin, protect, blend; };
inline Rgb vibrance(Rgb c,const VibranceParams &p,bool clip) {
    const double mx=std::max(c.r,std::max(c.g,c.b)), mn=std::min(c.r,std::min(c.g,c.b));
    const double chroma=mx-mn;
    const double lum=0.2126*c.r+0.7152*c.g+0.0722*c.b;
    // The adaptive weight is bounded for HDR, but colour data is not clipped.
    double amount=p.vibrance*(1.0-std::min(chroma,1.0));
    if(p.skin>0 && chroma>0) amount*=1.0+(0.15-1.0)*skinWeight(hueOf(c.r,c.g,c.b),chroma)*p.skin;
    if(p.protect>0) amount*=1.0+(0.0-1.0)*smoothRange(0.70,1.0,lum)*p.protect;
    const double gain=std::max(0.0,1.0+amount+p.saturation);
    auto channel=[&](double value) {
        const double out=lum+(value-lum)*gain;
        const double mixed=value+(out-value)*p.blend;
        return clip ? std::clamp(mixed,0.0,1.0) : mixed;
    };
    return {channel(c.r),channel(c.g),channel(c.b)};
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
    const auto target=kelvin(temperature), reference=kelvin(kReferenceKelvin);
    return {target.r/std::max(1e-4,reference.r),
        target.g/std::max(1e-4,reference.g)*(1.0+(tint/100.0)*0.2),
        target.b/std::max(1e-4,reference.b)};
}
inline Rgb temperature(Rgb c,Rgb gain,double blend,bool preserve,bool clip) {
    Rgb out{c.r*gain.r,c.g*gain.g,c.b*gain.b};
    if(preserve) {
        const double before=0.2126*c.r+0.7152*c.g+0.0722*c.b;
        const double after=0.2126*out.r+0.7152*out.g+0.0722*out.b;
        if(after>1e-5) { const double scale=before/after; out.r*=scale; out.g*=scale; out.b*=scale; }
    }
    auto mix=[&](double a,double b) { const double v=a+(b-a)*blend; return clip ? std::clamp(v,0.0,1.0) : v; };
    return {mix(c.r,out.r),mix(c.g,out.g),mix(c.b,out.b)};
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
} // namespace fxmanager::pointwise
