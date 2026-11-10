#pragma once

#include <QByteArray>
#include <QColor>
#include <QDataStream>
#include <QImage>
#include <QIODevice>
#include <algorithm>
#include <array>
#include <cmath>
#include <vector>

namespace tfm::guided {

struct Pair {
    bool valid = false;
    QColor source;
    QColor target;
};

inline double srgbToLinear(double x)
{
    return x <= 0.04045 ? x / 12.92 : std::pow((x + 0.055) / 1.055, 2.4);
}

inline double linearToSrgb(double x)
{
    x = std::clamp(x, 0.0, 1.0);
    return x <= 0.0031308 ? x * 12.92 : 1.055 * std::pow(x, 1.0 / 2.4) - 0.055;
}

struct Lab {
    double l = 0;
    double a = 0;
    double b = 0;
};

inline Lab rgbToOklab(const QColor &color)
{
    const double r = srgbToLinear(color.redF());
    const double g = srgbToLinear(color.greenF());
    const double b = srgbToLinear(color.blueF());
    const double l = std::cbrt(0.4122214708*r + 0.5363325363*g + 0.0514459929*b);
    const double m = std::cbrt(0.2119034982*r + 0.6806995451*g + 0.1073969566*b);
    const double s = std::cbrt(0.0883024619*r + 0.2817188376*g + 0.6299787005*b);
    return {0.2104542553*l + 0.7936177850*m - 0.0040720468*s,
            1.9779984951*l - 2.4285922050*m + 0.4505937099*s,
            0.0259040371*l + 0.7827717662*m - 0.8086757660*s};
}

inline QColor oklabToRgb(const Lab &value)
{
    const double l = std::pow(std::max(0.0, value.l + 0.3963377774*value.a + 0.2158037573*value.b), 3);
    const double m = std::pow(std::max(0.0, value.l - 0.1055613458*value.a - 0.0638541728*value.b), 3);
    const double s = std::pow(std::max(0.0, value.l - 0.0894841775*value.a - 1.2914855480*value.b), 3);
    const double r = linearToSrgb(+4.0767416621*l - 3.3077115913*m + 0.2309699292*s);
    const double g = linearToSrgb(-1.2684380046*l + 2.6097574011*m - 0.3413193965*s);
    const double b = linearToSrgb(-0.0041960863*l - 0.7034186147*m + 1.7076147010*s);
    return QColor::fromRgbF(r, g, b);
}

struct Lut {
    static constexpr int Size = 33;
    std::vector<float> values = std::vector<float>(Size * Size * Size * 3);
    bool valid = false;

    static int index(int r, int g, int b, int channel)
    {
        return (((r * Size) + g) * Size + b) * 3 + channel;
    }

    bool isIdentity() const
    {
        if(!valid) return false;
        for(int r=0;r<Size;++r) for(int g=0;g<Size;++g) for(int b=0;b<Size;++b) {
            const int channels[]={r,g,b};
            for(int c=0;c<3;++c)
                if(values[index(r,g,b,c)]!=float(channels[c])/float(Size-1)) return false;
        }
        return true;
    }

    std::array<double,3> sampleFloat(std::array<double,3> color, bool retainExtended = true) const
    {
        if (!valid) return color;
        const double r = std::clamp(color[0], 0.0, 1.0) * (Size - 1);
        const double g = std::clamp(color[1], 0.0, 1.0) * (Size - 1);
        const double b = std::clamp(color[2], 0.0, 1.0) * (Size - 1);
        const int r0 = std::min(int(r), Size - 2), g0 = std::min(int(g), Size - 2), b0 = std::min(int(b), Size - 2);
        const double fr = r - r0, fg = g - g0, fb = b - b0;
        const auto at = [&](int ri, int gi, int bi, int channel) {
            return double(values[index(ri, gi, bi, channel)]);
        };
        std::array<double, 3> out{};
        std::array<std::array<int, 3>, 4> corners{};
        std::array<double, 4> weights{};
        if (fr >= fg) {
            if (fg >= fb) {
                corners = {{{r0,g0,b0},{r0+1,g0,b0},{r0+1,g0+1,b0},{r0+1,g0+1,b0+1}}};
                weights = {1-fr, fr-fg, fg-fb, fb};
            } else if (fr >= fb) {
                corners = {{{r0,g0,b0},{r0+1,g0,b0},{r0+1,g0,b0+1},{r0+1,g0+1,b0+1}}};
                weights = {1-fr, fr-fb, fb-fg, fg};
            } else {
                corners = {{{r0,g0,b0},{r0,g0,b0+1},{r0+1,g0,b0+1},{r0+1,g0+1,b0+1}}};
                weights = {1-fb, fb-fr, fr-fg, fg};
            }
        } else if (fr >= fb) {
            corners = {{{r0,g0,b0},{r0,g0+1,b0},{r0+1,g0+1,b0},{r0+1,g0+1,b0+1}}};
            weights = {1-fg, fg-fr, fr-fb, fb};
        } else if (fg >= fb) {
            corners = {{{r0,g0,b0},{r0,g0+1,b0},{r0,g0+1,b0+1},{r0+1,g0+1,b0+1}}};
            weights = {1-fg, fg-fb, fb-fr, fr};
        } else {
            corners = {{{r0,g0,b0},{r0,g0,b0+1},{r0,g0+1,b0+1},{r0+1,g0+1,b0+1}}};
            weights = {1-fb, fb-fg, fg-fr, fr};
        }
        for (int i = 0; i < 4; ++i)
            for (int channel = 0; channel < 3; ++channel)
                out[channel] += weights[i] * at(corners[i][0], corners[i][1], corners[i][2], channel);
        for(int c=0;c<3;++c) {
            out[c]=std::clamp(out[c],0.0,1.0);
            // LUTs only define [0,1]; retain out-of-domain source residuals.
            if(retainExtended) out[c]+=color[c]-std::clamp(color[c],0.0,1.0);
        }
        return out;
    }
    QColor sample(const QColor &color) const
    {
        if(!valid) return color;
        const auto out=sampleFloat({double(color.redF()),double(color.greenF()),double(color.blueF())},false);
        return QColor::fromRgbF(out[0],out[1],out[2],color.alphaF());
    }

};

struct LightnessStats {
    double mean = 0.5;
    double stdev = 0.2;
    bool valid = false;
};

inline LightnessStats imageLightnessStats(const QImage &image)
{
    LightnessStats stats;
    if (image.isNull()) return stats;
    double sum = 0.0;
    double sumSq = 0.0;
    int count = 0;
    for (int y = 0; y < image.height(); ++y) {
        for (int x = 0; x < image.width(); ++x) {
            const QColor color = image.pixelColor(x, y);
            if (color.alpha() <= 0) continue;
            const double lightness = rgbToOklab(color).l;
            sum += lightness;
            sumSq += lightness * lightness;
            ++count;
        }
    }
    if (count < 16) return stats;
    stats.mean = sum / double(count);
    stats.stdev = std::sqrt(std::max(0.0, sumSq / double(count) - stats.mean * stats.mean));
    stats.stdev = std::max(stats.stdev, 0.02);
    stats.valid = true;
    return stats;
}

inline double alignLightness(double lightness, const LightnessStats &source, const LightnessStats &reference)
{
    if (!source.valid || !reference.valid) return lightness;
    return (lightness - source.mean) * (reference.stdev / source.stdev) + reference.mean;
}

// Grade from the two preview images, not from four swatches.
// 1. Map source OKLab L through histogram matching so a high-key photo lands
//    in the reference's actual lightness distribution (mean/std leaves it high-key).
// 2. At that lightness, the reference's chroma-weighted a/b is the main tone.
// 3. Colours that sit away from the source's own main tone pick a reference
//    accent of the same lightness and the same direction away from its main tone.
//    A one-colour reference has no accent, so the result stays the main tone.
struct LookTransfer {
    static constexpr int Bins = 48;
    static constexpr int HueBins = 8;
    bool valid = false;
    double align = 1.0;
    double strength = 1.0;
    double chromaAmount = 1.0;
    double luminance = 0.0;
    double neutral = 0.0;
    double shadowColor = 1.0;
    double highlightWarmth = 1.0;
    double keepLocal = 1.0;
    double matchLocal = 0.0;
    double srcCdf[Bins]{};
    double refCdf[Bins]{};
    double chromaA[Bins]{};
    double chromaB[Bins]{};
    double srcMeanA[Bins]{};
    double srcMeanB[Bins]{};
    double accentA[HueBins][Bins]{};
    double accentB[HueBins][Bins]{};
    double accentW[HueBins][Bins]{};

    static LookTransfer fromImages(const QImage &sourceImage, const QImage &referenceImage,
                                   double alignBrightness, double luminanceValue, double chromaValue,
                                   double strengthValue, double neutralProtection, double smoothness,
                                   double shadowColorValue, double highlightWarmthValue,
                                   double keepLocalValue = 1.0, double matchLocalValue = 0.0)
    {
        LookTransfer look;
        look.align = std::clamp(alignBrightness, 0.0, 1.0);
        look.strength = std::clamp(strengthValue, 0.0, 1.0);
        look.chromaAmount = std::clamp(chromaValue, 0.0, 2.0);
        look.luminance = std::clamp(luminanceValue, 0.0, 2.0);
        look.neutral = std::clamp(neutralProtection, 0.0, 1.0);
        look.shadowColor = std::clamp(shadowColorValue, 0.0, 1.0);
        look.highlightWarmth = std::clamp(highlightWarmthValue, 0.0, 2.0);
        look.keepLocal = std::clamp(keepLocalValue, 0.0, 1.0);
        look.matchLocal = std::clamp(matchLocalValue, 0.0, 1.0);
        if (sourceImage.isNull() || referenceImage.isNull()) return look;

        double srcHist[Bins]{};
        double refHist[Bins]{};
        double srcSumA[Bins]{};
        double srcSumB[Bins]{};
        double srcCount[Bins]{};
        const auto accumulate = [](const QImage &image, double *hist, double *sumA, double *sumB, double *weight, bool weightedChroma, double *plainA, double *plainB, double *plainW) {
            if (image.isNull() || image.width() < 2 || image.height() < 2) return;
            const int stride = std::max(1, std::max(image.width(), image.height()) / 320);
            for (int y = 0; y < image.height(); y += stride) {
                for (int x = 0; x < image.width(); x += stride) {
                    const QColor color = image.pixelColor(x, y);
                    if (color.alpha() <= 0) continue;
                    const Lab lab = rgbToOklab(color);
                    const int bin = std::clamp(int(std::clamp(lab.l, 0.0, 1.0) * (Bins - 1) + 0.5), 0, Bins - 1);
                    hist[bin] += 1.0;
                    if (plainA) {
                        plainA[bin] += lab.a;
                        plainB[bin] += lab.b;
                        plainW[bin] += 1.0;
                    }
                    if (!weightedChroma) continue;
                    const double chroma = std::hypot(lab.a, lab.b);
                    // Deepest pixels keep their own colour. Chroma weighting only
                    // takes over once lightness leaves the shadow tail, so a black
                    // crevice is not replaced by a brighter red beside it.
                    const double tone = std::clamp(lab.l / 0.22, 0.0, 1.0);
                    const double vivid = 0.015 + chroma * chroma;
                    const double w = (1.0 - tone) + tone * vivid;
                    sumA[bin] += lab.a * w;
                    sumB[bin] += lab.b * w;
                    weight[bin] += w;
                }
            }
        };
        accumulate(sourceImage, srcHist, nullptr, nullptr, nullptr, false, srcSumA, srcSumB, srcCount);
        accumulate(referenceImage, refHist, nullptr, nullptr, nullptr, false, nullptr, nullptr, nullptr);

        const auto blur = [](double *values) {
            double copy[Bins];
            for (int i = 0; i < Bins; ++i) copy[i] = values[i];
            for (int i = 0; i < Bins; ++i) {
                const double left = copy[std::max(0, i - 1)];
                const double right = copy[std::min(Bins - 1, i + 1)];
                values[i] = left * 0.25 + copy[i] * 0.5 + right * 0.25;
            }
        };
        const int passes = std::clamp(int(std::lround(1.0 + smoothness * 4.0)), 1, 5);
        for (int pass = 0; pass < passes; ++pass) {
            blur(srcHist);
            blur(refHist);
        }

        double srcSum = 0.0;
        double refSum = 0.0;
        for (int i = 0; i < Bins; ++i) {
            srcSum += srcHist[i];
            refSum += refHist[i];
            look.srcCdf[i] = srcSum;
            look.refCdf[i] = refSum;
        }
        blur(srcSumA);
        blur(srcSumB);
        blur(srcCount);
        for (int i = 0; i < Bins; ++i) {
            if (srcCount[i] > 1e-8) {
                look.srcMeanA[i] = srcSumA[i] / srcCount[i];
                look.srcMeanB[i] = srcSumB[i] / srcCount[i];
            }
        }
        int srcLast = -1;
        for (int i = 0; i < Bins; ++i) {
            if (srcCount[i] > 1e-8) srcLast = i;
            else if (srcLast >= 0) {
                look.srcMeanA[i] = look.srcMeanA[srcLast];
                look.srcMeanB[i] = look.srcMeanB[srcLast];
            }
        }
        int srcFirst = -1;
        for (int i = 0; i < Bins; ++i) if (srcCount[i] > 1e-8) { srcFirst = i; break; }
        if (srcFirst > 0) {
            for (int i = 0; i < srcFirst; ++i) {
                look.srcMeanA[i] = look.srcMeanA[srcFirst];
                look.srcMeanB[i] = look.srcMeanB[srcFirst];
            }
        }

        bool hasTone[Bins]{};
        if (!referenceImage.isNull() && referenceImage.width() >= 2 && referenceImage.height() >= 2) {
            double hueA[HueBins][Bins]{};
            double hueB[HueBins][Bins]{};
            double hueN[HueBins][Bins]{};
            const int stride = std::max(1, std::max(referenceImage.width(), referenceImage.height()) / 320);
            for (int y = 0; y < referenceImage.height(); y += stride) {
                for (int x = 0; x < referenceImage.width(); x += stride) {
                    const QColor color = referenceImage.pixelColor(x, y);
                    if (color.alpha() <= 0) continue;
                    const Lab lab = rgbToOklab(color);
                    if (std::hypot(lab.a, lab.b) < 0.02) continue;
                    const int bin = std::clamp(int(std::clamp(lab.l, 0.0, 1.0) * (Bins - 1) + 0.5), 0, Bins - 1);
                    const int hue = hueIndex(lab.a, lab.b);
                    hueA[hue][bin] += lab.a;
                    hueB[hue][bin] += lab.b;
                    hueN[hue][bin] += 1.0;
                }
            }
            for (int bin = 0; bin < Bins; ++bin) {
                int bestHue = -1;
                double bestN = 0.0;
                for (int hue = 0; hue < HueBins; ++hue) {
                    if (hueN[hue][bin] > bestN) {
                        bestN = hueN[hue][bin];
                        bestHue = hue;
                    }
                }
                if (bestHue < 0 || bestN < 2.0) continue;
                hasTone[bin] = true;
                look.chromaA[bin] = hueA[bestHue][bin] / bestN;
                look.chromaB[bin] = hueB[bestHue][bin] / bestN;
                for (int hue = 0; hue < HueBins; ++hue) {
                    // A sub colour only has to be a few percent of this lightness.
                    // The old fifth-of-the-winner gate dropped the foliage in a blue scene.
                    if (hue == bestHue || hueN[hue][bin] < 3.0 || hueN[hue][bin] * 25.0 < bestN) continue;
                    look.accentA[hue][bin] = hueA[hue][bin] / hueN[hue][bin];
                    look.accentB[hue][bin] = hueB[hue][bin] / hueN[hue][bin];
                    look.accentW[hue][bin] = hueN[hue][bin];
                }
            }
        }
        int prevTone = -1;
        for (int bin = 0; bin < Bins; ++bin) {
            if (!hasTone[bin]) continue;
            if (prevTone >= 0) {
                for (int gap = prevTone + 1; gap < bin; ++gap) {
                    const double f = double(gap - prevTone) / double(bin - prevTone);
                    look.chromaA[gap] = look.chromaA[prevTone] * (1.0 - f) + look.chromaA[bin] * f;
                    look.chromaB[gap] = look.chromaB[prevTone] * (1.0 - f) + look.chromaB[bin] * f;
                }
            }
            prevTone = bin;
        }
        if (prevTone >= 0) {
            int firstTone = 0;
            while (firstTone < Bins && !hasTone[firstTone]) ++firstTone;
            for (int bin = 0; bin < firstTone; ++bin) {
                look.chromaA[bin] = look.chromaA[firstTone];
                look.chromaB[bin] = look.chromaB[firstTone];
            }
            for (int bin = prevTone + 1; bin < Bins; ++bin) {
                look.chromaA[bin] = look.chromaA[prevTone];
                look.chromaB[bin] = look.chromaB[prevTone];
            }
        }

        look.valid = srcSum > 16.0 && refSum > 16.0;
        return look;
    }

    static int hueIndex(double a, double b)
    {
        const double turns = (std::atan2(b, a) + 3.14159265358979323846) / (2.0 * 3.14159265358979323846);
        int index = int(turns * HueBins);
        if (index < 0) index = 0;
        if (index >= HueBins) index = HueBins - 1;
        return index;
    }

    static double cdfAt(const double *cdf, double lightness)
    {
        const double pos = std::clamp(lightness, 0.0, 1.0) * (Bins - 1);
        const int i = std::min(int(pos), Bins - 2);
        const double f = pos - i;
        return cdf[i] * (1.0 - f) + cdf[i + 1] * f;
    }

    static double invertCdf(const double *cdf, double p)
    {
        if (cdf[Bins - 1] <= 1e-8) return std::clamp(p, 0.0, 1.0);
        p = std::clamp(p, 0.0, cdf[Bins - 1]);
        int i = 0;
        while (i < Bins - 2 && cdf[i + 1] < p) ++i;
        const double span = cdf[i + 1] - cdf[i];
        const double f = span > 1e-8 ? (p - cdf[i]) / span : 0.0;
        return std::clamp((i + f) / double(Bins - 1), 0.0, 1.0);
    }

    double matchLightness(double lightness) const
    {
        if (align <= 0.0 || srcCdf[Bins - 1] <= 1e-8 || refCdf[Bins - 1] <= 1e-8) return lightness;
        const double percentile = cdfAt(srcCdf, lightness) / srcCdf[Bins - 1];
        const double matched = invertCdf(refCdf, percentile * refCdf[Bins - 1]);
        const double aligned = lightness + (matched - lightness) * align;
        // Luminance is an extra exposure on top of the histogram match. 0 leaves it alone.
        return std::clamp(aligned + (luminance * 0.12), 0.0, 1.0);
    }

    Lab chromaAt(double lightness) const
    {
        const double pos = std::clamp(lightness, 0.0, 1.0) * (Bins - 1);
        const int i = std::min(int(pos), Bins - 2);
        const double f = pos - i;
        return {lightness, chromaA[i] * (1.0 - f) + chromaA[i + 1] * f, chromaB[i] * (1.0 - f) + chromaB[i + 1] * f};
    }

    Lab sourceMeanAt(double lightness) const
    {
        const double pos = std::clamp(lightness, 0.0, 1.0) * (Bins - 1);
        const int i = std::min(int(pos), Bins - 2);
        const double f = pos - i;
        return {lightness, srcMeanA[i] * (1.0 - f) + srcMeanA[i + 1] * f, srcMeanB[i] * (1.0 - f) + srcMeanB[i + 1] * f};
    }

    Lab gradeAt(double mappedL, const Lab &value) const
    {
        const Lab main = chromaAt(mappedL);
        const Lab srcMean = sourceMeanAt(value.l);
        const double dev = std::hypot(value.a - srcMean.a, value.b - srcMean.b);
        const double t = std::clamp((dev - 0.035) / 0.05, 0.0, 1.0);
        const double mix = t * t * (3.0 - 2.0 * t);
        if (mix <= 0.0 || std::hypot(value.a, value.b) < 0.03) return main;
        const int hue = hueIndex(value.a, value.b);
        const int center = std::clamp(int(std::clamp(mappedL, 0.0, 1.0) * (Bins - 1) + 0.5), 0, Bins - 1);
        double best = 1.0e9;
        double accentAFound = main.a;
        double accentBFound = main.b;
        bool found = false;
        for (int dl = -4; dl <= 4; ++dl) {
            const int bin = center + dl;
            if (bin < 0 || bin >= Bins) continue;
            for (int dh = -1; dh <= 1; ++dh) {
                const int h = (hue + dh + HueBins) % HueBins;
                if (accentW[h][bin] < 2.0) continue;
                const double score = std::abs(dh) + std::abs(dl) * 0.35;
                if (score < best) {
                    best = score;
                    accentAFound = accentA[h][bin];
                    accentBFound = accentB[h][bin];
                    found = true;
                }
            }
        }
        if (!found) return main;
        return {mappedL, main.a + (accentAFound - main.a) * mix, main.b + (accentBFound - main.b) * mix};
    }

    bool accentNear(double mappedL, double da, double db, double &outA, double &outB) const
    {
        const int center = std::clamp(int(std::clamp(mappedL, 0.0, 1.0) * (Bins - 1) + 0.5), 0, Bins - 1);
        const bool hasDir = std::hypot(da, db) > 1e-4;
        const int hue = hasDir ? hueIndex(da, db) : 0;
        double strongScore = -1.0;
        double strongA = 0.0;
        double strongB = 0.0;
        bool haveStrong = false;
        double hueScore = 1.0e9;
        double hueA = 0.0;
        double hueB = 0.0;
        bool haveHue = false;
        for (int dl = -10; dl <= 10; ++dl) {
            const int bin = center + dl;
            if (bin < 0 || bin >= Bins) continue;
            for (int h = 0; h < HueBins; ++h) {
                const double w = accentW[h][bin];
                if (w < 3.0) continue;
                const double near = w / (1.0 + std::abs(dl) * 0.35);
                if (near > strongScore) {
                    strongScore = near;
                    strongA = accentA[h][bin];
                    strongB = accentB[h][bin];
                    haveStrong = true;
                }
                if (!hasDir) continue;
                int dh = std::abs(h - hue);
                if (dh > HueBins / 2) dh = HueBins - dh;
                // Only a genuinely similar hue wins. Otherwise the strongest
                // reference sub colour is used, so a warm source colour can
                // still land on green foliage.
                if (dh > 1) continue;
                const double score = dh + std::abs(dl) * 0.3;
                if (score < hueScore) {
                    hueScore = score;
                    hueA = accentA[h][bin];
                    hueB = accentB[h][bin];
                    haveHue = true;
                }
            }
        }
        if (haveHue) {
            outA = hueA;
            outB = hueB;
            return true;
        }
        if (haveStrong) {
            outA = strongA;
            outB = strongB;
            return true;
        }
        return false;
    }

    Lab map(Lab value) const
    {
        const double mappedL = matchLightness(value.l);
        const Lab main = chromaAt(mappedL);
        const Lab srcMean = sourceMeanAt(value.l);
        const double keep = std::clamp(keepLocal, 0.0, 1.0);
        const double match = std::clamp(matchLocal, 0.0, 1.0);
        const double shadowT = std::clamp(mappedL / 0.4, 0.0, 1.0);
        const double shadow = shadowColor + (1.0 - shadowColor) * shadowT * shadowT * (3.0 - 2.0 * shadowT);
        const double highlight = std::clamp((mappedL - 0.6) / 0.35, 0.0, 1.0);
        const double warmth = main.b > 0 ? 1.0 + highlight * (highlightWarmth - 1.0) : 1.0;
        const double sourceChroma = std::hypot(value.a, value.b);
        const double protect = 1.0 - neutral * std::clamp((0.075 - sourceChroma) / 0.075, 0.0, 1.0);
        const double amount = std::clamp(chromaAmount * strength * protect * shadow, 0.0, 2.0);
        const double da = value.a - srcMean.a;
        const double db = value.b - srcMean.b;
        const double dev = std::hypot(da, db);
        // Source sub colours in a flat photo sit only a little way off the mean.
        // Full strength by ~0.02 OKLab, which is the top of that spread.
        const double depart = std::clamp((dev - 0.008) / 0.012, 0.0, 1.0);
        const double presence = depart * depart * (3.0 - 2.0 * depart);
        constexpr double gain = 2.0;
        double srcA = da * gain;
        double srcB = db * gain;
        double srcMag = std::hypot(srcA, srcB);
        if (srcMag > 0.22) {
            srcA *= 0.22 / srcMag;
            srcB *= 0.22 / srcMag;
        }
        double offA = srcA * keep;
        double offB = srcB * keep;
        double accentAValue = 0.0;
        double accentBValue = 0.0;
        if (match > 0.0 && presence > 0.0 && accentNear(mappedL, da, db, accentAValue, accentBValue)) {
            double refA = accentAValue - main.a;
            double refB = accentBValue - main.b;
            const double refMag = std::hypot(refA, refB);
            if (refMag > 0.008) {
                const double take = match * presence;
                offA += (refA - offA) * take;
                offB += (refB - offB) * take;
            }
        }
        return {mappedL,
                value.a + (main.a * warmth - value.a) * amount + offA,
                value.b + (main.b * warmth - value.b) * amount + offB};
    }
};

inline Lut buildLookLut(const LookTransfer &look)
{
    Lut lut;
    if (!look.valid) return lut;
    for (int r = 0; r < Lut::Size; ++r) {
        for (int g = 0; g < Lut::Size; ++g) {
            for (int b = 0; b < Lut::Size; ++b) {
                const QColor input = QColor::fromRgbF(double(r) / (Lut::Size - 1), double(g) / (Lut::Size - 1), double(b) / (Lut::Size - 1));
                const Lab mapped = look.map(rgbToOklab(input));
                const QColor output = oklabToRgb(mapped);
                lut.values[Lut::index(r, g, b, 0)] = float(output.redF());
                lut.values[Lut::index(r, g, b, 1)] = float(output.greenF());
                lut.values[Lut::index(r, g, b, 2)] = float(output.blueF());
            }
        }
    }
    lut.valid = true;
    return lut;
}

inline Lut buildLut(const std::array<Pair, 4> &pairs, double luminance,
                    double chroma, double strength, double neutralProtection,
                    double smoothness, double shadowColor = 1.0,
                    double highlightWarmth = 1.0,
                    bool alignBrightness = true,
                    const LightnessStats &sourceLightness = {},
                    const LightnessStats &referenceLightness = {})
{
    Lut lut;
    const bool useAlign = alignBrightness && sourceLightness.valid && referenceLightness.valid;
    std::array<Lab, 4> source{}, delta{};
    int count = 0;
    for (int i = 0; i < 4; ++i) {
        if (!pairs[i].valid) continue;
        source[count] = rgbToOklab(pairs[i].source);
        if (useAlign) {
            // Match overall brightness first so sample deltas mostly carry colour.
            source[count].l = alignLightness(source[count].l, sourceLightness, referenceLightness);
        }
        const Lab target = rgbToOklab(pairs[i].target);
        delta[count] = {target.l - source[count].l, target.a - source[count].a, target.b - source[count].b};
        ++count;
    }
    if (count < 2) return lut;
    const double sigma = std::clamp(0.025 + smoothness * 0.28, 0.025, 0.5);
    const double sigma2 = 2.0 * sigma * sigma;
    // Grade transfer is tonal: weight mainly by lightness so green/blue source
    // pixels still pick up the matching tonal pair (full Lab distance left them
    // under-weighted and produced a thin wash instead of the reference look).
    constexpr double kChromaMetric = 0.22;
    const auto pairDistance2 = [&](const Lab &lhs, const Lab &rhs) {
        const double dl = lhs.l - rhs.l;
        const double da = (lhs.a - rhs.a) * kChromaMetric;
        const double db = (lhs.b - rhs.b) * kChromaMetric;
        return dl * dl + da * da + db * db;
    };
    // Solve the Gaussian RBF system so explicit samples are interpolation
    // constraints, rather than averaging different colour roles together.
    double system[4][7] = {};
    for (int i = 0; i < count; ++i) {
        for (int j = 0; j < count; ++j) {
            system[i][j] = std::exp(-pairDistance2(source[i], source[j]) / sigma2);
        }
        system[i][count]=delta[i].l;
        system[i][count+1]=delta[i].a;
        system[i][count+2]=delta[i].b;
    }
    for (int col=0; col<count; ++col) {
        int pivot=col;
        for (int row=col+1; row<count; ++row)
            if (std::abs(system[row][col])>std::abs(system[pivot][col])) pivot=row;
        // Identical or numerically indistinguishable source samples are ambiguous.
        if (std::abs(system[pivot][col])<1e-8) return lut;
        for (int j=0;j<count+3;++j) std::swap(system[pivot][j],system[col][j]);
        const double divisor=system[col][col];
        for (int j=col;j<count+3;++j) system[col][j]/=divisor;
        for (int row=0;row<count;++row) if(row!=col) {
            const double factor=system[row][col];
            for(int j=col;j<count+3;++j) system[row][j]-=factor*system[col][j];
        }
    }
    for(int i=0;i<count;++i) delta[i]={system[i][count],system[i][count+1],system[i][count+2]};
    const double neutral = std::clamp(neutralProtection, 0.0, 1.0);
    const double lAmount = std::clamp(luminance, 0.0, 2.0);
    const double cAmount = std::clamp(chroma, 0.0, 2.0);
    const double total = std::clamp(strength, 0.0, 1.0);
    for (int r = 0; r < Lut::Size; ++r) {
        for (int g = 0; g < Lut::Size; ++g) {
            for (int b = 0; b < Lut::Size; ++b) {
                const QColor input = QColor::fromRgbF(double(r)/(Lut::Size-1), double(g)/(Lut::Size-1), double(b)/(Lut::Size-1));
                Lab x = rgbToOklab(input);
                if (useAlign) {
                    x.l = alignLightness(x.l, sourceLightness, referenceLightness);
                }
                Lab d{};
                double nearest = 0.0;
                for (int i = 0; i < count; ++i) {
                    const double weight = std::exp(-pairDistance2(x, source[i]) / sigma2);
                    d.l += weight * delta[i].l; d.a += weight * delta[i].a; d.b += weight * delta[i].b;
                    nearest = std::max(nearest, weight);
                }
                const double shadowT = std::clamp(x.l / 0.4, 0.0, 1.0);
                const double shadow = std::clamp(shadowColor,0.0,1.0) +
                    (1.0-std::clamp(shadowColor,0.0,1.0))*shadowT*shadowT*(3.0-2.0*shadowT);
                const double highlight = std::clamp((x.l-0.6)/0.35,0.0,1.0);
                const double warmth = d.b > 0 ? 1.0 + highlight*(std::clamp(highlightWarmth,0.0,2.0)-1.0) : 1.0;
                const double chromaMagnitude = std::hypot(x.a, x.b);
                const double protect = 1.0 - neutral * std::clamp((0.075 - chromaMagnitude) / 0.075, 0.0, 1.0) * (1.0 - nearest);
                const Lab mapped{x.l + d.l*lAmount*total, x.a + d.a*cAmount*total*protect*shadow*warmth, x.b + d.b*cAmount*total*protect*shadow*warmth};
                const QColor output = oklabToRgb(mapped);
                lut.values[Lut::index(r,g,b,0)] = float(output.redF());
                lut.values[Lut::index(r,g,b,1)] = float(output.greenF());
                lut.values[Lut::index(r,g,b,2)] = float(output.blueF());
            }
        }
    }
    lut.valid = true;
    return lut;
}

inline QByteArray encodeLut(const Lut &lut)
{
    if (!lut.valid) return {};
    QByteArray bytes;
    QDataStream stream(&bytes, QIODevice::WriteOnly);
    stream.setByteOrder(QDataStream::LittleEndian);
    stream.setVersion(QDataStream::Qt_5_15);
    stream.setFloatingPointPrecision(QDataStream::SinglePrecision);
    stream << quint32(0x474c5431) << quint16(Lut::Size);
    for (float value : lut.values) stream << value;
    return bytes;
}

inline Lut decodeLut(const QByteArray &bytes)
{
    Lut lut;
    const qsizetype expected = 4 + 2 + qsizetype(lut.values.size()) * qsizetype(sizeof(float));
    if (bytes.size() != expected) return lut;
    QDataStream stream(bytes);
    stream.setByteOrder(QDataStream::LittleEndian);
    stream.setVersion(QDataStream::Qt_5_15);
    stream.setFloatingPointPrecision(QDataStream::SinglePrecision);
    quint32 magic = 0; quint16 size = 0;
    stream >> magic >> size;
    if (magic != 0x474c5431 || size != Lut::Size) return lut;
    for (float &value : lut.values) {
        stream >> value;
        if (!std::isfinite(value) || value < 0 || value > 1) return {};
    }
    lut.valid = stream.status() == QDataStream::Ok && stream.atEnd();
    return lut;
}

inline QByteArray inflateStored(const QByteArray &stored)
{
    if (stored.isEmpty()) return {};
    const QByteArray inflated = qUncompress(stored);
    return inflated.isEmpty() ? stored : inflated;
}

inline void writeDoubles(QDataStream &stream, const double *values, int count)
{
    for (int i = 0; i < count; ++i) stream << values[i];
}

inline bool readDoubles(QDataStream &stream, double *values, int count)
{
    for (int i = 0; i < count; ++i) {
        stream >> values[i];
        if (!std::isfinite(values[i])) return false;
    }
    return stream.status() == QDataStream::Ok;
}

// Compact grade. Krita stores filter configuration in kritarc bookmarks, so the
// 33^3 display grid stays in memory and is rebuilt from this.
inline QByteArray encodeLook(const LookTransfer &look)
{
    if (!look.valid) return {};
    QByteArray bytes;
    QDataStream stream(&bytes, QIODevice::WriteOnly);
    stream.setByteOrder(QDataStream::LittleEndian);
    stream.setVersion(QDataStream::Qt_5_15);
    stream.setFloatingPointPrecision(QDataStream::DoublePrecision);
    stream << quint32(0x474c4b31) << quint16(1) << quint16(LookTransfer::Bins) << quint16(LookTransfer::HueBins);
    const double scalars[] = {
        look.align, look.strength, look.chromaAmount, look.luminance, look.neutral,
        look.shadowColor, look.highlightWarmth, look.keepLocal, look.matchLocal
    };
    writeDoubles(stream, scalars, 9);
    writeDoubles(stream, look.srcCdf, LookTransfer::Bins);
    writeDoubles(stream, look.refCdf, LookTransfer::Bins);
    writeDoubles(stream, look.chromaA, LookTransfer::Bins);
    writeDoubles(stream, look.chromaB, LookTransfer::Bins);
    writeDoubles(stream, look.srcMeanA, LookTransfer::Bins);
    writeDoubles(stream, look.srcMeanB, LookTransfer::Bins);
    writeDoubles(stream, &look.accentA[0][0], LookTransfer::HueBins * LookTransfer::Bins);
    writeDoubles(stream, &look.accentB[0][0], LookTransfer::HueBins * LookTransfer::Bins);
    writeDoubles(stream, &look.accentW[0][0], LookTransfer::HueBins * LookTransfer::Bins);
    return stream.status() == QDataStream::Ok ? bytes : QByteArray();
}

inline LookTransfer decodeLook(const QByteArray &bytes)
{
    LookTransfer look;
    if (bytes.isEmpty()) return look;
    QDataStream stream(bytes);
    stream.setByteOrder(QDataStream::LittleEndian);
    stream.setVersion(QDataStream::Qt_5_15);
    stream.setFloatingPointPrecision(QDataStream::DoublePrecision);
    quint32 magic = 0; quint16 version = 0, bins = 0, hueBins = 0;
    stream >> magic >> version >> bins >> hueBins;
    if (magic != 0x474c4b31 || version != 1 || bins != LookTransfer::Bins || hueBins != LookTransfer::HueBins)
        return {};
    double scalars[9] = {};
    if (!readDoubles(stream, scalars, 9)) return {};
    look.align = scalars[0];
    look.strength = scalars[1];
    look.chromaAmount = scalars[2];
    look.luminance = scalars[3];
    look.neutral = scalars[4];
    look.shadowColor = scalars[5];
    look.highlightWarmth = scalars[6];
    look.keepLocal = scalars[7];
    look.matchLocal = scalars[8];
    if (!readDoubles(stream, look.srcCdf, LookTransfer::Bins)
        || !readDoubles(stream, look.refCdf, LookTransfer::Bins)
        || !readDoubles(stream, look.chromaA, LookTransfer::Bins)
        || !readDoubles(stream, look.chromaB, LookTransfer::Bins)
        || !readDoubles(stream, look.srcMeanA, LookTransfer::Bins)
        || !readDoubles(stream, look.srcMeanB, LookTransfer::Bins)
        || !readDoubles(stream, &look.accentA[0][0], LookTransfer::HueBins * LookTransfer::Bins)
        || !readDoubles(stream, &look.accentB[0][0], LookTransfer::HueBins * LookTransfer::Bins)
        || !readDoubles(stream, &look.accentW[0][0], LookTransfer::HueBins * LookTransfer::Bins))
        return {};
    look.valid = stream.status() == QDataStream::Ok && stream.atEnd();
    return look.valid ? look : LookTransfer{};
}

inline QByteArray encodeLightness(const LightnessStats &source, const LightnessStats &reference)
{
    if (!source.valid && !reference.valid) return {};
    QByteArray bytes;
    QDataStream stream(&bytes, QIODevice::WriteOnly);
    stream.setByteOrder(QDataStream::LittleEndian);
    stream.setVersion(QDataStream::Qt_5_15);
    stream.setFloatingPointPrecision(QDataStream::DoublePrecision);
    stream << quint32(0x474c5331);
    stream << quint8(source.valid ? 1 : 0) << source.mean << source.stdev;
    stream << quint8(reference.valid ? 1 : 0) << reference.mean << reference.stdev;
    return stream.status() == QDataStream::Ok ? bytes : QByteArray();
}

inline void decodeLightness(const QByteArray &bytes, LightnessStats &source, LightnessStats &reference)
{
    source = {};
    reference = {};
    if (bytes.isEmpty()) return;
    QDataStream stream(bytes);
    stream.setByteOrder(QDataStream::LittleEndian);
    stream.setVersion(QDataStream::Qt_5_15);
    stream.setFloatingPointPrecision(QDataStream::DoublePrecision);
    quint32 magic = 0;
    quint8 sourceValid = 0, referenceValid = 0;
    double sourceMean = 0, sourceStdev = 0, referenceMean = 0, referenceStdev = 0;
    stream >> magic;
    if (magic != 0x474c5331) return;
    stream >> sourceValid >> sourceMean >> sourceStdev >> referenceValid >> referenceMean >> referenceStdev;
    if (stream.status() != QDataStream::Ok || !stream.atEnd()) return;
    if (sourceValid && std::isfinite(sourceMean) && std::isfinite(sourceStdev)) {
        source.mean = sourceMean;
        source.stdev = sourceStdev;
        source.valid = true;
    }
    if (referenceValid && std::isfinite(referenceMean) && std::isfinite(referenceStdev)) {
        reference.mean = referenceMean;
        reference.stdev = referenceStdev;
        reference.valid = true;
    }
}

inline Lut lutForGuidedStorage(const QByteArray &lookBytes,
                                const QByteArray &legacyLutBytes,
                                const std::array<Pair, 4> &pairs,
                                double chroma,
                                double strength,
                                double smoothness,
                                bool alignBrightness,
                                const LightnessStats &sourceLightness,
                                const LightnessStats &referenceLightness)
{
    const LookTransfer look = decodeLook(lookBytes);
    if (look.valid) return buildLookLut(look);
    const Lut legacy = decodeLut(legacyLutBytes);
    if (legacy.valid) return legacy;
    return buildLut(pairs, 0.0, chroma, strength, 0.0, smoothness, 1.0, 1.0,
                    alignBrightness, sourceLightness, referenceLightness);
}

inline QByteArray encodePairs(const std::array<Pair, 4> &pairs)
{
    QByteArray bytes;
    QDataStream stream(&bytes, QIODevice::WriteOnly);
    stream.setByteOrder(QDataStream::LittleEndian);
    stream.setVersion(QDataStream::Qt_5_15);
    stream.setFloatingPointPrecision(QDataStream::SinglePrecision);
    stream << quint32(0x47504331);
    for (const Pair &pair : pairs) {
        stream << quint8(pair.valid ? 1 : 0);
        stream << pair.source.redF() << pair.source.greenF() << pair.source.blueF();
        stream << pair.target.redF() << pair.target.greenF() << pair.target.blueF();
    }
    return bytes;
}

inline std::array<Pair, 4> decodePairs(const QByteArray &bytes)
{
    std::array<Pair, 4> pairs{};
    QDataStream stream(bytes);
    stream.setByteOrder(QDataStream::LittleEndian);
    stream.setVersion(QDataStream::Qt_5_15);
    stream.setFloatingPointPrecision(QDataStream::SinglePrecision);
    quint32 magic = 0; stream >> magic;
    if (magic != 0x47504331) return pairs;
    for (Pair &pair : pairs) {
        quint8 valid = 0; double sr=0,sg=0,sb=0,tr=0,tg=0,tb=0;
        stream >> valid >> sr >> sg >> sb >> tr >> tg >> tb;
        if (valid && std::isfinite(sr) && std::isfinite(sg) && std::isfinite(sb)
            && std::isfinite(tr) && std::isfinite(tg) && std::isfinite(tb)) {
            pair.valid = true;
            pair.source = QColor::fromRgbF(std::clamp(sr,0.0,1.0),std::clamp(sg,0.0,1.0),std::clamp(sb,0.0,1.0));
            pair.target = QColor::fromRgbF(std::clamp(tr,0.0,1.0),std::clamp(tg,0.0,1.0),std::clamp(tb,0.0,1.0));
        }
    }
    return stream.status() == QDataStream::Ok ? pairs : std::array<Pair, 4>{};
}

} // namespace tfm::guided
