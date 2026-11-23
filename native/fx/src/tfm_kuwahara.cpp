#include "tfm_kuwahara.h"
#include "tfm_filter_widget.h"
#include "tfm_processing.h"
#include "tfm_kuwahara_gpu.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <QImage>
#include <filter/kis_filter_category_ids.h>
#include <filter/kis_filter_configuration.h>
#include <kis_paint_device.h>
#include <kis_painter.h>
#include <KisGlobalResourcesInterface.h>
#include <KoUpdater.h>
#include <klocalizedstring.h>

namespace {

struct KuwaharaParams {
    int radius = 2;
    int iterations = 1;
};

inline QRgb clampedPixel(const QImage &image, int x, int y)
{
    return reinterpret_cast<const QRgb *>(image.constScanLine(std::clamp(y, 0, image.height() - 1)))[std::clamp(x, 0, image.width() - 1)];
}

// Each column holds sums for the top and bottom halves of the kernel.
struct Moments {
    int sums[3] = {};
    int squares[3] = {};

    void addPixel(QRgb pixel) {
        const int rgb[] = {qRed(pixel), qGreen(pixel), qBlue(pixel)};
        for (int c = 0; c < 3; ++c) {
            sums[c] += rgb[c];
            squares[c] += rgb[c] * rgb[c];
        }
    }
    void slide(const Moments &enter, const Moments &leave) {
        for (int c = 0; c < 3; ++c) {
            sums[c] += enter.sums[c] - leave.sums[c];
            squares[c] += enter.squares[c] - leave.squares[c];
        }
    }
};

void classicBand(QImage &output, const QImage &source, int y0, int y1, int radius)
{
    const int count = (radius + 1) * (radius + 1);
    const int divisor = count * count;
    const int width = source.width();
    const Moments zero;
    QVector<Moments> top(width), bottom(width);
    for (int y = y0; y < y1; ++y) {
        top.fill(zero);
        bottom.fill(zero);
        for (int dy = 0; dy <= radius; ++dy) {
            const auto *upper = reinterpret_cast<const QRgb *>(source.constScanLine(std::max(0, y - dy)));
            const auto *lower = reinterpret_cast<const QRgb *>(source.constScanLine(std::min(source.height() - 1, y + dy)));
            for (int x = 0; x < width; ++x) {
                top[x].addPixel(upper[x]);
                bottom[x].addPixel(lower[x]);
            }
        }
        Moments quadrants[4];
        for (int dx = 0; dx <= radius; ++dx) {
            const int right = std::min(dx, width - 1);
            quadrants[0].slide(top[0], zero);
            quadrants[1].slide(top[right], zero);
            quadrants[2].slide(bottom[0], zero);
            quadrants[3].slide(bottom[right], zero);
        }
        auto *row = reinterpret_cast<QRgb *>(output.scanLine(y));
        for (int x = 0; x < width; ++x) {
            const Moments *best = &quadrants[0];
            qint64 bestKey = std::numeric_limits<qint64>::max();
            for (const auto &q : quadrants) {
                qint64 numerator = 0;
                for (int c = 0; c < 3; ++c)
                    numerator += qint64(q.squares[c]) * count - qint64(q.sums[c]) * q.sums[c];
                const qint64 key = (64 * numerator + divisor / 2) / divisor;
                if (key < bestKey) { bestKey = key; best = &q; }
            }
            auto mean = [&](int c) { return (best->sums[c] + count / 2) / count; };
            row[x] = qRgba(mean(0), mean(1), mean(2), qAlpha(clampedPixel(source, x, y)));
            const int left = std::max(0, x - radius);
            const int next = std::min(width - 1, x + 1);
            const int right = std::min(width - 1, x + radius + 1);
            quadrants[0].slide(top[next], top[left]);
            quadrants[1].slide(top[right], top[x]);
            quadrants[2].slide(bottom[next], bottom[left]);
            quadrants[3].slide(bottom[right], bottom[x]);
        }
    }
}

void runCpuPass(QImage &output, const QImage &source, const KuwaharaParams &p)
{
    tfm::parallelRows(output.height(), [&](int y0, int y1) { classicBand(output, source, y0, y1, p.radius); });
}

tfm::EncodedRgbaImage floatPass(const tfm::EncodedRgbaImage &source,
                                    int radius, KoUpdater *updater)
{
    auto output=source;
    float *dst=output.pixels.data();
    const float *src=source.pixels.constData();
    tfm::parallelRows(source.height,[&](int y0,int y1) {
        for(int y=y0;y<y1;++y) {
            if(updater && updater->interrupted()) return;
            for(int x=0;x<source.width;++x) {
                const float *center = src + 4 * (y * source.width + x);
                double best = 0.0;
                for(int quadrant=0;quadrant<4;++quadrant) {
                    const int sx=(quadrant&1) ? 1 : -1, sy=(quadrant&2) ? 1 : -1;
                    double sum[3]={}, squares[3]={};
                    for(int dy=0;dy<=radius;++dy) for(int dx=0;dx<=radius;++dx) {
                        const float *p=src+4*(std::clamp(y+dy*sy,0,source.height-1)*source.width+std::clamp(x+dx*sx,0,source.width-1));
                        for(int c=0;c<3;++c) { const double delta = double(p[c]) - center[c]; sum[c] += delta; squares[c] += delta * delta; }
                    }
                    const double inv=1.0/((radius+1)*(radius+1));
                    double variance=0;
                    for(int c=0;c<3;++c) { sum[c]*=inv; variance+=squares[c]*inv-sum[c]*sum[c]; }
                    // Keep full precision: the U8 variance tie quantizer would
                    // erase real differences in a high-depth smooth gradient.
                    if (quadrant == 0 || variance < best - 1e-5 * std::abs(best)) {
                        best=variance;
                        for(int c=0;c<3;++c) dst[4*(y*source.width+x)+c]=float(center[c] + sum[c]);
                    }
                }
            }
        }
    });
    return output;
}

} // namespace

KisFilterKuwahara::KisFilterKuwahara()
    : KisFilter(id(), FiltersCategoryArtisticId, i18n("&Kuwahara..."))
{
    setSupportsAdjustmentLayers(true);
    setColorSpaceIndependence(FULLY_INDEPENDENT);
    // Neighbourhood sampling needs the whole frame; Krita's patch threading
    // would give every patch its own clamped neighbourhood.
    setSupportsThreading(false);
}

KisFilterConfigurationSP KisFilterKuwahara::defaultConfiguration(KisResourcesInterfaceSP r) const
{
    auto c = factoryConfiguration(r);

    tfm::applyBuiltinDefaults(id().id(), c);
    tfm::applyFilterDefaults(id().id(), c);
    return c;
}

KisConfigWidget *KisFilterKuwahara::createConfigurationWidget(QWidget *p, const KisPaintDeviceSP, bool) const
{
    return new TfmFilterWidget(id().id(), {
        {"size", i18n("Size"), 1.0, 12.0, 2.0, 1.0, 0},
        {"iterations", i18n("Iterations"), 1.0, 4.0, 1.0, 1.0, 0},
    }, p, false);
}

QRect KisFilterKuwahara::neededRect(const QRect &rect, const KisFilterConfigurationSP c, int) const
{
    const int halo = int(std::clamp(c ? c->getDouble("size", 2.0) : 2.0, 1.0, 12.0))
        * int(std::clamp(c ? c->getDouble("iterations", 1.0) : 1.0, 1.0, 4.0));
    return rect.adjusted(-halo, -halo, halo, halo);
}

QRect KisFilterKuwahara::changedRect(const QRect &rect, const KisFilterConfigurationSP c, int lod) const
{
    const int iterations = int(std::clamp(c ? c->getDouble("iterations", 1.0) : 1.0, 1.0, 4.0));
    const int halo = int(std::clamp(c ? c->getDouble("size", 2.0) : 2.0, 1.0, 12.0)) * iterations;
    Q_UNUSED(lod);
    return rect.adjusted(-halo, -halo, halo, halo);
}

void KisFilterKuwahara::processImpl(KisPaintDeviceSP d, const QRect &r,
                                    const KisFilterConfigurationSP c, KoUpdater *u) const
{
    if (r.isEmpty() || !d || (u && u->interrupted())) return;
    KuwaharaParams params;
    params.radius = int(std::clamp(c ? c->getDouble("size", 2.0) : 2.0, 1.0, 12.0));
    params.iterations = int(std::clamp(c ? c->getDouble("iterations", 1.0) : 1.0, 1.0, 4.0));

    QRect frame = d->defaultBounds()->bounds();
    if (frame.isEmpty()) frame = d->extent();
    if (frame.isEmpty()) frame = r;
    const QRect outputRect = r.intersected(frame);
    if (outputRect.isEmpty()) return;

    const int halo=params.radius*params.iterations;
    const QRect srcRect = outputRect.adjusted(-halo, -halo, halo, halo).intersected(frame);
    // Later regions would otherwise sample the neighbourhood an earlier region
    // already smoothed and blur it a second time. Read the transaction baseline.
    KisPaintDeviceSP pristine = new KisPaintDevice(d->colorSpace());
    pristine->prepareClone(d);
    KisPainter::copyAreaOptimizedOldData(srcRect.topLeft(), d, pristine, srcRect);
    if(tfm::requiresFloatProcessing(d)) {
        auto current=tfm::readEncodedImage(pristine,srcRect);
        if(current.isNull()) return;
        tfm_kuwahara_gpu::Parameters gpu;
        gpu.srcRect = srcRect;
        gpu.outputRect = outputRect;
        gpu.radius = params.radius;
        QString reason;
        QString device;
        int completedPasses = 0;
        bool usedGpu = false;
        if (tfm::gpuRequested(id().id(), qint64(srcRect.width()) * srcRect.height())) {
            tfm::EncodedRgbaImage passOutput;
            bool ok = true;
            for (int pass = 0; pass < params.iterations && ok; ++pass) {
                ok = tfm_kuwahara_gpu::renderFloat(current, gpu, passOutput, reason, device,
                                                   [u] { return u && u->interrupted(); });
                if (ok) { current = passOutput; ++completedPasses; }
            }
            if (u && u->interrupted()) return;
            usedGpu = ok;
        } else {
            reason = QStringLiteral("CPU selected");
        }
        if (!usedGpu) {
            for(int pass=completedPasses;pass<params.iterations;++pass) {
                current=floatPass(current,params.radius,u);
                if(u && u->interrupted()) return;
            }
        }
        const auto cropped=current.copy(QRect(outputRect.topLeft()-srcRect.topLeft(),outputRect.size()));
        const bool written=tfm::writeEncodedImage(d,cropped,outputRect);
        tfm::reportBackend(id().id(), usedGpu ? QStringLiteral("gpu") : QStringLiteral("cpu"),
            written ? (usedGpu ? QString() : reason) : QStringLiteral("Float output conversion failed; pixels unchanged"),
            usedGpu ? device : QString());
        if(written && u) u->setProgress(100);
        return;
    }
    const QImage source = tfm::readImage(pristine, srcRect);
    if (source.isNull()) return;

    if (tfm::gpuRequested(id().id(), qint64(srcRect.width()) * srcRect.height())) {
        tfm_kuwahara_gpu::Parameters gpu;
        gpu.srcRect = srcRect;
        gpu.outputRect = outputRect;
        gpu.radius = params.radius;
        QImage current = source;
        QString reason, device;
        bool ok = true;
        for (int pass = 0; pass < params.iterations && ok; ++pass) {
            QImage passOutput;
            ok = tfm_kuwahara_gpu::render(current, gpu, passOutput, reason, device, [u] { return u && u->interrupted(); });
            if (ok) current = passOutput;
        }
        if(u && u->interrupted()) return;
        if (ok) {
            const QImage cropped = current.copy(outputRect.x() - srcRect.x(), outputRect.y() - srcRect.y(),
                                                outputRect.width(), outputRect.height());
            tfm::writeImage(d, cropped, outputRect);
            tfm::reportBackend(id().id(), QStringLiteral("gpu"), QString(), device);
            if (u) u->setProgress(100);
            return;
        }
        tfm::reportBackend(id().id(), QStringLiteral("cpu"), reason);
    } else {
        tfm::reportBackend(id().id(), QStringLiteral("cpu"), QStringLiteral("CPU selected"));
    }

    QImage current = source.copy();
    for (int pass = 0; pass < params.iterations; ++pass) {
        QImage next(current.size(), QImage::Format_ARGB32);
        runCpuPass(next, current, params);
        current = next;
        if(u && u->interrupted()) return;
    }
    const QImage cropped = current.copy(outputRect.x() - srcRect.x(), outputRect.y() - srcRect.y(),
                                        outputRect.width(), outputRect.height());
    if(u && u->interrupted()) return;
    tfm::writeImage(d, cropped, outputRect);
    if (u) u->setProgress(100);
}
