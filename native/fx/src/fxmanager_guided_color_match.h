#pragma once

#include <QByteArray>
#include <QColor>
#include <QDataStream>
#include <QIODevice>
#include <algorithm>
#include <array>
#include <cmath>
#include <vector>

namespace fxmanager::guided {

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

    QColor sample(const QColor &color) const
    {
        if (!valid) return color;
        const double r = std::clamp(double(color.redF()), 0.0, 1.0) * (Size - 1);
        const double g = std::clamp(double(color.greenF()), 0.0, 1.0) * (Size - 1);
        const double b = std::clamp(double(color.blueF()), 0.0, 1.0) * (Size - 1);
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
        return QColor::fromRgbF(std::clamp(out[0], 0.0, 1.0), std::clamp(out[1], 0.0, 1.0), std::clamp(out[2], 0.0, 1.0), color.alphaF());
    }
};

inline Lut buildLut(const std::array<Pair, 4> &pairs, double luminance,
                    double chroma, double strength, double neutralProtection,
                    double smoothness, double shadowColor = 1.0,
                    double highlightWarmth = 1.0)
{
    Lut lut;
    std::array<Lab, 4> source{}, delta{};
    int count = 0;
    for (int i = 0; i < 4; ++i) {
        if (!pairs[i].valid) continue;
        source[count] = rgbToOklab(pairs[i].source);
        const Lab target = rgbToOklab(pairs[i].target);
        delta[count] = {target.l - source[count].l, target.a - source[count].a, target.b - source[count].b};
        ++count;
    }
    if (count < 2) return lut;
    const double sigma = std::clamp(0.025 + smoothness * 0.28, 0.025, 0.5);
    const double sigma2 = 2.0 * sigma * sigma;
    // Solve the Gaussian RBF system so explicit samples are interpolation
    // constraints, rather than averaging different colour roles together.
    double system[4][7] = {};
    for (int i = 0; i < count; ++i) {
        for (int j = 0; j < count; ++j) {
            const double dl=source[i].l-source[j].l, da=source[i].a-source[j].a, db=source[i].b-source[j].b;
            system[i][j] = std::exp(-(dl*dl+da*da+db*db)/sigma2);
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
                const Lab x = rgbToOklab(input);
                Lab d{};
                double nearest = 0.0;
                for (int i = 0; i < count; ++i) {
                    const double dl = x.l - source[i].l, da = x.a - source[i].a, db = x.b - source[i].b;
                    const double weight = std::exp(-(dl*dl + da*da + db*db) / sigma2);
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

} // namespace fxmanager::guided
