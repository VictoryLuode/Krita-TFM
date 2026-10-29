#pragma once

#include <algorithm>
#include <array>
#include <cmath>

namespace fxmanager::statistical {

constexpr int kBins = 256;
constexpr int kQuantiles = 17;
constexpr int kBands = 3;

// Normalized Lab16: L in [0,1], a/b centred at the Lab16 neutral code.
struct Pixel { double l, a, b, alpha; };
struct Moments {
    double weight = 0, meanA = 0, meanB = 0;
    double varA = 0, covAB = 0, varB = 0;
};
struct Profile {
    bool valid = false;
    std::array<double, kQuantiles> quantiles{};
    std::array<double, kQuantiles> quantilesA{};
    std::array<double, kQuantiles> quantilesB{};
    Moments global;
    std::array<Moments, kBands> bands{};
};

inline std::array<double, kBands> bandWeights(double percentile)
{
    const double t = std::clamp(percentile, 0.0, 1.0);
    // Smooth partition of unity; no hard shadow/midtone/highlight boundary.
    return {(1-t)*(1-t), 2*t*(1-t), t*t};
}

class Accumulator {
    struct Sums {
        double w = 0, a = 0, b = 0, aa = 0, ab = 0, bb = 0;
        void merge(const Sums &s, double factor = 1.0) {
            w += s.w*factor; a += s.a*factor; b += s.b*factor;
            aa += s.aa*factor; ab += s.ab*factor; bb += s.bb*factor;
        }
        Moments finish() const {
            if (w <= 0) return {};
            const double ma = a/w, mb = b/w;
            return {w, ma, mb, std::max(0.0, aa/w-ma*ma), ab/w-ma*mb,
                    std::max(0.0, bb/w-mb*mb)};
        }
    };
    std::array<Sums, kBins> m_bins{};
    std::array<double, kBins> m_aHistogram{};
    std::array<double, kBins> m_bHistogram{};
    static std::array<double, kQuantiles> quantilesFromHistogram(const std::array<double, kBins> &bins, double low, double high)
    {
        std::array<double, kQuantiles> result{};
        double total = 0;
        for (double weight : bins) total += weight;
        if (total <= 0) return result;
        for (int q = 0; q < kQuantiles; ++q) {
            const double target = (0.005 + 0.99*q/(kQuantiles-1))*total;
            double cumulative = 0;
            for (int i = 0; i < kBins; ++i) {
                const double next = cumulative + bins[i];
                if (next >= target || i == kBins-1) {
                    const double fraction = bins[i] > 0 ? (target-cumulative)/bins[i] : 0;
                    result[q] = low + (i+std::clamp(fraction, 0.0, 1.0))*(high-low)/kBins;
                    break;
                }
                cumulative = next;
            }
        }
        return result;
    }
 public:
    void add(Pixel p) {
        if (!std::isfinite(p.l) || !std::isfinite(p.a) || !std::isfinite(p.b)
            || !std::isfinite(p.alpha) || p.alpha <= 0) return;
        p.alpha = std::clamp(p.alpha, 0.0, 1.0);
        const int index = std::clamp(int(p.l*kBins), 0, kBins-1);
        const int aIndex = std::clamp(int((p.a+1.0)*0.5*kBins), 0, kBins-1);
        const int bIndex = std::clamp(int((p.b+1.0)*0.5*kBins), 0, kBins-1);
        m_aHistogram[aIndex] += p.alpha;
        m_bHistogram[bIndex] += p.alpha;
        auto &s = m_bins[index];
        s.w += p.alpha; s.a += p.alpha*p.a; s.b += p.alpha*p.b;
        s.aa += p.alpha*p.a*p.a; s.ab += p.alpha*p.a*p.b; s.bb += p.alpha*p.b*p.b;
    }
    Profile finish() const {
        Profile profile;
        Sums all;
        for (const auto &s : m_bins) all.merge(s);
        if (all.w <= 0) return profile;
        profile.valid = true; profile.global = all.finish();
        profile.quantilesA = quantilesFromHistogram(m_aHistogram, -1.0, 1.0);
        profile.quantilesB = quantilesFromHistogram(m_bHistogram, -1.0, 1.0);
        double cumulative = 0;
        std::array<Sums, kBands> bands{};
        int q = 0;
        for (int i = 0; i < kBins; ++i) {
            const auto &s = m_bins[i];
            if (s.w <= 0) continue;
            while (q < kQuantiles) {
                const double probability = 0.005 + 0.99*q/(kQuantiles-1);
                if (probability*all.w > cumulative+s.w) break;
                const double offset = std::clamp((probability*all.w-cumulative)/s.w, 0.0, 1.0);
                profile.quantiles[q++] = (i+offset)/kBins;
            }
            const auto weights = bandWeights((cumulative+0.5*s.w)/all.w);
            for (int j = 0; j < kBands; ++j) bands[j].merge(s, weights[j]);
            cumulative += s.w;
        }
        for (int j = 0; j < kBands; ++j) {
            profile.bands[j] = bands[j].w >= std::max(1.0, 0.01*all.w)
                ? bands[j].finish() : profile.global;
        }
        return profile;
    }
};

// Lab D50 -> XYZ D50 -> Bradford D65 -> linear sRGB. This is a
// conservative sRGB safety envelope; Krita still performs the final profile
// conversion to the document colour space.
inline bool inSrgbGamut(Pixel p)
{
    const double fy = (p.l*100+16)/116;
    const double fx = fy+p.a*255/500, fz = fy-p.b*255/200;
    const auto inv = [](double v) { return v > 6.0/29 ? v*v*v : (116*v-16)/903.2962962962963; };
    const double x = 0.96422*inv(fx), y = inv(fy), z = 0.82521*inv(fz);
    const double xd = 0.9555766*x-0.0230393*y+0.0631636*z;
    const double yd = -0.0282895*x+1.0099416*y+0.0210077*z;
    const double zd = 0.0122982*x-0.0204830*y+1.3299098*z;
    const double r = 3.2404542*xd-1.5371385*yd-0.4985314*zd;
    const double g = -0.9692660*xd+1.8760108*yd+0.0415560*zd;
    const double b = 0.0556434*xd-0.2040259*yd+1.0572252*zd;
    return r >= -1e-5 && g >= -1e-5 && b >= -1e-5 && r <= 1.00001 && g <= 1.00001 && b <= 1.00001;
}

inline Pixel compressSrgbGamut(Pixel p)
{
    if (inSrgbGamut(p)) return p;
    double low = 0, high = 1;
    for (int i = 0; i < 12; ++i) {
        const double scale = (low+high)*0.5;
        if (inSrgbGamut({p.l,p.a*scale,p.b*scale,p.alpha})) low = scale;
        else high = scale;
    }
    p.a *= low*0.98; p.b *= low*0.98;
    return p;
}

struct Matrix2 {
    double aa = 1, ab = 0, ba = 0, bb = 1;
};

struct TransferOptions {
    // Defaults preserve the enhanced-v2 appearance when no keys were saved.
    double toneAmount = 0.65;
    double bandAmount = 0.75;
    double correlation = 1.0;
    double maxGain = 2.0;
    double maxShift = 0.20;
    double varianceFloor = 0.0001;
    bool composite = false;
};

inline Matrix2 covarianceRoot(const Moments &m, bool inverse, double varianceFloor = 0.0001)
{
    // Regularise eigenvalues before whitening; nearly flat colours cannot
    // produce unbounded gain. Coordinates are normalized Lab, not RGB.
    const double theta = 0.5*std::atan2(2*m.covAB, m.varA-m.varB);
    const double c = std::cos(theta), s = std::sin(theta);
    const double radius = std::hypot(m.varA-m.varB, 2*m.covAB);
    const double e1 = std::clamp(0.5*(m.varA+m.varB+radius), varianceFloor, 0.04);
    const double e2 = std::clamp(0.5*(m.varA+m.varB-radius), varianceFloor, 0.04);
    const double r1 = inverse ? 1/std::sqrt(e1) : std::sqrt(e1);
    const double r2 = inverse ? 1/std::sqrt(e2) : std::sqrt(e2);
    return {c*c*r1+s*s*r2, c*s*(r1-r2), c*s*(r1-r2), s*s*r1+c*c*r2};
}

struct ChromaMap {
    Moments source, reference;
    Matrix2 matrix;
    ChromaMap() = default;
    ChromaMap(const Moments &src, const Moments &ref, const TransferOptions &options = {}) : source(src), reference(ref) {
        const auto r = covarianceRoot(ref, false, options.varianceFloor), s = covarianceRoot(src, true, options.varianceFloor);
        matrix = {r.aa*s.aa+r.ab*s.ba, r.aa*s.ab+r.ab*s.bb,
                  r.ba*s.aa+r.bb*s.ba, r.ba*s.ab+r.bb*s.bb};
        const auto independentGain = [&options](double srcVariance, double refVariance) {
            return std::sqrt(std::clamp(refVariance, options.varianceFloor, 0.04)
                           / std::clamp(srcVariance, options.varianceFloor, 0.04));
        };
        matrix.aa = options.correlation*matrix.aa+(1-options.correlation)*independentGain(src.varA, ref.varA);
        matrix.bb = options.correlation*matrix.bb+(1-options.correlation)*independentGain(src.varB, ref.varB);
        matrix.ab *= options.correlation; matrix.ba *= options.correlation;
        // Bound the largest singular value (gain), without altering its hue
        // direction. A colourless source still acquires the reference mean.
        const double trace = matrix.aa*matrix.aa+matrix.ab*matrix.ab+matrix.ba*matrix.ba+matrix.bb*matrix.bb;
        const double determinant = matrix.aa*matrix.bb-matrix.ab*matrix.ba;
        const double gain = std::sqrt(0.5*(trace+std::sqrt(std::max(0.0,trace*trace-4*determinant*determinant))));
        const double scale = gain > options.maxGain ? options.maxGain/gain : 1.0;
        matrix.aa *= scale; matrix.ab *= scale; matrix.ba *= scale; matrix.bb *= scale;
    }
    std::array<double,2> apply(double a, double b) const {
        return {reference.meanA+matrix.aa*(a-source.meanA)+matrix.ab*(b-source.meanB),
                reference.meanB+matrix.ba*(a-source.meanA)+matrix.bb*(b-source.meanB)};
    }
};

class Transfer {
    TransferOptions m_options;
    Profile m_source;
    Profile m_reference;
    std::array<ChromaMap,kBands> m_maps;
    ChromaMap m_global;
    std::array<double, kQuantiles> m_postMklA{};
    std::array<double, kQuantiles> m_postMklB{};
    std::array<double,1025> m_tone{};
    bool m_valid = false;

    static double quantileMap(double value, const std::array<double,kQuantiles> &from,
                              const std::array<double,kQuantiles> &to)
    {
        if (value <= from.front()) return to.front();
        if (value >= from.back()) return to.back();
        for (int i = 1; i < kQuantiles; ++i) {
            if (value <= from[i]) {
                const double t = (value-from[i-1])/std::max(1e-8,from[i]-from[i-1]);
                return to[i-1]+t*(to[i]-to[i-1]);
            }
        }
        return value;
    }
    std::array<double,2> compositeChroma(double a, double b) const
    {
        const double hmA = quantileMap(a, m_source.quantilesA, m_reference.quantilesA);
        const double hmB = quantileMap(b, m_source.quantilesB, m_reference.quantilesB);
        const auto centered = m_global.apply(hmA, hmB);
        const double finalA = quantileMap(centered[0], m_postMklA, m_reference.quantilesA);
        const double finalB = quantileMap(centered[1], m_postMklB, m_reference.quantilesB);
        return {finalA, finalB};
    }
    double percentile(double l) const {
        const auto &q = m_source.quantiles;
        if (l <= q.front()) return 0;
        if (l >= q.back()) return 1;
        for (int i = 1; i < kQuantiles; ++i) {
            if (l <= q[i]) {
                const double t = (l-q[i-1])/std::max(1e-8,q[i]-q[i-1]);
                return (i-1+t)/(kQuantiles-1);
            }
        }
        return 1;
    }
public:
    Transfer(const Profile &source, const Profile &reference, TransferOptions options = {})
        : m_options(options), m_source(source), m_reference(reference), m_valid(source.valid && reference.valid) {
        const auto bounded = [](double v, double low, double high, double fallback) {
            return std::isfinite(v) ? std::clamp(v, low, high) : fallback;
        };
        m_options.toneAmount = bounded(options.toneAmount, 0, 1, 0.65);
        m_options.bandAmount = bounded(options.bandAmount, 0, 1, 0.75);
        m_options.correlation = bounded(options.correlation, 0, 1, 1);
        m_options.maxGain = bounded(options.maxGain, 1, 8, 2);
        m_options.maxShift = bounded(options.maxShift, 0, 100.0/255, 0.20);
        m_options.varianceFloor = bounded(options.varianceFloor, 0.01/65025, 100.0/65025, 0.0001);
        m_global = ChromaMap(source.global, reference.global, m_options);
        for (int j = 0; j < kBands; ++j) m_maps[j] = ChromaMap(source.bands[j], reference.bands[j], m_options);
        if (m_options.composite) {
            for (int i = 0; i < kQuantiles; ++i) {
                const double hmA = quantileMap(source.quantilesA[i], source.quantilesA, reference.quantilesA);
                const double hmB = quantileMap(source.quantilesB[i], source.quantilesB, reference.quantilesB);
                const auto mkl = m_global.apply(hmA, hmB);
                m_postMklA[i] = mkl[0];
                m_postMklB[i] = mkl[1];
            }
            for (int i = 1; i < kQuantiles; ++i) {
                m_postMklA[i] = std::max(m_postMklA[i], m_postMklA[i-1]);
                m_postMklB[i] = std::max(m_postMklB[i], m_postMklB[i-1]);
            }
        }
        const auto &s = source.quantiles, &r = reference.quantiles;
        const bool flat = s.back()-s.front() < 0.01;
        for (int i = 0; i <= 1024; ++i) {
            const double l = i/1024.0;
            double mapped = l;
            if (flat) mapped = l+r[8]-s[8];
            else if (l <= s.front()) mapped = l+r.front()-s.front();
            else if (l >= s.back()) mapped = l+r.back()-s.back();
            else {
                for (int j = 1; j < kQuantiles; ++j) if (l <= s[j]) {
                    const double t = (l-s[j-1])/std::max(1e-8,s[j]-s[j-1]);
                    mapped = r[j-1]+t*(r[j]-r[j-1]); break;
                }
            }
            // Partial histogram transfer protects the source structure.
            m_tone[i] = (1-m_options.toneAmount)*l+m_options.toneAmount*mapped;
        }
        for (int pass = 0; pass < 3; ++pass) {
            const auto before = m_tone;
            for (int i = 1; i < 1024; ++i) m_tone[i] = (before[i-1]+2*before[i]+before[i+1])*0.25;
        }
        const double medianPosition = std::clamp(s[8],0.0,1.0)*1024;
        const double desiredMedian = s[8]+m_options.toneAmount*(r[8]-s[8]);
        for (int i = 1; i <= 1024; ++i)
            m_tone[i] = m_tone[i-1]+std::clamp(m_tone[i]-m_tone[i-1],0.5/1024,3.0/1024);
        const int mid = std::clamp(int(medianPosition),0,1023);
        const double shift = desiredMedian-(m_tone[mid]+(medianPosition-mid)*(m_tone[mid+1]-m_tone[mid]));
        for (double &v : m_tone) v += shift;
    }
    Pixel apply(Pixel p, double strength, double luminance, double colour, double fade) const {
        const double amount = std::clamp(strength,0.0,1.0)*(1-std::clamp(fade,0.0,1.0));
        if (!m_valid || amount <= 0 || p.alpha <= 0) return p;
        const double t = std::clamp(p.l,0.0,1.0)*1024;
        const int i = std::min(int(t),1023);
        const double mappedL = m_options.toneAmount == 0 ? p.l : m_tone[i]+(t-i)*(m_tone[i+1]-m_tone[i]);
        const auto target = m_options.composite ? compositeChroma(p.a, p.b) : [&] {
            auto value = m_global.apply(p.a,p.b);
            value[0] *= 1-m_options.bandAmount; value[1] *= 1-m_options.bandAmount;
            for (int j = 0; j < kBands; ++j) {
                const auto ab = m_maps[j].apply(p.a,p.b);
                const auto weights = bandWeights(percentile(p.l));
                value[0] += m_options.bandAmount*weights[j]*ab[0]; value[1] += m_options.bandAmount*weights[j]*ab[1];
            }
            return value;
        }();
        double da = target[0]-p.a, db = target[1]-p.b;
        const double distance = std::hypot(da,db);
        if (distance > m_options.maxShift) { da *= m_options.maxShift/distance; db *= m_options.maxShift/distance; }
        return {std::clamp(p.l+(mappedL-p.l)*amount*std::clamp(luminance,0.0,2.0),0.0,1.0),
                p.a+da*amount*std::clamp(colour,0.0,2.0),
                p.b+db*amount*std::clamp(colour,0.0,2.0),p.alpha};
    }
};

} // namespace fxmanager::statistical
