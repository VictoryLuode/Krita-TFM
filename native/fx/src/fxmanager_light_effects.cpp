#include "fxmanager_light_effects.h"
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

struct Rgb { double r, g, b; };

Rgb hsvToRgb(double h, double s, double v)
{
    h = std::fmod(h, 1.0);
    if (h < 0.0) h += 1.0;
    const double c = v * s;
    const double x = c * (1.0 - std::abs(std::fmod(h * 6.0, 2.0) - 1.0));
    const double m = v - c;
    double r = 0.0, g = 0.0, b = 0.0;
    const int sector = int(h * 6.0);
    switch (sector) {
    case 0: r = c; g = x; break;
    case 1: r = x; g = c; break;
    case 2: g = c; b = x; break;
    case 3: g = x; b = c; break;
    case 4: r = x; b = c; break;
    default: r = c; b = x; break;
    }
    return {r + m, g + m, b + m};
}

double hash01(int a, int b)
{
    unsigned n = unsigned(a) * 374761393u + unsigned(b) * 668265263u;
    n = (n ^ (n >> 13)) * 1274126177u;
    return (n & 0x00ffffffu) / double(0x01000000);
}

double smoothstep(double edge0, double edge1, double value)
{
    const double t = std::clamp((value - edge0) / (edge1 - edge0), 0.0, 1.0);
    return t * t * (3.0 - 2.0 * t);
}

double rotatedField(double x, double y, double angleDegrees)
{
    const double angle = angleDegrees * (3.14159265358979323846 / 180.0);
    return x * std::cos(angle) - y * std::sin(angle);
}

// ---------------------------------------------------------------- Light Leaks

struct LeakParams { int type; double angle, scaleX, scaleY, hue, opacity; QString blend; };

const char *leakTypeName(int index)
{
    static const char *names[] = {
        "wash_horizontal", "wash_vertical", "glow_top_left",
        "glow_bottom_right", "edge_ring", "diagonal",
    };
    return names[index];
}

// Named plates, plus the old 0–40 slider. Values past 5 keep the same shape
// (type % 6) so a saved numeric configuration still lands on a plate.
int leakTypeIndex(const KisFilterConfigurationSP &config)
{
    if (!config) return 0;
    const QString text = config->getString(QStringLiteral("leak_type"));
    for (int index = 0; index < 6; ++index) {
        if (text == QLatin1String(leakTypeName(index))) return index;
    }
    bool ok = false;
    int numeric = text.toInt(&ok);
    if (!ok) {
        const double raw = config->getDouble(QStringLiteral("leak_type"), 0.0);
        if (!std::isfinite(raw)) return 0;
        numeric = int(std::lround(std::clamp(raw, 0.0, 40.0)));
    }
    numeric %= 6;
    if (numeric < 0) numeric += 6;
    return numeric;
}

// One smooth wash per leak type.
double leakShape(int type, double x, double y)
{
    const double edge = std::min(std::min(x, 1.0 - x), std::min(y, 1.0 - y));
    switch (type % 6) {
    case 0: return smoothstep(0.15, 0.95, x) * (0.65 + 0.35 * std::sin(y * 6.0));
    case 1: return smoothstep(0.1, 0.8, y) * (0.7 + 0.3 * std::sin(x * 5.0));
    case 2: return std::exp(-((x - 0.15) * (x - 0.15) + (y - 0.2) * (y - 0.2)) * 6.0);
    case 3: return std::exp(-((x - 0.85) * (x - 0.85) + (y - 0.75) * (y - 0.75)) * 5.0);
    case 4: return smoothstep(0.05, 0.6, edge) * (0.5 + 0.5 * std::sin((x + y) * 8.0));
    default: return 0.6 * smoothstep(0.0, 0.7, x) + 0.4 * smoothstep(0.0, 0.5, 1.0 - y);
    }
}

void applyLeaks(QImage &image, const LeakParams &p, const QRect &frame, const QPoint &origin)
{
    const int width = image.width();
    const int height = image.height();
    // Normalise against the whole canvas, not this patch: Krita renders a
    // filter layer patch by patch, and per-patch normalisation would draw one
    // complete leak inside every tile.
    const double frameW = std::max(1, frame.width() - 1);
    const double frameH = std::max(1, frame.height() - 1);
    const double hueShift = p.hue / 360.0;
    for (int y = 0; y < height; ++y) {
        QRgb *row = reinterpret_cast<QRgb *>(image.scanLine(y));
        for (int x = 0; x < width; ++x) {
            const double canvasX = origin.x() + x;
            const double canvasY = origin.y() + y;
            const double nx = (canvasX / frameW - 0.5) / p.scaleX + 0.5;
            const double ny = (canvasY / frameH - 0.5) / p.scaleY + 0.5;
            const double rx = rotatedField(nx - 0.5, ny - 0.5, p.angle) + 0.5;
            const double ry = rotatedField(ny - 0.5, 0.5 - nx, p.angle) + 0.5;
            const double amount = std::clamp(leakShape(p.type, std::clamp(rx, 0.0, 1.0), std::clamp(ry, 0.0, 1.0)), 0.0, 1.0);
            const double warmth = 0.02 + 0.08 * std::sin(p.type * 1.7);
            const Rgb leak = hsvToRgb(std::fmod(warmth + hueShift + 1.0, 1.0), 0.85, 1.0);

            const QRgb pixel = row[x];
            double r = qRed(pixel) / 255.0;
            double g = qGreen(pixel) / 255.0;
            double b = qBlue(pixel) / 255.0;
            const double t = amount * p.opacity;
            if (p.blend == QLatin1String("add")) {
                r += leak.r * t; g += leak.g * t; b += leak.b * t;
            } else if (p.blend == QLatin1String("lighten")) {
                r = std::max(r, leak.r * t + r * (1.0 - t));
                g = std::max(g, leak.g * t + g * (1.0 - t));
                b = std::max(b, leak.b * t + b * (1.0 - t));
            } else {
                // Screen, the G'MIC default: 1 - (1 - base) * (1 - leak).
                r = 1.0 - (1.0 - r) * (1.0 - leak.r * t);
                g = 1.0 - (1.0 - g) * (1.0 - leak.g * t);
                b = 1.0 - (1.0 - b) * (1.0 - leak.b * t);
            }
            row[x] = qRgba(int(std::lround(std::clamp(r, 0.0, 1.0) * 255.0)),
                           int(std::lround(std::clamp(g, 0.0, 1.0) * 255.0)),
                           int(std::lround(std::clamp(b, 0.0, 1.0) * 255.0)), qAlpha(pixel));
        }
    }
}

// --------------------------------------------------------------- Light Patch

struct PatchParams { double density, darkness, lightness; };

void applyPatch(QImage &image, const PatchParams &p, const QRect &frame, const QPoint &origin)
{
    const int width = image.width();
    const int height = image.height();
    // Patch centres are canvas-space; deriving them from the patch size would
    // place one full set of patches in every tile.
    const double frameW = double(std::max(1, frame.width()));
    const double frameH = double(std::max(1, frame.height()));
    const int patches = std::max(1, int(std::lround(p.density)));
    for (int y = 0; y < height; ++y) {
        QRgb *row = reinterpret_cast<QRgb *>(image.scanLine(y));
        for (int x = 0; x < width; ++x) {
            const double canvasX = origin.x() + x;
            const double canvasY = origin.y() + y;
            const QRgb pixel = row[x];
            double r = qRed(pixel) / 255.0;
            double g = qGreen(pixel) / 255.0;
            double b = qBlue(pixel) / 255.0;
            const double luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
            double shade = luminance * (1.0 - p.darkness);
            for (int patch = 0; patch < patches; ++patch) {
                const double cx = hash01(patch, 1);
                const double cy = hash01(patch, 2);
                const double radius = 0.08 + 0.18 * hash01(patch, 3);
                const double dx = (canvasX / frameW - cx) / radius;
                const double dy = (canvasY / frameH - cy) / (radius * 0.75);
                const double falloff = std::exp(-(dx * dx + dy * dy) * 2.0);
                const double warmth = hash01(patch, 4);
                const Rgb tint = hsvToRgb(0.02 + 0.12 * warmth, 0.35 + 0.4 * warmth, 1.0);
                const double gain = falloff * p.lightness * 0.35;
                shade += gain;
                r += tint.r * gain * 0.15;
                g += tint.g * gain * 0.15;
                b += tint.b * gain * 0.15;
            }
            // Darkness pulls the whole frame down; the patches punch bright spots back through it.
            const double lift = std::clamp(shade, 0.0, 2.0);
            r = std::clamp(r * (1.0 - p.darkness) + lift, 0.0, 1.0);
            g = std::clamp(g * (1.0 - p.darkness) + lift, 0.0, 1.0);
            b = std::clamp(b * (1.0 - p.darkness) + lift, 0.0, 1.0);
            row[x] = qRgba(int(std::lround(r * 255.0)), int(std::lround(g * 255.0)),
                           int(std::lround(b * 255.0)), qAlpha(pixel));
        }
    }
}

} // namespace

// ---------------------------------------------------------------- Light Leaks

KisFilterLightLeaks::KisFilterLightLeaks()
    : KisFilter(id(), FiltersCategoryArtisticId, i18n("&Light Leaks..."))
{
    setSupportsAdjustmentLayers(true);
    setColorSpaceIndependence(FULLY_INDEPENDENT);
}

KisFilterConfigurationSP KisFilterLightLeaks::defaultConfiguration(KisResourcesInterfaceSP r) const
{
    auto c = factoryConfiguration(r);
    c->setProperty("leak_type", QStringLiteral("wash_horizontal"));
    c->setProperty("angle", 0.0);
    c->setProperty("scale_x", 1.0);
    c->setProperty("scale_y", 1.0);
    c->setProperty("hue", 0.0);
    c->setProperty("opacity", 85.0);
    c->setProperty("blend", QStringLiteral("screen"));
    fxmanager::applyFilterDefaults(id().id(), c);
    return c;
}

KisConfigWidget *KisFilterLightLeaks::createConfigurationWidget(QWidget *p, const KisPaintDeviceSP, bool) const
{
    return new FxManagerFilterWidget(id().id(), {
        {"angle", i18n("Angle"), -180.0, 180.0, 0.0, 1.0, 0},
        {"scale_x", i18n("X-Scale"), 0.1, 4.0, 1.0, 0.01, 2},
        {"scale_y", i18n("Y-Scale"), 0.1, 4.0, 1.0, 0.01, 2},
        {"hue", i18n("Hue"), -180.0, 180.0, 0.0, 1.0, 0},
        {"opacity", i18n("Opacity (%)"), 0.0, 100.0, 85.0, 0.1, 1},
    }, p, false, {
        {"leak_type", i18n("Leak Type"), {
            {"wash_horizontal", i18n("Horizontal Wash")},
            {"wash_vertical", i18n("Vertical Wash")},
            {"glow_top_left", i18n("Top-Left Glow")},
            {"glow_bottom_right", i18n("Bottom-Right Glow")},
            {"edge_ring", i18n("Edge Ring")},
            {"diagonal", i18n("Diagonal Wash")},
        }, QStringLiteral("wash_horizontal")},
        {"blend", i18n("Blend Mode"), {
            {"screen", i18n("Screen")}, {"add", i18n("Add")}, {"lighten", i18n("Lighten")},
        }, QStringLiteral("screen")},
    });
}

void KisFilterLightLeaks::processImpl(KisPaintDeviceSP d, const QRect &r,
                                      const KisFilterConfigurationSP c, KoUpdater *u) const
{
    if (r.isEmpty() || !d) return;
    LeakParams params;
    params.type = leakTypeIndex(c);
    params.angle = std::clamp(c ? c->getDouble("angle", 0.0) : 0.0, -180.0, 180.0);
    params.scaleX = std::clamp(c ? c->getDouble("scale_x", 1.0) : 1.0, 0.1, 4.0);
    params.scaleY = std::clamp(c ? c->getDouble("scale_y", 1.0) : 1.0, 0.1, 4.0);
    params.hue = std::clamp(c ? c->getDouble("hue", 0.0) : 0.0, -180.0, 180.0);
    params.opacity = std::clamp(c ? c->getDouble("opacity", 85.0) : 85.0, 0.0, 100.0) / 100.0;
    params.blend = c ? c->getString("blend", QStringLiteral("screen")) : QStringLiteral("screen");

    QRect frame = d->defaultBounds()->bounds();
    if (frame.isEmpty()) frame = d->extent();
    if (frame.isEmpty()) frame = r;
    const QRect outputRect = r.intersected(frame);
    if (outputRect.isEmpty()) return;

    QImage output = fxmanager::readImage(d, outputRect);
    if (output.isNull()) return;
    if (fxmanager::gpuRequested()) {
        tfm_pointwise_gpu::Parameters gpu;
        gpu.operation = tfm_pointwise_gpu::Operation::LightLeaks;
        gpu.outputRect = outputRect;
        gpu.frame = frame;
        gpu.channel = params.type;
        gpu.angle = float(params.angle);
        gpu.scaleX = float(params.scaleX);
        gpu.scaleY = float(params.scaleY);
        gpu.p0 = float(params.hue);
        gpu.p1 = float(params.opacity);
        gpu.mode = params.blend == QLatin1String("add") ? 1 : params.blend == QLatin1String("lighten") ? 2 : 0;
        QImage gpuOutput;
        QString reason, device;
        if (tfm_pointwise_gpu::render(output, gpu, gpuOutput, reason, device)) {
            fxmanager::writeImage(d, gpuOutput, outputRect);
            fxmanager::reportBackend(id().id(), QStringLiteral("gpu"), QString(), device);
            if (u) u->setProgress(100);
            return;
        }
        fxmanager::reportBackend(id().id(), QStringLiteral("cpu"), reason);
    } else {
        fxmanager::reportBackend(id().id(), QStringLiteral("cpu"), QStringLiteral("CPU selected"));
    }
    applyLeaks(output, params, frame, outputRect.topLeft() - frame.topLeft());
    fxmanager::writeImage(d, output, outputRect);
    if (u) u->setProgress(100);
}

// --------------------------------------------------------------- Light Patch

KisFilterLightPatch::KisFilterLightPatch()
    : KisFilter(id(), FiltersCategoryArtisticId, i18n("&Light Patch..."))
{
    setSupportsAdjustmentLayers(true);
    setColorSpaceIndependence(FULLY_INDEPENDENT);
}

KisFilterConfigurationSP KisFilterLightPatch::defaultConfiguration(KisResourcesInterfaceSP r) const
{
    auto c = factoryConfiguration(r);
    c->setProperty("density", 20.0);
    c->setProperty("darkness", 0.951);
    c->setProperty("lightness", 1.015);
    fxmanager::applyFilterDefaults(id().id(), c);
    return c;
}

KisConfigWidget *KisFilterLightPatch::createConfigurationWidget(QWidget *p, const KisPaintDeviceSP, bool) const
{
    return new FxManagerFilterWidget(id().id(), {
        {"density", i18n("Density"), 1.0, 60.0, 20.0, 1.0, 0},
        {"darkness", i18n("Darkness"), 0.0, 1.0, 0.951, 0.001, 3},
        {"lightness", i18n("Lightness"), 0.0, 4.0, 1.015, 0.001, 3},
    }, p);
}

void KisFilterLightPatch::processImpl(KisPaintDeviceSP d, const QRect &r,
                                      const KisFilterConfigurationSP c, KoUpdater *u) const
{
    if (r.isEmpty() || !d) return;
    PatchParams params;
    params.density = std::clamp(c ? c->getDouble("density", 20.0) : 20.0, 1.0, 60.0);
    params.darkness = std::clamp(c ? c->getDouble("darkness", 0.951) : 0.951, 0.0, 1.0);
    params.lightness = std::clamp(c ? c->getDouble("lightness", 1.015) : 1.015, 0.0, 4.0);

    QRect frame = d->defaultBounds()->bounds();
    if (frame.isEmpty()) frame = d->extent();
    if (frame.isEmpty()) frame = r;
    const QRect outputRect = r.intersected(frame);
    if (outputRect.isEmpty()) return;

    QImage output = fxmanager::readImage(d, outputRect);
    if (output.isNull()) return;
    if (fxmanager::gpuRequested()) {
        tfm_pointwise_gpu::Parameters gpu;
        gpu.operation = tfm_pointwise_gpu::Operation::LightPatch;
        gpu.outputRect = outputRect;
        gpu.frame = frame;
        gpu.p0 = float(params.darkness);
        gpu.p1 = float(params.lightness);
        gpu.mode = std::max(1, int(std::lround(params.density)));
        QImage gpuOutput;
        QString reason, device;
        if (tfm_pointwise_gpu::render(output, gpu, gpuOutput, reason, device)) {
            fxmanager::writeImage(d, gpuOutput, outputRect);
            fxmanager::reportBackend(id().id(), QStringLiteral("gpu"), QString(), device);
            if (u) u->setProgress(100);
            return;
        }
        fxmanager::reportBackend(id().id(), QStringLiteral("cpu"), reason);
    } else {
        fxmanager::reportBackend(id().id(), QStringLiteral("cpu"), QStringLiteral("CPU selected"));
    }
    applyPatch(output, params, frame, outputRect.topLeft() - frame.topLeft());
    fxmanager::writeImage(d, output, outputRect);
    if (u) u->setProgress(100);
}
