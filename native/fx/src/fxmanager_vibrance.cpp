#include "fxmanager_vibrance.h"
#include "fxmanager_filter_widget.h"
#include "fxmanager_processing.h"
#include "tfm_pointwise_gpu.h"

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

double smoothRange(double e0, double e1, double x)
{
    if (e1 <= e0) return x < e0 ? 0.0 : 1.0;
    const double t = std::clamp((x - e0) / (e1 - e0), 0.0, 1.0);
    return t * t * (3.0 - 2.0 * t);
}

double hueDistance(double a, double b)
{
    const double d = std::abs(a - b);
    return std::min(d, 1.0 - d);
}

// Hue of an RGB triple in 0..1, matching hsv() in shaders/pointwise.comp.
double hueOf(double r, double g, double b)
{
    const double mx = std::max(r, std::max(g, b));
    const double mn = std::min(r, std::min(g, b));
    const double d = mx - mn;
    if (d <= 0.0) return 0.0;
    double h = 0.0;
    if (mx == r) h = std::fmod((g - b) / d, 6.0);
    else if (mx == g) h = (b - r) / d + 2.0;
    else h = (r - g) / d + 4.0;
    h /= 6.0;
    if (h < 0.0) h += 1.0;
    return h;
}

struct VibranceParams { double vibrance, saturation, skin, protect, blend; };

void applyBand(QImage &image, int y0, int y1, const VibranceParams &p)
{
    for (int y = y0; y < y1; ++y) {
        QRgb *row = reinterpret_cast<QRgb *>(image.scanLine(y));
        for (int x = 0; x < image.width(); ++x) {
            const QRgb pixel = row[x];
            const double r = qRed(pixel) / 255.0;
            const double g = qGreen(pixel) / 255.0;
            const double b = qBlue(pixel) / 255.0;
            const double mx = std::max(r, std::max(g, b));
            const double mn = std::min(r, std::min(g, b));
            const double chroma = mx - mn;
            const double lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
            double amount = p.vibrance * (1.0 - chroma);
            if (p.skin > 0.0 && chroma > 0.0) {
                const double skinMask = smoothRange(0.18, 0.05, hueDistance(hueOf(r, g, b), 0.07))
                                      * smoothRange(0.04, 0.20, chroma);
                const double scale = 1.0 + (0.15 - 1.0) * skinMask * p.skin;
                amount *= scale;
            }
            if (p.protect > 0.0) {
                const double keep = 1.0 + (0.0 - 1.0) * smoothRange(0.70, 1.0, lum) * p.protect;
                amount *= keep;
            }
            const double gain = std::max(0.0, 1.0 + amount + p.saturation);
            auto mixChannel = [&](double value) {
                const double out = lum + (value - lum) * gain;
                return std::clamp(value + (out - value) * p.blend, 0.0, 1.0);
            };
            row[x] = qRgba(int(std::lround(mixChannel(r) * 255.0)), int(std::lround(mixChannel(g) * 255.0)),
                           int(std::lround(mixChannel(b) * 255.0)), qAlpha(pixel));
        }
    }
}

} // namespace

KisFilterVibrance::KisFilterVibrance()
    : KisFilter(id(), FiltersCategoryArtisticId, i18n("&Vibrance..."))
{
    setSupportsAdjustmentLayers(true);
    setColorSpaceIndependence(FULLY_INDEPENDENT);
}

KisFilterConfigurationSP KisFilterVibrance::defaultConfiguration(KisResourcesInterfaceSP r) const
{
    auto c = factoryConfiguration(r);
    c->setProperty("vibrance", 30.0);
    c->setProperty("saturation", 0.0);
    c->setProperty("skin_protect", 1.0);
    c->setProperty("protect_highlights", 0.5);
    c->setProperty("blend", 1.0);
    fxmanager::applyFilterDefaults(id().id(), c);
    return c;
}

KisConfigWidget *KisFilterVibrance::createConfigurationWidget(QWidget *p, const KisPaintDeviceSP, bool) const
{
    return new FxManagerFilterWidget(id().id(), {
        {"vibrance", i18n("Vibrance"), -100.0, 100.0, 30.0, 1.0, 0},
        {"saturation", i18n("Saturation"), -100.0, 100.0, 0.0, 1.0, 0},
        {"skin_protect", i18n("Skin Protection"), 0.0, 1.0, 1.0, 0.01, 2},
        {"protect_highlights", i18n("Protect Highlights"), 0.0, 1.0, 0.5, 0.01, 2},
        {"blend", i18n("Blend"), 0.0, 1.0, 1.0, 0.01, 2},
    }, p);
}

void KisFilterVibrance::processImpl(KisPaintDeviceSP d, const QRect &r,
                                    const KisFilterConfigurationSP c, KoUpdater *u) const
{
    if (r.isEmpty() || !d) return;
    VibranceParams params;
    params.vibrance = std::clamp(c ? c->getDouble("vibrance", 30.0) : 30.0, -100.0, 100.0) / 100.0;
    params.saturation = std::clamp(c ? c->getDouble("saturation", 0.0) : 0.0, -100.0, 100.0) / 100.0;
    params.skin = std::clamp(c ? c->getDouble("skin_protect", 1.0) : 1.0, 0.0, 1.0);
    params.protect = std::clamp(c ? c->getDouble("protect_highlights", 0.5) : 0.5, 0.0, 1.0);
    params.blend = std::clamp(c ? c->getDouble("blend", 1.0) : 1.0, 0.0, 1.0);

    const QImage source = fxmanager::readImage(d, r);
    if (source.isNull()) return;
    if (fxmanager::gpuRequested(id().id())) {
        tfm_pointwise_gpu::Parameters gpu;
        gpu.operation = tfm_pointwise_gpu::Operation::Vibrance;
        gpu.outputRect = r;
        gpu.p0 = float(params.vibrance * 100.0);
        gpu.p1 = float(params.saturation * 100.0);
        gpu.p2 = float(params.skin);
        gpu.p3 = float(params.protect);
        gpu.p4 = float(params.blend);
        QImage output; QString reason, device;
        if (tfm_pointwise_gpu::render(source, gpu, output, reason, device)) {
            fxmanager::writeImage(d, output, r);
            fxmanager::reportBackend(id().id(), QStringLiteral("gpu"), QString(), device);
            if (u) u->setProgress(100);
            return;
        }
        fxmanager::reportBackend(id().id(), QStringLiteral("cpu"), reason);
    } else {
        fxmanager::reportBackend(id().id(), QStringLiteral("cpu"), QStringLiteral("CPU selected"));
    }

    QImage output = source.copy();
    fxmanager::parallelRows(output.height(), [&](int y0, int y1) { applyBand(output, y0, y1, params); });
    fxmanager::writeImage(d, output, r);
    if (u) u->setProgress(100);
}
