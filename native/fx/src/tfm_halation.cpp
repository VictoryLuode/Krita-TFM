#include "tfm_halation.h"
#include "tfm_filter_widget.h"
#include "tfm_processing.h"
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
    double colorG = 0.29;
    double colorB = 0.12;
    bool channelR = true;
    bool channelG = true;
    bool channelB = true;
    bool channelMode = false;  // true = R/G/B switches, false = glow colour
};

constexpr double kLumaR = 0.2126, kLumaG = 0.7152, kLumaB = 0.0722;
// Detwiler ratios 9 : 5.5 : 3.5 — red scatters farthest through the film base.
constexpr double kSigmaScaleR = 0.55, kSigmaScaleG = 0.336, kSigmaScaleB = 0.214;

// Colour is stored as "#rrggbb" so it round-trips through KisPropertiesConfiguration.
void parseGlowColor(const QString &text, double *r, double *g, double *b)
{
    *r = 1.0; *g = 0.29; *b = 0.12;
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

inline double softEnergy(double luminance, double threshold)
{
    const double soft = 0.06;
    const double lo = threshold - soft;
    const double hi = std::min(1.0, threshold + soft * 0.35);
    double gate = 0.0;
    if (hi > lo) {
        const double t = std::clamp((luminance - lo) / (hi - lo), 0.0, 1.0);
        gate = t * t * (3.0 - 2.0 * t);
    } else if (luminance >= threshold) {
        gate = 1.0;
    }
    return gate * std::max(0.0, luminance - lo);
}

// Film-base halation (not tinted bloom): soft-gated highlights, per-channel
// radii, and additive fill into dark-side headroom. Matches shaders/halation.comp.
struct HalationTap {
    int x, y;
    double weight[3];
};

QVector<HalationTap> halationKernel(const HalationParams &p)
{
    const int samples = std::clamp(p.samples, 8, 64);
    const double scales[] = {kSigmaScaleR, kSigmaScaleG, kSigmaScaleB};
    QVector<HalationTap> taps(samples);
    double sums[3] = {};
    for (int i = 0; i < samples; ++i) {
        const double t = i + 0.5;
        const double distance = std::sqrt(t / samples) * p.radius;
        auto &tap = taps[i];
        tap.x = int(std::cos(t * 2.39996323) * distance);
        tap.y = int(std::sin(t * 2.39996323) * distance);
        for (int c = 0; c < 3; ++c) {
            const double sigma = std::max(1.0, p.radius * scales[c]);
            tap.weight[c] = std::exp(-distance * distance / (2.0 * sigma * sigma));
            sums[c] += tap.weight[c];
        }
    }
    for (auto &tap : taps)
        for (int c = 0; c < 3; ++c) tap.weight[c] /= sums[c];
    return taps;
}

void halationBand(QImage &output, const QImage &source, int y0, int y1,
                  const HalationParams &p, const QVector<HalationTap> &kernel, KoUpdater *updater)
{
    for (int y = y0; y < y1; ++y) {
        if (updater && updater->interrupted()) return;
        QRgb *row = reinterpret_cast<QRgb *>(output.scanLine(y));
        for (int x = 0; x < output.width(); ++x) {
            const QRgb centre = clampedPixel(source, x, y);
            double glowR = 0.0, glowG = 0.0, glowB = 0.0;
            for (const auto &tap : kernel) {
                const QRgb pixel = clampedPixel(source, x + tap.x, y + tap.y);
                const double energy = softEnergy((kLumaR * qRed(pixel) + kLumaG * qGreen(pixel)
                    + kLumaB * qBlue(pixel)) / 255.0, p.threshold);
                glowR += energy * tap.weight[0];
                glowG += energy * tap.weight[1];
                glowB += energy * tap.weight[2];
            }
            const double destLum = std::clamp(
                (kLumaR * qRed(centre) + kLumaG * qGreen(centre) + kLumaB * qBlue(centre)) / 255.0, 0.0, 1.0);
            const double darkBias = 0.4 + 0.6 * std::pow(1.0 - destLum, 0.9);
            glowR *= darkBias * 1.45; glowG *= darkBias * 1.45; glowB *= darkBias * 1.45;
            const double tint = std::clamp(p.tintShift, 0.0, 1.0);
            const double gain = std::clamp(p.intensity, 0.0, 4.0);
            double shapedR, shapedG, shapedB;
            if (p.channelMode) {
                shapedR = glowR * (p.channelR ? 1.0 : 0.0);
                shapedG = glowG * (p.channelG ? 1.0 : 0.0);
                shapedB = glowB * (p.channelB ? 1.0 : 0.0);
            } else {
                shapedR = glowR * (1.0 + (p.colorR - 1.0) * tint);
                shapedG = glowG * (1.0 + (p.colorG - 1.0) * tint);
                shapedB = glowB * (1.0 + (p.colorB - 1.0) * tint);
            }
            shapedR *= gain; shapedG *= gain; shapedB *= gain;
            const double blend = std::clamp(p.blend, 0.0, 1.0);
            auto mixChannel = [&](double base, double light) {
                return std::clamp(base + (255.0 - base) * light * blend, 0.0, 255.0);
            };
            row[x] = qRgba(int(std::lround(mixChannel(qRed(centre), shapedR))),
                           int(std::lround(mixChannel(qGreen(centre), shapedG))),
                           int(std::lround(mixChannel(qBlue(centre), shapedB))),
                           qAlpha(centre));
        }
    }
}

} // namespace

namespace {
tfm::EncodedRgbaImage halationFloat(const tfm::EncodedRgbaImage &source,
                                         const HalationParams &p, KoUpdater *updater)
{
    auto output = source;
    auto *dst = output.pixels.data();
    const auto *src = source.pixels.constData();
    const auto kernel = halationKernel(p);
    const double colours[] = {p.colorR, p.colorG, p.colorB};
    const bool channels[] = {p.channelR, p.channelG, p.channelB};
    tfm::parallelRows(source.height, [&](int y0, int y1) {
        for (int y = y0; y < y1; ++y) {
            if (updater && updater->interrupted()) return;
            for (int x = 0; x < source.width; ++x) {
                double glow[3] = {};
                for (const auto &tap : kernel) {
                    const auto *sample = src + 4 * (std::clamp(y + tap.y, 0, source.height - 1)
                        * source.width + std::clamp(x + tap.x, 0, source.width - 1));
                    const double energy = softEnergy(
                        kLumaR * sample[0] + kLumaG * sample[1] + kLumaB * sample[2], p.threshold);
                    for (int c = 0; c < 3; ++c) glow[c] += energy * tap.weight[c];
                }
                auto *pixel = dst + 4 * (y * source.width + x);
                const double destLum = std::clamp(
                    kLumaR * pixel[0] + kLumaG * pixel[1] + kLumaB * pixel[2], 0.0, 1.0);
                const double darkBias = 0.4 + 0.6 * std::pow(1.0 - destLum, 0.9);
                for (int c = 0; c < 3; ++c) {
                    double light = glow[c] * darkBias * 1.45;
                    const double tint = p.channelMode ? (channels[c] ? 1.0 : 0.0)
                                                      : 1.0 + (colours[c] - 1.0) * p.tintShift;
                    light *= tint * p.intensity;
                    const double headroom = std::max(0.0, 1.0 - std::clamp(double(pixel[c]), 0.0, 1.0));
                    pixel[c] = float(pixel[c] + headroom * light * p.blend);
                }
            }
        }
    });
    return output;
}
}

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

    tfm::applyBuiltinDefaults(id().id(), c);
    tfm::applyFilterDefaults(id().id(), c);
    return c;
}

KisConfigWidget *KisFilterHalation::createConfigurationWidget(QWidget *p, const KisPaintDeviceSP, bool) const
{
    return new TfmFilterWidget(id().id(), {
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
        {"glow_color", i18n("Glow Color"), QStringLiteral("#ff4a1e")},
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
    if (r.isEmpty() || !d || (u && u->interrupted())) return;
    HalationParams params;
    params.threshold = std::clamp(c ? c->getDouble("threshold", 0.75) : 0.75, 0.0, 1.0);
    params.radius = std::clamp(c ? c->getDouble("radius", 24.0) : 24.0, 1.0, 200.0);
    params.intensity = std::clamp(c ? c->getDouble("intensity", 1.0) : 1.0, 0.0, 4.0);
    params.tintShift = std::clamp(c ? c->getDouble("tint", 1.0) : 1.0, 0.0, 1.0);
    params.blend = std::clamp(c ? c->getDouble("blend", 1.0) : 1.0, 0.0, 1.0);
    params.samples = int(std::clamp(c ? c->getDouble("quality", 32.0) : 32.0, 8.0, 64.0));
    parseGlowColor(c ? c->getString("glow_color", QStringLiteral("#ff4a1e")) : QStringLiteral("#ff4a1e"),
                   &params.colorR, &params.colorG, &params.colorB);
    params.channelR = !c || c->getBool("channel_r", true);
    params.channelG = !c || c->getBool("channel_g", true);
    params.channelB = !c || c->getBool("channel_b", true);
    params.channelMode = c && c->getString("glow_mode", QStringLiteral("color")) == QLatin1String("channels");

    if(params.blend==0.0 || params.intensity==0.0
        || (params.channelMode && !params.channelR && !params.channelG && !params.channelB)) {
        if(u) u->setProgress(100);
        return;
    }

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
    if(tfm::requiresFloatProcessing(d)) {
        const auto source=tfm::readEncodedImage(pristine,srcRect);
        if(source.isNull()) return;
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
        tfm::EncodedRgbaImage current;
        QString reason;
        QString device;
        bool usedGpu = false;
        if (tfm::gpuRequested(id().id(), qint64(srcRect.width()) * srcRect.height())) {
            usedGpu = tfm_halation_gpu::renderFloat(source, gpu, current, reason, device,
                                                    [u] { return u && u->interrupted(); });
            if (u && u->interrupted()) return;
            if (!usedGpu) tfm::reportBackend(id().id(), QStringLiteral("cpu"), reason);
        } else {
            tfm::reportBackend(id().id(), QStringLiteral("cpu"), QStringLiteral("CPU selected"));
        }
        if (!usedGpu) current = halationFloat(source, params, u);
        if(u && u->interrupted()) return;
        const auto cropped=current.copy(QRect(outputRect.topLeft()-srcRect.topLeft(),outputRect.size()));
        const bool written=tfm::writeEncodedImage(d,cropped,outputRect);
        tfm::reportBackend(id().id(), usedGpu ? QStringLiteral("gpu") : QStringLiteral("cpu"),
            written ? QString() : QStringLiteral("Float output conversion failed; pixels unchanged"),
            usedGpu ? device : QString());
        if(written && u) u->setProgress(100);
        return;
    }
    const QImage source = tfm::readImage(pristine, srcRect);
    if (source.isNull()) return;

    if (tfm::gpuRequested(id().id(), qint64(srcRect.width()) * srcRect.height())) {
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
        if (tfm_halation_gpu::render(source, gpu, gpuOutput, reason, device, [u] { return u && u->interrupted(); })) {
            if(u && u->interrupted()) return;
            const QImage cropped = gpuOutput.copy(outputRect.x() - srcRect.x(), outputRect.y() - srcRect.y(),
                                                  outputRect.width(), outputRect.height());
            tfm::writeImage(d, cropped, outputRect);
            tfm::reportBackend(id().id(), QStringLiteral("gpu"), QString(), device);
            if (u) u->setProgress(100);
            return;
        }
        if(u && u->interrupted()) return;
        tfm::reportBackend(id().id(), QStringLiteral("cpu"), reason);
    } else {
        tfm::reportBackend(id().id(), QStringLiteral("cpu"), QStringLiteral("CPU selected"));
    }

    QImage current(source.size(), QImage::Format_ARGB32);
    const auto kernel = halationKernel(params);
    tfm::parallelRows(current.height(), [&](int y0, int y1) { halationBand(current, source, y0, y1, params, kernel, u); });
    const QImage cropped = current.copy(outputRect.x() - srcRect.x(), outputRect.y() - srcRect.y(),
                                        outputRect.width(), outputRect.height());
    if(u && u->interrupted()) return;
    tfm::writeImage(d, cropped, outputRect);
    if (u) u->setProgress(100);
}
