#include "fxmanager_bloom.h"
#include "fxmanager_filter_widget.h"
#include "fxmanager_processing.h"
#include "tfm_bloom_gpu.h"
#include "bloom_algorithm.h"

#include <algorithm>
#include <QImage>
#include <filter/kis_filter_category_ids.h>
#include <filter/kis_filter_configuration.h>
#include <kis_paint_device.h>
#include <kis_painter.h>
#include <KisGlobalResourcesInterface.h>
#include <KoUpdater.h>
#include <klocalizedstring.h>

namespace {
int radiusFor(const KisFilterConfigurationSP &c) { return fxmanager::bloom::boundedRadius(int(c ? c->getDouble("radius", 12) : 12)); }
bool diffusionEnabled(const KisFilterConfigurationSP &c) { return c && c->getDouble("diffusion", 0.0) >= 0.5; }
}
KisFilterBloom::KisFilterBloom() : KisFilter(id(), FiltersCategoryArtisticId, i18n("&Bloom...")) { setSupportsAdjustmentLayers(true); setColorSpaceIndependence(FULLY_INDEPENDENT); }
KisFilterConfigurationSP KisFilterBloom::defaultConfiguration(KisResourcesInterfaceSP r) const { auto c=factoryConfiguration(r);c->setProperty("threshold",.7);c->setProperty("radius",12.0);c->setProperty("strength",.65);c->setProperty("diffusion",1.0);c->setProperty("softness",0.0);fxmanager::applyFilterDefaults(id().id(), c); return c; }
QRect KisFilterBloom::neededRect(const QRect &r,const KisFilterConfigurationSP c,int)const { const int margin=diffusionEnabled(c)?fxmanager::bloom::halo(radiusFor(c)):radiusFor(c); return r.adjusted(-margin,-margin,margin,margin); }
QRect KisFilterBloom::changedRect(const QRect &r,const KisFilterConfigurationSP c,int l)const{return neededRect(r,c,l);}
KisConfigWidget *KisFilterBloom::createConfigurationWidget(QWidget *p,const KisPaintDeviceSP,bool)const{return new FxManagerFilterWidget(id().id(),{{"threshold",i18n("Threshold"),0,1,.7,.01,2},{"radius",i18n("Radius"),1,64,12,1,0},{"strength",i18n("Strength"),0,2,.65,.01,2},{"diffusion",i18n("Diffusion"),0,1,1,1,0},{"softness",i18n("Softness"),0,1,0,.01,2}},p);}
void KisFilterBloom::processImpl(KisPaintDeviceSP d,const QRect &rect,const KisFilterConfigurationSP c,KoUpdater *u)const
{
    if(rect.isEmpty())return;
    const double threshold=c?c->getDouble("threshold",.7):.7;
    const int radius=radiusFor(c);
    const double strength=c?c->getDouble("strength",.65):.65;
    const bool diffusion=diffusionEnabled(c);
    const int margin=diffusion?fxmanager::bloom::halo(radius):radius;
    QRect read=rect.adjusted(-margin,-margin,margin,margin);
    if(!diffusion) { read=read.intersected(d->exactBounds()); if(read.isEmpty())read=rect; }
    // Neighbouring chunks may already have written into d in this transaction.
    // Read its transaction baseline; without a transaction Krita uses current data.
    KisPaintDeviceSP input = new KisPaintDevice(d->colorSpace());
    input->prepareClone(d);
    KisPainter::copyAreaOptimizedOldData(read.topLeft(), d, input, read);
    const QImage source=fxmanager::readImage(input,read);
    if(source.isNull())return;
    QImage out;
    const QRect localOutput(rect.topLeft() - read.topLeft(), rect.size());
    if (diffusion) {
        fxmanager::reportBackend(id().id(), QStringLiteral("cpu"), QStringLiteral("Bloom diffusion remains CPU-only"));
        out=fxmanager::bloom::diffuse(source,threshold,radius,strength,c ? c->getDouble("softness",0.0) : 0.0);
    } else {
        if (fxmanager::gpuRequested(id().id())) {
            QImage gpuOutput;
            QString reason;
            QString gpuDevice;
            if (tfm_bloom_gpu::renderLegacy(source, localOutput, threshold, radius, strength,
                                             gpuOutput, reason, gpuDevice)) {
                fxmanager::reportBackend(id().id(), QStringLiteral("gpu"), QString(), gpuDevice);
                fxmanager::writeImage(d, gpuOutput, rect);
                if (u) u->setProgress(100);
                return;
            }
            fxmanager::reportBackend(id().id(), QStringLiteral("cpu"), reason);
        } else {
            fxmanager::reportBackend(id().id(), QStringLiteral("cpu"), QStringLiteral("CPU selected"));
        }
        out=source.copy();
        fxmanager::parallelRows(source.height(),[&](int y0,int y1){fxmanager::bloom::legacyBand(source,out,y0,y1,threshold,radius,strength);});
    }
    fxmanager::writeImage(d,out.copy(localOutput),rect);
    if(u)u->setProgress(100);
}
