#include "fxmanager_halation.h"
#include "fxmanager_filter_widget.h"
#include "fxmanager_processing.h"
#include "tfm_halation_gpu.h"

#include <algorithm>
#include <cmath>
#include <QImage>
#include <QString>
#include <filter/kis_filter_category_ids.h>
#include <filter/kis_filter_configuration.h>
#include <kis_paint_device.h>
#include <kis_painter.h>
#include <KisGlobalResourcesInterface.h>
#include <KoUpdater.h>
#include <klocalizedstring.h>

namespace {

struct HalationParams {
    double threshold = 0.75;
    double radius = 24.0;
    double intensity = 1.0;
    double tintShift = 1.0;
    double blend = 1.0;
    int samples = 32;
    double colorR = 1.0;
    double colorG = 0.42;
    double colorB = 0.22;
    bool channelR = true;
    bool channelG = true;
    bool channelB = true;
    bool channelMode = false;  // true = R/G/B switches, false = glow colour
};

// Colour is stored as "#rrggbb" so it round-trips through KisPropertiesConfiguration.
void parseGlowColor(const QString &text, double *r, double *g, double *b)
{
    *r = 1.0; *g = 0.42; *b = 0.22;
    if (!text.startsWith(QLatin1Char('#')) || text.size() != 7) return;
    bool ok = true;
    const int value = text.midRef(1).toInt(&ok, 16);
    if (!ok) return;
    *r = double((value >> 16) & 0xff) / 255.0;
    *g = double((value >> 8) & 0xff) / 255.0;
    *b = double(value & 0xff) / 255.0;
}

inline QRgb clampedPixel(const QImage &image, int x, int y)
{
    return reinterpret_cast<const QRgb *>(image.constScanLine(std::clamp(y, 0, image.height() - 1)))[std::clamp(x, 0, image.width() - 1)];
}

// Mirrors halation() in shaders/halation.comp: gather highlight energy over a
// golden-angle spiral so one pass covers a large radius without a pyramid.
void halationBand(QImage &output, const QImage &source, int y0, int y1, const HalationParams &p)
{
    const int samples = std::clamp(p.samples, 8, 64);
    const double radius = std::max(0.0, p.radius);
    for (int y = y0; y < y1; ++y) {
        QRgb *row = reinterpret_cast<QRgb *>(output.scanLine(y));
        for (int x = 0; x < output.width(); ++x) {
            const QRgb centre = clampedPixel(source, x, y);
            double glowR = 0.0, glowG = 0.0, glowB = 0.0, weightSum = 0.0;
            for (int i = 0; i < samples; ++i) {
                const double t = double(i) + 0.5;
                const double angle = t * 2.39996323;
                const double distance = std::sqrt(t / double(samples)) * radius;
                const int ox = int(std::cos(angle) * distance);
                const int oy = int(std::sin(angle) * distance);
                const QRgb s = clampedPixel(source, x + ox, y + oy);
                const double luminance = (0.2126 * qRed(s) + 0.7152 * qGreen(s) + 0.0722 * qBlue(s)) / 255.0;
                const double energy = std::max(0.0, luminance - p.threshold);
                glowR += qRed(s) * energy;
                glowG += qGreen(s) * energy;
                glowB += qBlue(s) * energy;
                weightSum += energy;
            }
            if (weightSum <= 0.0) { row[x] = centre; continue; }
            const double inv = 1.0 / double(samples);
            glowR *= inv; glowG *= inv; glowB *= inv;
            const double tint = std::clamp(p.tintShift, 0.0, 1.0);
            const double gain = std::clamp(p.intensity, 0.0, 4.0);
            double tintedR, tintedG, tintedB;
            if (p.channelMode) {
                // Channel mode: the user picks which channels glow; the colour
                // picker is ignored so both controls never fight each other.
                tintedR = glowR * (p.channelR ? 1.0 : 0.0);
                tintedG = glowG * (p.channelG ? 1.0 : 0.0);
                tintedB = glowB * (p.channelB ? 1.0 : 0.0);
            } else {
                tintedR = glowR + (glowR * p.colorR - glowR) * tint;
                tintedG = glowG + (glowG * p.colorG - glowG) * tint;
                tintedB = glowB + (glowB * p.colorB - glowB) * tint;
            }
            tintedR *= gain; tintedG *= gain; tintedB *= gain;
            auto screen = [](double base, double glow) {
                return std::clamp(255.0 - (255.0 - base) * (255.0 - glow) / 255.0, 0.0, 255.0);
            };
            const double blend = std::clamp(p.blend, 0.0, 1.0);
            auto mixChannel = [&](double base, double glow) {
                return std::clamp(base + (screen(base, glow) - base) * blend, 0.0, 255.0);
            };
            row[x] = qRgba(int(std::lround(mixChannel(qRed(centre), tintedR))),
                           int(std::lround(mixChannel(qGreen(centre), tintedG))),
                           int(std::lround(mixChannel(qBlue(centre), tintedB))),
                           qAlpha(centre));
        }
    }
}

} // namespace

KisFilterHalation::KisFilterHalation()
    : KisFilter(id(), FiltersCategoryArtisticId, i18n("&Halation..."))
{
    setSupportsAdjustmentLayers(true);
    setColorSpaceIndependence(FULLY_INDEPENDENT);
    // The highlight gather reads a disc far wider than one patch, so Krita's
    // patch threading would clamp every patch to its own neighbourhood.
    setSupportsThreading(false);
}

KisFilterConfigurationSP KisFilterHalation::defaultConfiguration(KisResourcesInterfaceSP r) const
{
    auto c = factoryConfiguration(r);
    c->setProperty("threshold", 0.75);
    c->setProperty("radius", 24.0);
    c->setProperty("intensity", 1.0);
    c->setProperty("tint", 1.0);
    c->setProperty("blend", 1.0);
    c->setProperty("quality", 32.0);
    c->setProperty("glow_color", QStringLiteral("#ff6b38"));
    c->setProperty("channel_r", true);
    c->setProperty("channel_g", true);
    c->setProperty("channel_b", true);
    c->setProperty("glow_mode", QStringLiteral("color"));
    fxmanager::applyFilterDefaults(id().id(), c);
    return c;
}

KisConfigWidget *KisFilterHalation::createConfigurationWidget(QWidget *p, const KisPaintDeviceSP, bool) const
{
    return new FxManagerFilterWidget(id().id(), {
        {"threshold", i18n("Threshold"), 0.0, 1.0, 0.75, 0.01, 2},
        {"radius", i18n("Radius"), 1.0, 200.0, 24.0, 1.0, 0},
        {"intensity", i18n("Intensity"), 0.0, 4.0, 1.0, 0.05, 2},
        {"tint", i18n("Tint"), 0.0, 1.0, 1.0, 0.01, 2},
        {"blend", i18n("Blend"), 0.0, 1.0, 1.0, 0.01, 2},
        {"quality", i18n("Quality"), 8.0, 64.0, 32.0, 8.0, 0},
    }, p, false,
    {
        {"glow_mode", i18n("Mode"), {{"color", i18n("Custom Color")}, {"channels", i18n("Channel Mix")}}, "color"},
    },
    {
        {"channel_r", i18n("Red channel"), true},
        {"channel_g", i18n("Green channel"), true},
        {"channel_b", i18n("Blue channel"), true},
    },
    {
        {"glow_color", i18n("Glow Color"), QStringLiteral("#ff6b38")},
    });
}

QRect KisFilterHalation::neededRect(const QRect &rect, const KisFilterConfigurationSP c, int) const
{
    const int halo = int(std::ceil(std::clamp(c ? c->getDouble("radius", 24.0) : 24.0, 1.0, 200.0)));
    return rect.adjusted(-halo, -halo, halo, halo);
}

QRect KisFilterHalation::changedRect(const QRect &rect, const KisFilterConfigurationSP c, int lod) const
{
    return neededRect(rect, c, lod);
}

void KisFilterHalation::processImpl(KisPaintDeviceSP d, const QRect &r,
                                    const KisFilterConfigurationSP c, KoUpdater *u) const
{
    if (r.isEmpty() || !d) return;
    HalationParams params;
    params.threshold = std::clamp(c ? c->getDouble("threshold", 0.75) : 0.75, 0.0, 1.0);
    params.radius = std::clamp(c ? c->getDouble("radius", 24.0) : 24.0, 1.0, 200.0);
    params.intensity = std::clamp(c ? c->getDouble("intensity", 1.0) : 1.0, 0.0, 4.0);
    params.tintShift = std::clamp(c ? c->getDouble("tint", 1.0) : 1.0, 0.0, 1.0);
    params.blend = std::clamp(c ? c->getDouble("blend", 1.0) : 1.0, 0.0, 1.0);
    params.samples = int(std::clamp(c ? c->getDouble("quality", 32.0) : 32.0, 8.0, 64.0));
    parseGlowColor(c ? c->getString("glow_color", QStringLiteral("#ff6b38")) : QStringLiteral("#ff6b38"),
                   &params.colorR, &params.colorG, &params.colorB);
    params.channelR = !c || c->getBool("channel_r", true);
    params.channelG = !c || c->getBool("channel_g", true);
    params.channelB = !c || c->getBool("channel_b", true);
    params.channelMode = c && c->getString("glow_mode", QStringLiteral("color")) == QLatin1String("channels");

    QRect frame = d->defaultBounds()->bounds();
    if (frame.isEmpty()) frame = d->extent();
    if (frame.isEmpty()) frame = r;
    const QRect outputRect = r.intersected(frame);
    if (outputRect.isEmpty()) return;

    const int halo = int(std::ceil(params.radius));
    const QRect srcRect = outputRect.adjusted(-halo, -halo, halo, halo).intersected(frame);
    // Later regions would otherwise gather the glow an earlier region already
    // wrote back into this device. Read the transaction baseline patch instead.
    KisPaintDeviceSP pristine = new KisPaintDevice(d->colorSpace());
    pristine->prepareClone(d);
    KisPainter::copyAreaOptimizedOldData(srcRect.topLeft(), d, pristine, srcRect);
    const QImage source = fxmanager::readImage(pristine, srcRect);
    if (source.isNull()) return;

    if (fxmanager::gpuRequested()) {
        tfm_halation_gpu::Parameters gpu;
        gpu.srcRect = srcRect;
        gpu.outputRect = outputRect;
        gpu.threshold = float(params.threshold);
        gpu.radius = float(params.radius);
        gpu.intensity = float(params.intensity);
        gpu.tintShift = float(params.tintShift);
        gpu.blend = float(params.blend);
        gpu.samples = params.samples;
        gpu.colorR = float(params.colorR);
        gpu.colorG = float(params.colorG);
        gpu.colorB = float(params.colorB);
        gpu.channelR = params.channelR;
        gpu.channelG = params.channelG;
        gpu.channelB = params.channelB;
        gpu.mode = params.channelMode ? 1 : 0;
        QImage gpuOutput;
        QString reason, device;
        if (tfm_halation_gpu::render(source, gpu, gpuOutput, reason, device)) {
            const QImage cropped = gpuOutput.copy(outputRect.x() - srcRect.x(), outputRect.y() - srcRect.y(),
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

    QImage current(source.size(), QImage::Format_ARGB32);
    fxmanager::parallelRows(current.height(), [&](int y0, int y1) { halationBand(current, source, y0, y1, params); });
    const QImage cropped = current.copy(outputRect.x() - srcRect.x(), outputRect.y() - srcRect.y(),
                                        outputRect.width(), outputRect.height());
    fxmanager::writeImage(d, cropped, outputRect);
    if (u) u->setProgress(100);
}
