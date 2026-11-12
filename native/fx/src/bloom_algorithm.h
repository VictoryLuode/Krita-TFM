#pragma once
#include <QImage>
#include <QVector>
#include <algorithm>
#include <cmath>

namespace tfm { namespace bloom {
// Multi-scale diffusion: successive box passes with growing radii approximate a
// mip/pyramid bloom without extra full-resolution buffers.
constexpr int blurPasses = 3;
inline int boundedRadius(int radius) { return std::clamp(radius, 1, 64); }
inline int levelRadius(int radius, int level)
{
    // Finest → coarsest: r/4, r/2, r (clamped).
    const int base = boundedRadius(radius);
    const int shift = std::max(0, blurPasses - 1 - std::clamp(level, 0, blurPasses - 1));
    return std::max(1, base >> shift);
}
inline int halo(int radius)
{
    int sum = 0;
    for (int level = 0; level < blurPasses; ++level) sum += levelRadius(radius, level);
    return sum;
}

// A quadratic knee joins zero to the hard excess continuously with a
// continuous first derivative. Softness is an absolute luminance width (0..1).
inline double highlight(double luminance, double threshold, double softness)
{
    const double knee = std::clamp(softness, 0.0, 1.0);
    const double excess = luminance - threshold;
    if (knee == 0.0) return std::max(0.0, excess);
    const double t = std::clamp(excess + knee, 0.0, 2.0 * knee);
    return std::max(excess, t * t / (4.0 * knee));
}
struct Light { double r=0, g=0, b=0; };
inline Light operator+(Light a, Light b) { return {a.r+b.r,a.g+b.g,a.b+b.b}; }
inline Light operator-(Light a, Light b) { return {a.r-b.r,a.g-b.g,a.b-b.b}; }
inline Light operator*(Light a, double s) { return {a.r*s,a.g*s,a.b*s}; }

// Constant-zero extension. Running sums make each separable pass O(pixels),
// independent of radius apart from its bounded initial window per row/column.
inline void boxPass(const QVector<Light> &in, QVector<Light> &out,
                    int width, int height, int radius, bool horizontal)
{
    const int lines = horizontal ? height : width;
    const int length = horizontal ? width : height;
    const int stride = horizontal ? 1 : width;
    const double scale = 1.0 / (2 * radius + 1);
    for (int line=0; line<lines; ++line) {
        const int start = horizontal ? line*width : line;
        Light sum;
        for (int i=0; i<=std::min(radius,length-1); ++i) sum = sum + in[start+i*stride];
        for (int i=0; i<length; ++i) {
            out[start+i*stride] = sum * scale;
            if (i-radius>=0) sum = sum - in[start+(i-radius)*stride];
            if (i+radius+1<length) sum = sum + in[start+(i+radius+1)*stride];
        }
    }
}
inline QImage diffuse(const QImage &input, double threshold, int radius,
                      double strength, double softness)
{
    const QImage source = input.convertToFormat(QImage::Format_ARGB32);
    QImage out = source.copy();
    if (source.isNull() || strength<=0) return out;
    radius = boundedRadius(radius);
    threshold = std::clamp(threshold,0.0,1.0);
    QVector<Light> light(source.width()*source.height()), temp(light.size()), accum(light.size());
    for (int y=0; y<source.height(); ++y) {
        const QRgb *row = reinterpret_cast<const QRgb *>(source.constScanLine(y));
        for (int x=0; x<source.width(); ++x) {
            const QRgb p=row[x];
            const double lum=(.2126*qRed(p)+.7152*qGreen(p)+.0722*qBlue(p))/255.0;
            // RGB is straight; alpha weights emitted energy. Hidden RGB emits none.
            const double gain=highlight(lum,threshold,softness)/std::max(.001,1.0-threshold)*(qAlpha(p)/255.0);
            light[y*source.width()+x]={qRed(p)*gain,qGreen(p)*gain,qBlue(p)*gain};
        }
    }
    // Multi-scale: blur the extract at growing radii and accumulate.
    constexpr double weights[blurPasses] = {0.45, 0.35, 0.20};
    for (int level = 0; level < blurPasses; ++level) {
        const int r = levelRadius(radius, level);
        boxPass(light, temp, source.width(), source.height(), r, true);
        boxPass(temp, light, source.width(), source.height(), r, false);
        const double w = weights[level];
        for (int i = 0; i < accum.size(); ++i) accum[i] = accum[i] + light[i] * w;
    }
    light = accum;
    for (int y=0; y<source.height(); ++y) {
        QRgb *row=reinterpret_cast<QRgb *>(out.scanLine(y));
        for (int x=0; x<source.width(); ++x) {
            const QRgb p=row[x];
            // Preserve coverage, including hidden destination RGB. Bloom can
            // brighten existing translucent paint but never creates coverage.
            if (!qAlpha(p)) continue;
            const Light g=light[y*source.width()+x]*std::clamp(strength,0.0,2.0);
            row[x]=qRgba(std::clamp(int(qRed(p)+g.r),0,255),std::clamp(int(qGreen(p)+g.g),0,255),std::clamp(int(qBlue(p)+g.b),0,255),qAlpha(p));
        }
    }
    return out;
}

// Frozen compatibility path: preserve arithmetic, sampling and rounding.
inline void legacyBand(const QImage &source, QImage &out, int y0, int y1, double threshold, int radius, double strength)
{
    const int width = source.width(); const int height = source.height(); const int step = std::max(1, radius / 8); const double denom = std::max(.001, 1.0 - threshold);
    for (int y = y0; y < y1; ++y) {
        const QRgb *src = reinterpret_cast<const QRgb *>(source.constScanLine(y)); QRgb *dst = reinterpret_cast<QRgb *>(out.scanLine(y));
        for (int x = 0; x < width; ++x) {
            const QRgb base = src[x]; const double lum = (.2126*qRed(base)+.7152*qGreen(base)+.0722*qBlue(base))/255.0; dst[x]=base; if(lum<=threshold) continue;
            int sr=0,sg=0,sb=0,n=0;
            for(int oy=-radius;oy<=radius;oy+=step){const int sy=std::clamp(y+oy,0,height-1);const QRgb *row=reinterpret_cast<const QRgb *>(source.constScanLine(sy));for(int ox=-radius;ox<=radius;ox+=step){const QRgb p=row[std::clamp(x+ox,0,width-1)];const double l=(.2126*qRed(p)+.7152*qGreen(p)+.0722*qBlue(p))/255.0;if(l>threshold){sr+=qRed(p);sg+=qGreen(p);sb+=qBlue(p);++n;}}}
            if(n){const double a=std::clamp((lum-threshold)/denom*strength,0.0,1.0);dst[x]=qRgba(std::clamp(int(qRed(base)+sr/n*a),0,255),std::clamp(int(qGreen(base)+sg/n*a),0,255),std::clamp(int(qBlue(base)+sb/n*a),0,255),qAlpha(base));}
        }
    }
}
} }
