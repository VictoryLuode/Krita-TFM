#include "fxmanager_kuwahara.h"
#include "fxmanager_filter_widget.h"
#include "fxmanager_processing.h"
#include "tfm_kuwahara_gpu.h"

#include <algorithm>
#include <cmath>
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

// Classic Kuwahara: pick the quadrant with the smallest variance and use its
// mean. Quadrants include the centre pixel, matching the reference filter.
void classicBand(QImage &output, const QImage &source, int y0, int y1, int radius)
{
    for (int y = y0; y < y1; ++y) {
        QRgb *row = reinterpret_cast<QRgb *>(output.scanLine(y));
        for (int x = 0; x < output.width(); ++x) {
            double bestKey = 1e30;
            double bestR = 0.0, bestG = 0.0, bestB = 0.0;
            for (int q = 0; q < 4; ++q) {
                const int sx = (q & 1) == 0 ? -1 : 1;
                const int sy = (q & 2) == 0 ? -1 : 1;
                double sumR = 0.0, sumG = 0.0, sumB = 0.0;
                double sumR2 = 0.0, sumG2 = 0.0, sumB2 = 0.0;
                int count = 0;
                for (int dy = 0; dy <= radius; ++dy) {
                    for (int dx = 0; dx <= radius; ++dx) {
                        const QRgb s = clampedPixel(source, x + dx * sx, y + dy * sy);
                        const double sr = qRed(s), sg = qGreen(s), sb = qBlue(s);
                        sumR += sr; sumG += sg; sumB += sb;
                        sumR2 += sr * sr; sumG2 += sg * sg; sumB2 += sb * sb;
                        ++count;
                    }
                }
                const double inv = 1.0 / count;
                const double meanR = sumR * inv, meanG = sumG * inv, meanB = sumB * inv;
                const double variance = (sumR2 * inv - meanR * meanR) + (sumG2 * inv - meanG * meanG) + (sumB2 * inv - meanB * meanB);
                // Quantise so float rounding cannot flip the argmin on a tie;
                // the GPU path applies the same rule.
                const double key = std::floor(variance * 64.0 + 0.5);
                if (key < bestKey) { bestKey = key; bestR = meanR; bestG = meanG; bestB = meanB; }
            }
            row[x] = qRgba(int(std::lround(bestR)), int(std::lround(bestG)), int(std::lround(bestB)), qAlpha(clampedPixel(source, x, y)));
        }
    }
}

void runCpuPass(QImage &output, const QImage &source, const KuwaharaParams &p)
{
    fxmanager::parallelRows(output.height(), [&](int y0, int y1) { classicBand(output, source, y0, y1, p.radius); });
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
    c->setProperty("size", 2.0);
    c->setProperty("iterations", 1.0);
    fxmanager::applyFilterDefaults(id().id(), c);
    return c;
}

KisConfigWidget *KisFilterKuwahara::createConfigurationWidget(QWidget *p, const KisPaintDeviceSP, bool) const
{
    return new FxManagerFilterWidget(id().id(), {
        {"size", i18n("Size"), 1.0, 12.0, 2.0, 1.0, 0},
        {"iterations", i18n("Iterations"), 1.0, 4.0, 1.0, 1.0, 0},
    }, p, false);
}

QRect KisFilterKuwahara::neededRect(const QRect &rect, const KisFilterConfigurationSP c, int) const
{
    const int halo = int(std::clamp(c ? c->getDouble("size", 2.0) : 2.0, 1.0, 12.0));
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
    if (r.isEmpty() || !d) return;
    KuwaharaParams params;
    params.radius = int(std::clamp(c ? c->getDouble("size", 2.0) : 2.0, 1.0, 12.0));
    params.iterations = int(std::clamp(c ? c->getDouble("iterations", 1.0) : 1.0, 1.0, 4.0));

    QRect frame = d->defaultBounds()->bounds();
    if (frame.isEmpty()) frame = d->extent();
    if (frame.isEmpty()) frame = r;
    const QRect outputRect = r.intersected(frame);
    if (outputRect.isEmpty()) return;

    const QRect srcRect = outputRect.adjusted(-params.radius, -params.radius, params.radius, params.radius).intersected(frame);
    // Later regions would otherwise sample the neighbourhood an earlier region
    // already smoothed and blur it a second time. Read the transaction baseline.
    KisPaintDeviceSP pristine = new KisPaintDevice(d->colorSpace());
    pristine->prepareClone(d);
    KisPainter::copyAreaOptimizedOldData(srcRect.topLeft(), d, pristine, srcRect);
    const QImage source = fxmanager::readImage(pristine, srcRect);
    if (source.isNull()) return;

    bool rendered = false;
    if (fxmanager::gpuRequested(id().id())) {
        tfm_kuwahara_gpu::Parameters gpu;
        gpu.srcRect = srcRect;
        gpu.outputRect = outputRect;
        gpu.radius = params.radius;
        QImage current = source;
        QString reason, device;
        bool ok = true;
        for (int pass = 0; pass < params.iterations && ok; ++pass) {
            QImage passOutput;
            ok = tfm_kuwahara_gpu::render(current, gpu, passOutput, reason, device);
            if (ok) current = passOutput;
        }
        if (ok) {
            const QImage cropped = current.copy(outputRect.x() - srcRect.x(), outputRect.y() - srcRect.y(),
                                                outputRect.width(), outputRect.height());
            fxmanager::writeImage(d, cropped, outputRect);
            fxmanager::reportBackend(id().id(), QStringLiteral("gpu"), QString(), device);
            if (u) u->setProgress(100);
            return;
        }
        fxmanager::reportBackend(id().id(), QStringLiteral("cpu"), reason);
    } else {
        fxmanager::reportBackend(id().id(), QStringLiteral("cpu"), QStringLiteral("CPU selected"));
    }
    Q_UNUSED(rendered);

    QImage current = source.copy();
    for (int pass = 0; pass < params.iterations; ++pass) {
        QImage next(current.size(), QImage::Format_ARGB32);
        runCpuPass(next, current, params);
        current = next;
    }
    const QImage cropped = current.copy(outputRect.x() - srcRect.x(), outputRect.y() - srcRect.y(),
                                        outputRect.width(), outputRect.height());
    fxmanager::writeImage(d, cropped, outputRect);
    if (u) u->setProgress(100);
}
