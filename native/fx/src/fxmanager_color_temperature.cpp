#include "fxmanager_color_temperature.h"
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

void applyBand(QImage &image, int y0, int y1, double temperature, double tint, double blend, bool preserve)
{
    const auto gains=temperatureGains(temperature,tint);
    for(int y=y0;y<y1;++y) {
        auto *row=reinterpret_cast<QRgb*>(image.scanLine(y));
        for(int x=0;x<image.width();++x) {
            const auto pixel=row[x];
            const auto out=fxmanager::pointwise::temperature({qRed(pixel)/255.0,qGreen(pixel)/255.0,qBlue(pixel)/255.0},gains,blend,preserve,true);
            row[x]=qRgba(int(std::lround(out.r*255.0)),int(std::lround(out.g*255.0)),int(std::lround(out.b*255.0)),qAlpha(pixel));
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

    fxmanager::applyBuiltinDefaults(id().id(), c);
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
    if (r.isEmpty() || !d || (u && u->interrupted())) return;
    const double temperature = std::clamp(c ? c->getDouble("temperature", kReferenceKelvin) : kReferenceKelvin, 2000.0, 12000.0);
    const double tint = std::clamp(c ? c->getDouble("tint", 0.0) : 0.0, -100.0, 100.0);
    const double blend = std::clamp(c ? c->getDouble("blend", 1.0) : 1.0, 0.0, 1.0);
    const bool preserve = (c ? c->getDouble("preserve_luminance", 1.0) : 1.0) > 0.5;

    if (blend == 0.0 || (temperature == kReferenceKelvin && tint == 0.0)) { if(u) u->setProgress(100); return; }
    if (fxmanager::requiresFloatProcessing(d)) {
        const auto gains=temperatureGains(temperature,tint);
        fxmanager::transformEncoded(d,r,id().id(),u,[&](float *p,int,int) {
            const auto out=fxmanager::pointwise::temperature({p[0],p[1],p[2]},gains,blend,preserve,false);
            p[0]=float(out.r); p[1]=float(out.g); p[2]=float(out.b);
        });
        return;
    }

    const QImage source = fxmanager::readImage(d, r);
    if (source.isNull()) return;
    if (fxmanager::gpuRequested(id().id(),qint64(r.width())*r.height())) {
        tfm_pointwise_gpu::Parameters gpu;
        gpu.operation = tfm_pointwise_gpu::Operation::ColorTemperature;
        gpu.outputRect = r;
        gpu.p0 = float(temperature);
        gpu.p1 = float(tint);
        gpu.p2 = float(blend);
        gpu.p3 = preserve ? 1.0f : 0.0f;
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
    fxmanager::parallelRows(output.height(), [&](int y0, int y1) {
        applyBand(output, y0, y1, temperature, tint, blend, preserve);
    });
    if(u && u->interrupted()) return;
    fxmanager::writeImage(d, output, r);
    if (u) u->setProgress(100);
}
