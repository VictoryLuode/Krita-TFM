#include "fxmanager_lens_distortion.h"
#include "fxmanager_lens_distortion_widget.h"
#include "fxmanager_processing.h"
#include "tfm_lens_gpu.h"

#include <algorithm>
#include <cmath>
#include <QImage>
#include <filter/kis_filter_category_ids.h>
#include <filter/kis_filter_configuration.h>
#include <kis_paint_device.h>
#include <KisGlobalResourcesInterface.h>
#include <KoUpdater.h>
#include <klocalizedstring.h>

namespace {

constexpr double kMinimumDistortion = -0.999;
constexpr double kHorizontalDispersionScale = 5.0;
constexpr double kRadialDispersionScale = 4.0;
constexpr double kDistortionScale = 4.0;

QRgb sampleBilinear(const QImage &image, double x, double y)
{
    const int width = image.width();
    const int height = image.height();
    if (width <= 0 || height <= 0) {
        return qRgba(0, 0, 0, 0);
    }
    const double maxX = double(width - 1);
    const double maxY = double(height - 1);
    if (x < -0.5 || y < -0.5 || x > maxX + 0.5 || y > maxY + 0.5) {
        return qRgba(0, 0, 0, 0);
    }
    const double sx = std::clamp(x, 0.0, maxX);
    const double sy = std::clamp(y, 0.0, maxY);
    const int x0 = int(std::floor(sx));
    const int y0 = int(std::floor(sy));
    const int x1 = std::min(x0 + 1, image.width() - 1);
    const int y1 = std::min(y0 + 1, image.height() - 1);
    const double fx = sx - x0;
    const double fy = sy - y0;
    const QRgb *row0 = reinterpret_cast<const QRgb *>(image.constScanLine(y0));
    const QRgb *row1 = reinterpret_cast<const QRgb *>(image.constScanLine(y1));
    const QRgb a = row0[x0];
    const QRgb b = row0[x1];
    const QRgb c = row1[x0];
    const QRgb d = row1[x1];
    auto mix = [&](int channel) {
        auto component = [channel](QRgb pixel) {
            switch (channel) {
            case 0: return qRed(pixel);
            case 1: return qGreen(pixel);
            case 2: return qBlue(pixel);
            default: return qAlpha(pixel);
            }
        };
        const double top = (1.0 - fx) * component(a) + fx * component(b);
        const double bottom = (1.0 - fx) * component(c) + fx * component(d);
        return int(std::lround((1.0 - fy) * top + fy * bottom));
    };
    return qRgba(mix(0), mix(1), mix(2), mix(3));
}
}

KisFilterLensDistortion::KisFilterLensDistortion()
    : KisFilter(id(), FiltersCategoryArtisticId, i18n("&Lens Distortion..."))
{
    setSupportsAdjustmentLayers(true);
    setColorSpaceIndependence(FULLY_INDEPENDENT);
    // A radial mapper samples arbitrary pixels from the whole image. Processing
    // isolated Krita patches would create one lens per patch (a tiled result).
    setSupportsThreading(false);
}
KisFilterConfigurationSP KisFilterLensDistortion::defaultConfiguration(KisResourcesInterfaceSP r) const
{
    auto configuration = factoryConfiguration(r);
    configuration->setProperty("mode", "radial");
    configuration->setProperty("distortion", 0.0);
    configuration->setProperty("dispersion", 0.0);
    configuration->setProperty("jitter", false);
    configuration->setProperty("fit", false);
    fxmanager::applyFilterDefaults(id().id(), configuration); return configuration;
}
KisConfigWidget *KisFilterLensDistortion::createConfigurationWidget(QWidget *parent,
                                                                     const KisPaintDeviceSP,
                                                                     bool) const
{
    return new LensDistortionConfigurationWidget(id().id(), parent);
}

bool KisFilterLensDistortion::needsTransparentPixels(const KisFilterConfigurationSP, const KoColorSpace *) const
{
    return true;
}

QRect KisFilterLensDistortion::neededRect(const QRect &rect,
                                          const KisFilterConfigurationSP,
                                          int) const
{
    // Lens Distortion samples outside the output patch. Request a bounded
    // halo around it so patch edges do not become transparent seams, while
    // avoiding the unbounded rectangle that can explode group projections.
    const int marginX = std::max(1, rect.width());
    const int marginY = std::max(1, rect.height());
    return rect.adjusted(-marginX, -marginY, marginX, marginY);
}

void KisFilterLensDistortion::processImpl(KisPaintDeviceSP device,
                                          const QRect &rect,
                                          const KisFilterConfigurationSP configuration,
                                          KoUpdater *updater) const
{
    if (rect.isEmpty() || !device) return;

    const QString mode = configuration ? configuration->getString("mode", "radial") : QStringLiteral("radial");
    const double distortion = std::clamp(
        configuration ? configuration->getDouble("distortion", 0.0) : 0.0,
        kMinimumDistortion,
        1.0);
    const double dispersion = std::clamp(
        configuration ? configuration->getDouble("dispersion", 0.0) : 0.0,
        0.0,
        1.0);
    const bool horizontal = mode == QStringLiteral("horizontal");
    const bool fit = configuration && configuration->getBool("fit", false);
    const bool jitter = configuration && configuration->getBool("jitter", false);
    if ((!horizontal && std::abs(distortion) < 1e-9 && dispersion < 1e-9)
        || (horizontal && dispersion < 1e-9)) return;

    QRect frame = device->defaultBounds()->bounds();
    if (frame.isEmpty()) frame = device->extent();
    if (frame.isEmpty()) frame = rect;
    const QRect outputRect = rect.intersected(frame);
    if (outputRect.isEmpty()) return;

    const QImage source = fxmanager::readImage(device, frame);
    if (source.isNull()) return;
    if (fxmanager::gpuRequested()) {
        QImage gpuOutput;
        QString reason;
        QString gpuDevice;
        if (tfm_lens_gpu::render(source, frame, outputRect, horizontal, distortion,
                                 dispersion, fit, jitter, gpuOutput, reason, gpuDevice)) {
            fxmanager::writeImage(device, gpuOutput, outputRect);
            fxmanager::reportBackend(id().id(), QStringLiteral("gpu"), QString(), gpuDevice);
            if (updater) updater->setProgress(100);
            return;
        }
        fxmanager::reportBackend(id().id(), QStringLiteral("cpu"), reason);
    } else {
        fxmanager::reportBackend(id().id(), QStringLiteral("cpu"), QStringLiteral("CPU selected"));
    }
    QImage output(outputRect.size(), QImage::Format_ARGB32);

    const double width = frame.width();
    const double height = frame.height();
    const double centerX = width * 0.5;
    const double centerY = height * 0.5;

    // Blender: green keeps the requested distortion, red/blue get +-dispersion/4,
    // and all three are multiplied by DISTORTION_SCALE.
    const double radialDispersion = dispersion / kRadialDispersionScale;
    const double redInput = std::clamp(distortion + radialDispersion, kMinimumDistortion, 1.0);
    const double blueInput = std::clamp(distortion - radialDispersion, kMinimumDistortion, 1.0);
    const double chromatic[3] = {
        redInput * kDistortionScale,
        distortion * kDistortionScale,
        blueInput * kDistortionScale
    };
    // compute_scale()
    const double maximumDistortion = std::max({redInput, distortion, blueInput});
    const double scale = (fit && maximumDistortion > 0.0)
        ? 1.0 / (1.0 + 2.0 * maximumDistortion)
        : 1.0 / (1.0 + maximumDistortion);
    const double horizontalDispersion = dispersion * kHorizontalDispersionScale / std::max(1.0, width);

    // Krita may already render this Filter Layer in tiles; keep the row loop
    // local to the requested rect and write only that rect back. Rows are
    // independent (source is read-only, each worker owns whole output rows),
    // so the band pass can run in parallel without touching host tiling.
    fxmanager::parallelRows(output.height(), [&](int y0, int y1) {
    for (int y = y0; y < y1; ++y) {
        QRgb *row = reinterpret_cast<QRgb *>(output.scanLine(y));
        const double imageY = outputRect.y() - frame.y() + y + 0.5;
        for (int x = 0; x < output.width(); ++x) {
            const double imageX = outputRect.x() - frame.x() + x + 0.5;

            if (horizontal) {
                // execute_horizontal_distortion_cpu(): normalized sample offsets.
                const double normalizedX = imageX / width;
                const double normalizedY = imageY / height;
                const QRgb red = sampleBilinear(source, (normalizedX + horizontalDispersion) * width - 0.5, imageY - 0.5);
                const QRgb green = sampleBilinear(source, imageX - 0.5, imageY - 0.5);
                const QRgb blue = sampleBilinear(source, (normalizedX - horizontalDispersion) * width - 0.5, imageY - 0.5);
                const int alpha = int(std::lround((qAlpha(red) + qAlpha(green) + qAlpha(blue)) / 3.0));
                Q_UNUSED(normalizedY);
                row[x] = qRgba(qRed(red), qGreen(green), qBlue(blue), alpha);
                continue;
            }

            // radial_lens_distortion(): centred normalized UV, per-axis centre.
            const double uvx = scale * (imageX - centerX) / centerX;
            const double uvy = scale * (imageY - centerY) / centerY;
            const double distanceSquared = uvx * uvx + uvy * uvy;

            if (chromatic[0] * distanceSquared > 1.0
                || chromatic[1] * distanceSquared > 1.0
                || chromatic[2] * distanceSquared > 1.0) {
                row[x] = qRgba(0, 0, 0, 0);
                continue;
            }

            auto distortionScale = [distanceSquared](double value) {
                return 1.0 / (1.0 + std::sqrt(std::max(0.0, 1.0 - value * distanceSquared)));
            };

            const double redScale = distortionScale(chromatic[0]);
            const double greenScale = distortionScale(chromatic[1]);
            const double blueScale = distortionScale(chromatic[2]);
            const double redX = (uvx * redScale + 0.5) * width;
            const double redY = (uvy * redScale + 0.5) * height;
            const double greenX = (uvx * greenScale + 0.5) * width;
            const double greenY = (uvy * greenScale + 0.5) * height;
            const double blueX = (uvx * blueScale + 0.5) * width;
            const double blueY = (uvy * blueScale + 0.5) * height;

            auto stepsFor = [jitter](double amount, int seed) {
                if (jitter) {
                    return amount < 4.0 ? 2 : int(std::sqrt(amount + 1.0));
                }
                Q_UNUSED(seed);
                return int(amount + 1.0);
            };
            const int stepsRed = std::max(1, stepsFor(std::hypot(redX - greenX, redY - greenY), 0));
            const int stepsBlue = std::max(1, stepsFor(std::hypot(greenX - blueX, greenY - blueY), 1));
            const int stepsGreen = stepsRed + stepsBlue;

            double accumulated[4] = {0.0, 0.0, 0.0, 0.0};
            auto integrate = [&](int start, int end, int steps) {
                const double amount = chromatic[end] - chromatic[start];
                for (int i = 0; i < steps; ++i) {
                    const double increment = (i + (jitter
                        ? (fxmanager::deterministicNoise(x, y, start * steps + i, 71) + 1.0) * 0.5
                        : 0.5)) / steps;
                    const double value = chromatic[start] + increment * amount;
                    const double channelScale = 1.0 / (1.0 + std::sqrt(std::max(0.0, 1.0 - value * distanceSquared)));
                    const double sampleX = (uvx * channelScale + 0.5) * width - 0.5;
                    const double sampleY = (uvy * channelScale + 0.5) * height - 0.5;
                    const QRgb pixel = sampleBilinear(source, sampleX, sampleY);
                    const int startValue = start == 0 ? qRed(pixel) : qGreen(pixel);
                    const int endValue = end == 1 ? qGreen(pixel) : qBlue(pixel);
                    accumulated[start] += (1.0 - increment) * startValue;
                    accumulated[end] += increment * endValue;
                    accumulated[3] += qAlpha(pixel);
                }
            };
            integrate(0, 1, stepsRed);
            integrate(1, 2, stepsBlue);

            accumulated[0] *= 2.0 / stepsRed;
            accumulated[1] *= 2.0 / stepsGreen;
            accumulated[2] *= 2.0 / stepsBlue;
            accumulated[3] /= stepsGreen;
            row[x] = qRgba(std::clamp(int(std::lround(accumulated[0])), 0, 255),
                           std::clamp(int(std::lround(accumulated[1])), 0, 255),
                           std::clamp(int(std::lround(accumulated[2])), 0, 255),
                           std::clamp(int(std::lround(accumulated[3])), 0, 255));
        }
    }
    });

    fxmanager::writeImage(device, output, outputRect);
    if (updater) updater->setProgress(100);
}
