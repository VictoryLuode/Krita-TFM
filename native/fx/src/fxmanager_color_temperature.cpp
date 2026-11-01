#include "fxmanager_color_temperature.h"
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

constexpr double kReferenceKelvin = 6500.0;

struct Rgb { double r = 0.0, g = 0.0, b = 0.0; };

// Tanner Helland's black-body approximation, normalised to 0..1. This must stay
// numerically identical to the kelvin() helper in shaders/pointwise.comp.
Rgb kelvin(double kelvinValue)
{
    const double t = std::clamp(kelvinValue, 1000.0, 40000.0) / 100.0;
    double rr, gg, bb;
    if (t <= 66.0) {
        rr = 255.0;
        gg = 99.4708025861 * std::log(t) - 161.1195681661;
        bb = t <= 19.0 ? 0.0 : 138.5177312231 * std::log(t - 10.0) - 305.0447927307;
    } else {
        rr = 329.698727446 * std::pow(t - 60.0, -0.1332047592);
        gg = 288.1221695283 * std::pow(t - 60.0, -0.0755148492);
        bb = 255.0;
    }
    return {std::clamp(rr / 255.0, 0.0, 1.0), std::clamp(gg / 255.0, 0.0, 1.0), std::clamp(bb / 255.0, 0.0, 1.0)};
}

void applyBand(QImage &image, int y0, int y1, double temperature, double tint, double blend, bool preserve)
{
    const Rgb target = kelvin(temperature);
    const Rgb reference = kelvin(kReferenceKelvin);
    const double gainR = target.r / std::max(1e-4, reference.r);
    const double gainG = (target.g / std::max(1e-4, reference.g)) * (1.0 + tint * 0.2);
    const double gainB = target.b / std::max(1e-4, reference.b);
    for (int y = y0; y < y1; ++y) {
        QRgb *row = reinterpret_cast<QRgb *>(image.scanLine(y));
        for (int x = 0; x < image.width(); ++x) {
            const QRgb pixel = row[x];
            const double r = qRed(pixel) / 255.0;
            const double g = qGreen(pixel) / 255.0;
            const double b = qBlue(pixel) / 255.0;
            double outR = r * gainR;
            double outG = g * gainG;
            double outB = b * gainB;
            if (preserve) {
                const double before = 0.2126 * r + 0.7152 * g + 0.0722 * b;
                const double after = 0.2126 * outR + 0.7152 * outG + 0.0722 * outB;
                if (after > 1e-5) {
                    const double scale = before / after;
                    outR *= scale; outG *= scale; outB *= scale;
                }
            }
            outR = std::clamp(r + (outR - r) * blend, 0.0, 1.0);
            outG = std::clamp(g + (outG - g) * blend, 0.0, 1.0);
            outB = std::clamp(b + (outB - b) * blend, 0.0, 1.0);
            row[x] = qRgba(int(std::lround(outR * 255.0)), int(std::lround(outG * 255.0)),
                           int(std::lround(outB * 255.0)), qAlpha(pixel));
        }
    }
}

} // namespace

KisFilterColorTemperature::KisFilterColorTemperature()
    : KisFilter(id(), FiltersCategoryArtisticId, i18n("&Color Temperature..."))
{
    setSupportsAdjustmentLayers(true);
    setColorSpaceIndependence(FULLY_INDEPENDENT);
}

KisFilterConfigurationSP KisFilterColorTemperature::defaultConfiguration(KisResourcesInterfaceSP r) const
{
    auto c = factoryConfiguration(r);
    c->setProperty("temperature", kReferenceKelvin);
    c->setProperty("tint", 0.0);
    c->setProperty("blend", 1.0);
    c->setProperty("preserve_luminance", 1.0);
    fxmanager::applyFilterDefaults(id().id(), c);
    return c;
}

KisConfigWidget *KisFilterColorTemperature::createConfigurationWidget(QWidget *p, const KisPaintDeviceSP, bool) const
{
    return new FxManagerFilterWidget(id().id(), {
        {"temperature", i18n("Temperature (K)"), 2000.0, 12000.0, kReferenceKelvin, 50.0, 0},
        {"tint", i18n("Tint (green/magenta)"), -100.0, 100.0, 0.0, 1.0, 0},
        {"blend", i18n("Blend"), 0.0, 1.0, 1.0, 0.01, 2},
        {"preserve_luminance", i18n("Preserve Luminance"), 0.0, 1.0, 1.0, 1.0, 0},
    }, p);
}

void KisFilterColorTemperature::processImpl(KisPaintDeviceSP d, const QRect &r,
                                            const KisFilterConfigurationSP c, KoUpdater *u) const
{
    if (r.isEmpty() || !d) return;
    const double temperature = std::clamp(c ? c->getDouble("temperature", kReferenceKelvin) : kReferenceKelvin, 2000.0, 12000.0);
    const double tint = std::clamp(c ? c->getDouble("tint", 0.0) : 0.0, -100.0, 100.0);
    const double blend = std::clamp(c ? c->getDouble("blend", 1.0) : 1.0, 0.0, 1.0);
    const bool preserve = (c ? c->getDouble("preserve_luminance", 1.0) : 1.0) > 0.5;

    const QImage source = fxmanager::readImage(d, r);
    if (source.isNull()) return;
    if (fxmanager::gpuRequested()) {
        tfm_pointwise_gpu::Parameters gpu;
        gpu.operation = tfm_pointwise_gpu::Operation::ColorTemperature;
        gpu.outputRect = r;
        gpu.p0 = float(temperature);
        gpu.p1 = float(tint);
        gpu.p2 = float(blend);
        gpu.p3 = preserve ? 1.0f : 0.0f;
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
    fxmanager::parallelRows(output.height(), [&](int y0, int y1) {
        applyBand(output, y0, y1, temperature, tint, blend, preserve);
    });
    fxmanager::writeImage(d, output, r);
    if (u) u->setProgress(100);
}
