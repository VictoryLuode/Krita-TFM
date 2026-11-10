#include "fxmanager_film_grain.h"
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
struct Preset { const char *id; double amount; double size; int seed; bool monochrome; };
const Preset presetFor(const QString &id)
{
    static const Preset custom {"custom", .18, 2.0, 17, true};
    static const Preset presets[] = {
        {"8mm_caffenol", .14, 2.5, 11, true},
        {"8mm_home_movie", .22, 1.8, 23, true},
        {"super_8", .18, 2.0, 17, true},
        {"16mm_broadcast", .12, 1.5, 31, false},
        {"16mm_indie_cinema", .10, 1.2, 47, false},
        {"35mm_portra_400", .08, 1.0, 61, false},
        {"super_35", .06, .9, 73, false},
        {"70mm_cinema", .035, .7, 89, false},
    };
    for (const Preset &preset : presets) if (id == QLatin1String(preset.id)) return preset;
    return custom;
}
void grainBand(QImage &image, int y0, int y1, double amount, double size, int seed, bool monochrome,
               const QPoint &origin)
{
    const int width = image.width();
    const double amplitude = std::clamp(amount, 0.0, 1.0) * 255.0;
    for (int y = y0; y < y1; ++y) {
        QRgb *row = reinterpret_cast<QRgb *>(image.scanLine(y));
        for (int x = 0; x < width; ++x) {
            const int gx = origin.x() + x;
            const int gy = origin.y() + y;
            const double common = fxmanager::deterministicNoise(int(std::floor(gx / std::max(.5, size))), int(std::floor(gy / std::max(.5, size))), seed);
            const double nr = monochrome ? common : fxmanager::deterministicNoise(gx, gy, seed, 1);
            const double ng = monochrome ? common : fxmanager::deterministicNoise(gx, gy, seed, 2);
            const double nb = monochrome ? common : fxmanager::deterministicNoise(gx, gy, seed, 3);
            const QRgb p = row[x];
            row[x] = qRgba(std::clamp(int(qRed(p) + nr * amplitude), 0, 255), std::clamp(int(qGreen(p) + ng * amplitude), 0, 255), std::clamp(int(qBlue(p) + nb * amplitude), 0, 255), qAlpha(p));
        }
    }
}
}

KisFilterFilmGrain::KisFilterFilmGrain() : KisFilter(id(), FiltersCategoryArtisticId, i18n("&Film Grain...")) { setSupportsAdjustmentLayers(true); setColorSpaceIndependence(FULLY_INDEPENDENT); }
KisFilterConfigurationSP KisFilterFilmGrain::defaultConfiguration(KisResourcesInterfaceSP r) const
{
    auto c = factoryConfiguration(r);      fxmanager::applyBuiltinDefaults(id().id(), c);
    fxmanager::applyFilterDefaults(id().id(), c); return c;
}
KisConfigWidget *KisFilterFilmGrain::createConfigurationWidget(QWidget *p, const KisPaintDeviceSP, bool) const
{
    return new FxManagerFilterWidget(id().id(), {{"amount", i18n("Amount"), 0, 1, .18, .01, 3}, {"size", i18n("Size"), .5, 8, 2, .1, 1}, {"seed", i18n("Seed"), 0, 999, 17, 1, 0}}, p, true,
        {{"preset", i18n("Preset"), {{"8mm_caffenol", i18n("8 mm Caffenol")}, {"8mm_home_movie", i18n("8 mm Home Movie")}, {"super_8", i18n("Super 8 mm")}, {"16mm_broadcast", i18n("16 mm Broadcast")}, {"16mm_indie_cinema", i18n("16 mm Indie Cinema")}, {"35mm_portra_400", i18n("35 mm Portra 400")}, {"super_35", i18n("Super 35 mm")}, {"70mm_cinema", i18n("70 mm Cinema")}, {"custom", i18n("Custom")}}, "super_8"}});
}
void KisFilterFilmGrain::processImpl(KisPaintDeviceSP d, const QRect &r, const KisFilterConfigurationSP c, KoUpdater *u) const
{
    if (r.isEmpty() || !d || (u && u->interrupted())) return;
    const Preset preset = presetFor(c ? c->getString("preset", "super_8") : QStringLiteral("super_8"));
    const bool isCustom = QString::fromLatin1(preset.id) == QLatin1String("custom");
    const double amount = isCustom ? (c ? c->getDouble("amount", preset.amount) : preset.amount) : preset.amount;
    const double size = isCustom ? (c ? c->getDouble("size", preset.size) : preset.size) : preset.size;
    const int seed = isCustom ? (c ? c->getInt("seed", preset.seed) : preset.seed) : preset.seed;
    const bool mono = isCustom ? (c ? c->getBool("monochrome", preset.monochrome) : preset.monochrome) : preset.monochrome;
    if(amount<=0.0) { if(u) u->setProgress(100); return; }
    if(fxmanager::requiresFloatProcessing(d)) {
        fxmanager::transformEncoded(d,r,id().id(),u,[&](float *p,int gx,int gy) {
            const double common=fxmanager::deterministicNoise(int(std::floor(gx/std::max(.5,size))),int(std::floor(gy/std::max(.5,size))),seed);
            for(int channel=0;channel<3;++channel) {
                const double noise=mono ? common : fxmanager::deterministicNoise(gx,gy,seed,channel+1);
                p[channel]+=float(noise*std::clamp(amount,0.0,1.0));
            }
        });
        return;
    }
    QImage image = fxmanager::readImage(d, r); if (image.isNull()) return;
    const QPoint frameOffset = r.topLeft();
    if (fxmanager::gpuRequested(id().id(),qint64(r.width())*r.height())) {
        tfm_pointwise_gpu::Parameters gpu;
        gpu.operation = tfm_pointwise_gpu::Operation::FilmGrain;
        gpu.outputRect = r;
        gpu.amount = float(amount);
        gpu.size = float(size);
        gpu.seed = float(seed);
        gpu.monochrome = mono ? 1 : 0;
        QImage output;
        QString reason, device;
        if (tfm_pointwise_gpu::render(image, gpu, output, reason, device, [u] { return u && u->interrupted(); })) {
            if(u && u->interrupted()) return;
            fxmanager::writeImage(d, output, r);
            fxmanager::reportBackend(id().id(), QStringLiteral("gpu"), QString(), device);
            if (u) u->setProgress(100);
            return;
        }
        if(u && u->interrupted()) return;
        fxmanager::reportBackend(id().id(), QStringLiteral("cpu"), reason);
    } else {
        fxmanager::reportBackend(id().id(), QStringLiteral("cpu"), fxmanager::cpuBackendReason(id().id(),qint64(r.width())*r.height()));
    }
    fxmanager::parallelRows(image.height(), [&](int y0, int y1) { grainBand(image, y0, y1, amount, size, seed, mono, frameOffset); });
    if(u && u->interrupted()) return;
    fxmanager::writeImage(d, image, r); if (u) u->setProgress(100);
}
