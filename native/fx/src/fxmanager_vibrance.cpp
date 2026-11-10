#include "fxmanager_vibrance.h"
#include "fxmanager_filter_widget.h"
#include "fxmanager_processing.h"
#include "tfm_pointwise_gpu.h"
#include "pointwise_math.h"

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

using namespace fxmanager::pointwise;

void applyBand(QImage &image, int y0, int y1, const VibranceParams &p)
{
    for(int y=y0;y<y1;++y) {
        auto *row=reinterpret_cast<QRgb*>(image.scanLine(y));
        for(int x=0;x<image.width();++x) {
            const auto pixel=row[x];
            const auto out=fxmanager::pointwise::vibrance({qRed(pixel)/255.0,qGreen(pixel)/255.0,qBlue(pixel)/255.0},p,true);
            row[x]=qRgba(int(std::lround(out.r*255.0)),int(std::lround(out.g*255.0)),int(std::lround(out.b*255.0)),qAlpha(pixel));
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

    fxmanager::applyBuiltinDefaults(id().id(), c);
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
    if (r.isEmpty() || !d || (u && u->interrupted())) return;
    VibranceParams params;
    params.vibrance = std::clamp(c ? c->getDouble("vibrance", 30.0) : 30.0, -100.0, 100.0) / 100.0;
    params.saturation = std::clamp(c ? c->getDouble("saturation", 0.0) : 0.0, -100.0, 100.0) / 100.0;
    params.skin = std::clamp(c ? c->getDouble("skin_protect", 1.0) : 1.0, 0.0, 1.0);
    params.protect = std::clamp(c ? c->getDouble("protect_highlights", 0.5) : 0.5, 0.0, 1.0);
    params.blend = std::clamp(c ? c->getDouble("blend", 1.0) : 1.0, 0.0, 1.0);

    if (params.blend == 0.0 || (params.vibrance == 0.0 && params.saturation == 0.0)) { if(u) u->setProgress(100); return; }
    if (fxmanager::requiresFloatProcessing(d)) {
        fxmanager::transformEncoded(d,r,id().id(),u,[&](float *p,int,int) {
            const auto out=fxmanager::pointwise::vibrance({p[0],p[1],p[2]},params,false);
            p[0]=float(out.r); p[1]=float(out.g); p[2]=float(out.b);
        });
        return;
    }

    const QImage source = fxmanager::readImage(d, r);
    if (source.isNull()) return;
    if (fxmanager::gpuRequested(id().id(),qint64(r.width())*r.height())) {
        tfm_pointwise_gpu::Parameters gpu;
        gpu.operation = tfm_pointwise_gpu::Operation::Vibrance;
        gpu.outputRect = r;
        gpu.p0 = float(params.vibrance * 100.0);
        gpu.p1 = float(params.saturation * 100.0);
        gpu.p2 = float(params.skin);
        gpu.p3 = float(params.protect);
        gpu.p4 = float(params.blend);
        QImage output; QString reason, device;
        if (tfm_pointwise_gpu::render(source, gpu, output, reason, device, [u] { return u && u->interrupted(); })) {
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

    QImage output = source.copy();
    fxmanager::parallelRows(output.height(), [&](int y0, int y1) { applyBand(output, y0, y1, params); });
    if(u && u->interrupted()) return;
    fxmanager::writeImage(d, output, r);
    if (u) u->setProgress(100);
}
