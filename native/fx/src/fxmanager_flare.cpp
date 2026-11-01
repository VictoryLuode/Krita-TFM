#include "fxmanager_flare.h"
#include "fxmanager_filter_widget.h"
#include "fxmanager_processing.h"
#include "tfm_flare_gpu.h"

#include <algorithm>
#include <cmath>
#include <QImage>
#include <QVector>
#include <filter/kis_filter_category_ids.h>
#include <filter/kis_filter_configuration.h>
#include <kis_paint_device.h>
#include <kis_painter.h>
#include <KisGlobalResourcesInterface.h>
#include <KoUpdater.h>
#include <klocalizedstring.h>

namespace {

// Every helper below mirrors the matching function in shaders/flare.comp so the
// CPU fallback and the Vulkan path produce the same image.

double ramp(double lowEdge, double highEdge, double x)
{
    const double t = std::clamp((x - lowEdge) / std::max(highEdge - lowEdge, 1e-6), 0.0, 1.0);
    return t * t * (3.0 - 2.0 * t);
}

struct Rgb { double r, g, b; };

Rgb dispersion(double t, double tintShift)
{
    t = std::clamp(t, 0.0, 1.0);
    const Rgb warm{1.0, 0.55, 0.25};
    const Rgb cool{0.25, 0.45, 1.0};
    const Rgb tinted{warm.r + (cool.r - warm.r) * t,
                     warm.g + (cool.g - warm.g) * t,
                     warm.b + (cool.b - warm.b) * t};
    const double k = std::clamp(tintShift, 0.0, 1.0);
    // tintShift 0 keeps the glow neutral, 1 applies full dispersion colour.
    return Rgb{1.0 + (tinted.r - 1.0) * k, 1.0 + (tinted.g - 1.0) * k, 1.0 + (tinted.b - 1.0) * k};
}

double luminanceAt(const QImage &image, int x, int y)
{
    const QRgb p = reinterpret_cast<const QRgb *>(image.constScanLine(std::clamp(y, 0, image.height() - 1)))[std::clamp(x, 0, image.width() - 1)];
    return (0.2126 * qRed(p) + 0.7152 * qGreen(p) + 0.0722 * qBlue(p)) / 255.0;
}

struct FlareParams {
    tfm_flare_gpu::Mode mode = tfm_flare_gpu::Mode::GhostFlare;
    double threshold = 0.85;
    double length = 0.35;
    double intensity = 1.0;
    double tintShift = 1.0;
    double decay = 3.0;
    double aspect = 0.02;
    double blend = 1.0;
    int maxSources = 1;
};

Rgb ghostFlare(double u, double v, const QVector<tfm_flare_gpu::FlareSource> &sources, const FlareParams &p)
{
    Rgb acc{0.0, 0.0, 0.0};
    const int count = std::clamp(int(sources.size()), 1, 8);
    const int ghosts = std::clamp(int(p.decay), 1, 6);
    for (int s = 0; s < count; ++s) {
        const tfm_flare_gpu::FlareSource &source = sources[s];
        const double axisX = 0.5 - source.x;
        const double axisY = 0.5 - source.y;
        // Ghosts march along the source->centre axis and out the far side,
        // which is how a real lens reflects a bright point.
        for (int g = 1; g <= ghosts; ++g) {
            const double t = double(g) / double(ghosts);
            const double ghostX = source.x + axisX * (1.0 + t) * 2.0;
            const double ghostY = source.y + axisY * (1.0 + t) * 2.0;
            const double radius = std::max(0.004, double(source.radius) * (0.10 + 0.18 * t));
            const double dx = u - ghostX, dy = v - ghostY;
            const double d = std::sqrt(dx * dx + dy * dy) / radius;
            const double disc = (1.0 - ramp(0.35, 1.0, d)) * (1.0 - t * 0.55);
            const Rgb tint = dispersion(t, p.tintShift);
            acc.r += tint.r * disc * source.strength;
            acc.g += tint.g * disc * source.strength;
            acc.b += tint.b * disc * source.strength;
        }
        // Central halo around the detected light itself.
        const double haloRadius = std::max(0.01, double(source.radius) * 1.6);
        const double hx = u - source.x, hy = v - source.y;
        const double halo = 1.0 - ramp(haloRadius * 0.15, haloRadius, std::sqrt(hx * hx + hy * hy));
        acc.r += 1.0 * halo * source.strength * 0.6;
        acc.g += 0.85 * halo * source.strength * 0.6;
        acc.b += 0.7 * halo * source.strength * 0.6;
    }
    const double k = std::clamp(p.intensity, 0.0, 4.0);
    return Rgb{acc.r * k, acc.g * k, acc.b * k};
}

Rgb anamorphicStreak(double u, double v, const QVector<tfm_flare_gpu::FlareSource> &sources, const FlareParams &p)
{
    Rgb acc{0.0, 0.0, 0.0};
    const int count = std::clamp(int(sources.size()), 1, 8);
    const double aspect = std::max(0.002, p.aspect);
    const double falloff = std::max(0.05, p.decay);
    const double span = std::max(0.001, p.length);
    for (int s = 0; s < count; ++s) {
        const tfm_flare_gpu::FlareSource &source = sources[s];
        const double dx = u - source.x;
        const double dy = v - source.y;
        // Horizontal bar: exponential falloff along x, tight Gaussian along y.
        const double along = std::abs(dx) / span;
        const double across = dy / aspect;
        const double bar = std::exp(-along / falloff) * std::exp(-across * across);
        const Rgb tint = dispersion(std::clamp(along, 0.0, 1.0), p.tintShift);
        acc.r += tint.r * bar * source.strength;
        acc.g += tint.g * bar * source.strength;
        acc.b += tint.b * bar * source.strength;
    }
    const double k = std::clamp(p.intensity, 0.0, 4.0);
    return Rgb{acc.r * k, acc.g * k, acc.b * k};
}

Rgb lightRays(double u, double v, const QImage &image, const QVector<tfm_flare_gpu::FlareSource> &sources, const FlareParams &p)
{
    const tfm_flare_gpu::FlareSource &primary = sources[0];
    const double toX = primary.x - u;
    const double toY = primary.y - v;
    const double distance = std::sqrt(toX * toX + toY * toY);
    if (distance <= 0.0001) return Rgb{0.0, 0.0, 0.0};
    const double dirX = toX / distance, dirY = toY / distance;
    const int taps = 32;
    const double span = std::clamp(p.length, 0.01, 1.0);
    const double falloff = std::max(0.1, p.decay);
    double sum = 0.0;
    for (int i = 0; i < taps; ++i) {
        const double t = double(i) / double(taps);
        const double px = u + dirX * (t * span * distance);
        const double py = v + dirY * (t * span * distance);
        const double luminance = luminanceAt(image, int(px * image.width()), int(py * image.height()));
        sum += std::max(0.0, luminance - p.threshold) * std::exp(-t * falloff);
    }
    sum /= double(taps);
    const double k = std::clamp(p.intensity, 0.0, 4.0) * primary.strength;
    return Rgb{1.0 * sum * k, 0.92 * sum * k, 0.78 * sum * k};
}

void flareBand(QImage &output, const QImage &source, int y0, int y1,
               const QVector<tfm_flare_gpu::FlareSource> &sources, const FlareParams &p)
{
    const int width = output.width();
    const int height = output.height();
    for (int y = y0; y < y1; ++y) {
        QRgb *row = reinterpret_cast<QRgb *>(output.scanLine(y));
        const double v = (double(y) + 0.5) / double(height);
        for (int x = 0; x < width; ++x) {
            const QRgb base = reinterpret_cast<const QRgb *>(source.constScanLine(y))[x];
            const double u = (double(x) + 0.5) / double(width);
            Rgb glow;
            if (p.mode == tfm_flare_gpu::Mode::GhostFlare) glow = ghostFlare(u, v, sources, p);
            else if (p.mode == tfm_flare_gpu::Mode::Anamorphic) glow = anamorphicStreak(u, v, sources, p);
            else glow = lightRays(u, v, source, sources, p);
            auto channel = [&](double baseValue, double glowValue) {
                const double capped = std::clamp(glowValue * 255.0, 0.0, 255.0);
                const double combined = 255.0 - (255.0 - baseValue) * (255.0 - capped) / 255.0;
                return std::clamp(baseValue + (combined - baseValue) * std::clamp(p.blend, 0.0, 1.0), 0.0, 255.0);
            };
            row[x] = qRgba(int(std::lround(channel(qRed(base), glow.r))),
                           int(std::lround(channel(qGreen(base), glow.g))),
                           int(std::lround(channel(qBlue(base), glow.b))),
                           qAlpha(base));
        }
    }
}

// Shared driver: both the CPU and GPU paths need the same detected sources and
// the same whole-frame source region, so they cannot drift apart.
void runFlare(KisPaintDeviceSP d, const QRect &r,
              const KisFilterConfigurationSP c, KoUpdater *u,
              const FlareParams &requested, const QString &id)
{
    if (r.isEmpty() || !d) return;
    QRect frame = d->defaultBounds()->bounds();
    if (frame.isEmpty()) frame = d->extent();
    if (frame.isEmpty()) frame = r;
    const QRect outputRect = r.intersected(frame);
    if (outputRect.isEmpty()) return;
    const QRect srcRect = frame;
    // Filter layers call processImpl once per region and write each result back
    // into d, so later regions would otherwise detect the flare already drawn by
    // earlier ones and grow extra streaks. Read the transaction baseline instead.
    KisPaintDeviceSP pristine = new KisPaintDevice(d->colorSpace());
    pristine->prepareClone(d);
    KisPainter::copyAreaOptimizedOldData(srcRect.topLeft(), d, pristine, srcRect);
    const QImage source = fxmanager::readImage(pristine, srcRect);
    if (source.isNull()) return;

    FlareParams params = requested;
    QVector<tfm_flare_gpu::FlareSource> sources =
        tfm_flare_gpu::detectSources(source, params.threshold, params.maxSources);
    if (params.mode == tfm_flare_gpu::Mode::Anamorphic) {
        // A streak is one optical axis, not one independent flare per tile.
        // Filter-layer tiles can expose different local source peaks, so use a
        // stable frame anchor here; this keeps the band continuous across tiles.
        sources = {tfm_flare_gpu::FlareSource{0.5f, 0.5f, 1.0f, 0.06f}};
    }
    if (sources.isEmpty()) return;
    // Anamorphic Flare is a single continuous optical streak. Multiple local
    // peaks in a bright scene must not become separate horizontal bars: merge
    // them into the strongest source before both CPU and GPU rendering.
    if (params.mode == tfm_flare_gpu::Mode::Anamorphic && sources.size() > 1) {
        const auto strongest = std::max_element(sources.cbegin(), sources.cend(),
            [](const auto &a, const auto &b) { return a.strength < b.strength; });
        const auto primary = *strongest;
        sources = {primary};
    }

    if (fxmanager::gpuRequested()) {
        tfm_flare_gpu::Parameters gpu;
        gpu.srcRect = srcRect;
        gpu.outputRect = outputRect;
        gpu.mode = params.mode;
        gpu.threshold = float(params.threshold);
        gpu.length = float(params.length);
        gpu.intensity = float(params.intensity);
        gpu.tintShift = float(params.tintShift);
        gpu.decay = float(params.decay);
        gpu.aspect = float(params.aspect);
        gpu.blend = float(params.blend);
        gpu.sources = sources;
        QImage gpuOutput;
        QString reason, device;
        if (tfm_flare_gpu::render(source, gpu, gpuOutput, reason, device)) {
            const QImage cropped = gpuOutput.copy(outputRect.x() - srcRect.x(), outputRect.y() - srcRect.y(),
                                                  outputRect.width(), outputRect.height());
            fxmanager::writeImage(d, cropped, outputRect);
            fxmanager::reportBackend(id, QStringLiteral("gpu"), QString(), device);
            if (u) u->setProgress(100);
            return;
        }
        fxmanager::reportBackend(id, QStringLiteral("cpu"), reason);
    } else {
        fxmanager::reportBackend(id, QStringLiteral("cpu"), QStringLiteral("CPU selected"));
    }

    QImage current(srcRect.size(), QImage::Format_ARGB32);
    fxmanager::parallelRows(current.height(), [&](int y0, int y1) {
        flareBand(current, source, y0, y1, sources, params);
    });
    const QImage cropped = current.copy(outputRect.x() - srcRect.x(), outputRect.y() - srcRect.y(),
                                        outputRect.width(), outputRect.height());
    fxmanager::writeImage(d, cropped, outputRect);
    if (u) u->setProgress(100);
}

FlareParams readCommon(const KisFilterConfigurationSP c, tfm_flare_gpu::Mode mode,
                       double defaultLength, double defaultIntensity,
                       double defaultTint, double defaultDecay,
                       double defaultAspect, double defaultBlend)
{
    FlareParams p;
    p.mode = mode;
    p.threshold = std::clamp(c ? c->getDouble("threshold", 0.85) : 0.85, 0.0, 1.0);
    p.length = std::clamp(c ? c->getDouble("length", defaultLength) : defaultLength, 0.001, 1.0);
    p.intensity = std::clamp(c ? c->getDouble("intensity", defaultIntensity) : defaultIntensity, 0.0, 4.0);
    p.tintShift = std::clamp(c ? c->getDouble("tint", defaultTint) : defaultTint, 0.0, 1.0);
    p.decay = std::clamp(c ? c->getDouble("decay", defaultDecay) : defaultDecay, 0.05, 6.0);
    p.aspect = std::clamp(c ? c->getDouble("aspect", defaultAspect) : defaultAspect, 0.002, 0.5);
    p.blend = std::clamp(c ? c->getDouble("blend", defaultBlend) : defaultBlend, 0.0, 1.0);
    p.maxSources = int(std::clamp(c ? c->getDouble("sources", 1.0) : 1.0, 1.0, 8.0));
    return p;
}

} // namespace

// ---------------------------------------------------------------- Lens Flare

KisFilterLensFlare::KisFilterLensFlare()
    : KisFilter(id(), FiltersCategoryArtisticId, i18n("&Lens Flare..."))
{
    setSupportsAdjustmentLayers(true);
    setColorSpaceIndependence(FULLY_INDEPENDENT);
    setSupportsThreading(false);
}

KisFilterConfigurationSP KisFilterLensFlare::defaultConfiguration(KisResourcesInterfaceSP r) const
{
    auto c = factoryConfiguration(r);
    c->setProperty("threshold", 0.85);
    c->setProperty("length", 0.35);
    c->setProperty("decay", 3.0);
    c->setProperty("intensity", 1.0);
    c->setProperty("tint", 1.0);
    c->setProperty("blend", 1.0);
    c->setProperty("sources", 1.0);
    fxmanager::applyFilterDefaults(id().id(), c);
    return c;
}

KisConfigWidget *KisFilterLensFlare::createConfigurationWidget(QWidget *p, const KisPaintDeviceSP, bool) const
{
    return new FxManagerFilterWidget(id().id(), {
        {"threshold", i18n("Threshold"), 0.0, 1.0, 0.85, 0.01, 2},
        {"length", i18n("Spread"), 0.01, 1.0, 0.35, 0.01, 2},
        {"decay", i18n("Ghost Count"), 1.0, 6.0, 3.0, 1.0, 0},
        {"intensity", i18n("Intensity"), 0.0, 4.0, 1.0, 0.05, 2},
        {"tint", i18n("Dispersion"), 0.0, 1.0, 1.0, 0.01, 2},
        {"sources", i18n("Light Sources"), 1.0, 8.0, 1.0, 1.0, 0},
        {"blend", i18n("Blend"), 0.0, 1.0, 1.0, 0.01, 2},
    }, p, false);
}

void KisFilterLensFlare::processImpl(KisPaintDeviceSP d, const QRect &r,
                                    const KisFilterConfigurationSP c, KoUpdater *u) const
{
    runFlare(d, r, c, u,
             readCommon(c, tfm_flare_gpu::Mode::GhostFlare, 0.35, 1.0, 1.0, 3.0, 0.02, 1.0),
             id().id());
}

// ---------------------------------------------------------- Anamorphic Flare

KisFilterAnamorphicFlare::KisFilterAnamorphicFlare()
    : KisFilter(id(), FiltersCategoryArtisticId, i18n("&Anamorphic Flare..."))
{
    setSupportsAdjustmentLayers(true);
    setColorSpaceIndependence(FULLY_INDEPENDENT);
    setSupportsThreading(false);
}

KisFilterConfigurationSP KisFilterAnamorphicFlare::defaultConfiguration(KisResourcesInterfaceSP r) const
{
    auto c = factoryConfiguration(r);
    c->setProperty("threshold", 0.85);
    c->setProperty("length", 0.45);
    c->setProperty("decay", 0.35);
    c->setProperty("aspect", 0.012);
    c->setProperty("intensity", 1.0);
    c->setProperty("tint", 1.0);
    c->setProperty("blend", 1.0);
    c->setProperty("sources", 2.0);
    fxmanager::applyFilterDefaults(id().id(), c);
    return c;
}

KisConfigWidget *KisFilterAnamorphicFlare::createConfigurationWidget(QWidget *p, const KisPaintDeviceSP, bool) const
{
    return new FxManagerFilterWidget(id().id(), {
        {"threshold", i18n("Threshold"), 0.0, 1.0, 0.85, 0.01, 2},
        {"length", i18n("Streak Length"), 0.01, 1.0, 0.45, 0.01, 2},
        {"decay", i18n("Falloff"), 0.05, 2.0, 0.35, 0.01, 2},
        {"aspect", i18n("Thickness"), 0.002, 0.2, 0.012, 0.001, 3},
        {"intensity", i18n("Intensity"), 0.0, 4.0, 1.0, 0.05, 2},
        {"tint", i18n("Tint"), 0.0, 1.0, 1.0, 0.01, 2},
        {"sources", i18n("Light Sources"), 1.0, 8.0, 2.0, 1.0, 0},
        {"blend", i18n("Blend"), 0.0, 1.0, 1.0, 0.01, 2},
    }, p, false);
}

void KisFilterAnamorphicFlare::processImpl(KisPaintDeviceSP d, const QRect &r,
                                          const KisFilterConfigurationSP c, KoUpdater *u) const
{
    runFlare(d, r, c, u,
             readCommon(c, tfm_flare_gpu::Mode::Anamorphic, 0.45, 1.0, 1.0, 0.35, 0.012, 1.0),
             id().id());
}

// ---------------------------------------------------------------- Light Rays

KisFilterLightRays::KisFilterLightRays()
    : KisFilter(id(), FiltersCategoryArtisticId, i18n("&Light Rays..."))
{
    setSupportsAdjustmentLayers(true);
    setColorSpaceIndependence(FULLY_INDEPENDENT);
    setSupportsThreading(false);
}

KisFilterConfigurationSP KisFilterLightRays::defaultConfiguration(KisResourcesInterfaceSP r) const
{
    auto c = factoryConfiguration(r);
    c->setProperty("threshold", 0.7);
    c->setProperty("length", 0.6);
    c->setProperty("decay", 2.0);
    c->setProperty("intensity", 1.0);
    c->setProperty("tint", 1.0);
    c->setProperty("blend", 1.0);
    c->setProperty("sources", 1.0);
    fxmanager::applyFilterDefaults(id().id(), c);
    return c;
}

KisConfigWidget *KisFilterLightRays::createConfigurationWidget(QWidget *p, const KisPaintDeviceSP, bool) const
{
    return new FxManagerFilterWidget(id().id(), {
        {"threshold", i18n("Threshold"), 0.0, 1.0, 0.7, 0.01, 2},
        {"length", i18n("Length"), 0.01, 1.0, 0.6, 0.01, 2},
        {"decay", i18n("Falloff"), 0.1, 6.0, 2.0, 0.1, 2},
        {"intensity", i18n("Intensity"), 0.0, 4.0, 1.0, 0.05, 2},
        {"blend", i18n("Blend"), 0.0, 1.0, 1.0, 0.01, 2},
    }, p, false);
}

void KisFilterLightRays::processImpl(KisPaintDeviceSP d, const QRect &r,
                                     const KisFilterConfigurationSP c, KoUpdater *u) const
{
    runFlare(d, r, c, u,
             readCommon(c, tfm_flare_gpu::Mode::LightRays, 0.6, 1.0, 1.0, 2.0, 0.02, 1.0),
             id().id());
}
