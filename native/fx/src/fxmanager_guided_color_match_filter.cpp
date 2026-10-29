#include "fxmanager_guided_color_match_filter.h"
#include "fxmanager_guided_color_match.h"
#include "fxmanager_processing.h"
#include <KoUpdater.h>
#include <filter/kis_filter_category_ids.h>
#include <filter/kis_filter_configuration.h>
#include <KisGlobalResourcesInterface.h>
#include <kis_config_widget.h>
#include "fxmanager_guided_widget.h"

KisFilterGuidedColorMatch::KisFilterGuidedColorMatch()
    : KisFilter(id(),FiltersCategoryColorId,i18n("&Guided Color Match..."))
{
    setColorSpaceIndependence(FULLY_INDEPENDENT);
    setSupportsThreading(false);
    setSupportsAdjustmentLayers(true);
}
KisFilterConfigurationSP KisFilterGuidedColorMatch::defaultConfiguration(KisResourcesInterfaceSP resources) const
{
    auto config=factoryConfiguration(resources);
    config->setProperty("guided_version",1);
    config->setProperty("match_strength",1.0);
    config->setProperty("luminance",0.0);
    config->setProperty("chroma",1.0);
    config->setProperty("shadow_color",1.0);
    config->setProperty("highlight_warmth",1.0);
    config->setProperty("neutral_protection",0.0);
    config->setProperty("smoothness",0.35);
    config->setProperty("guided_pairs",QByteArray());
    config->setProperty("guided_lut",QByteArray());
    config->setProperty("guided_lut_valid",false);
    fxmanager::applyFilterDefaults(id().id(), config); return config;
}
KisConfigWidget *KisFilterGuidedColorMatch::createConfigurationWidget(QWidget *parent,const KisPaintDeviceSP device,bool) const
{
    return new fxmanager::guided::GuidedWidget(id().id(),[device] {
        return device ? fxmanager::readImage(device,device->exactBounds()).rgbSwapped() : QImage();
    },parent);
}
void KisFilterGuidedColorMatch::processImpl(KisPaintDeviceSP device,const QRect &rect,
    const KisFilterConfigurationSP config,KoUpdater *updater) const
{
    if(!device || rect.isEmpty() || !config || !config->getBool("guided_lut_valid",false)) return;
    // Cache the immutable LUT per worker; never refit during rendering.
    thread_local QByteArray cachedBytes;
    thread_local fxmanager::guided::Lut cachedLut;
    const QByteArray bytes=config->getProperty("guided_lut").toByteArray();
    if(bytes!=cachedBytes) {
        cachedLut=fxmanager::guided::decodeLut(bytes);
        cachedBytes=bytes;
    }
    if(!cachedLut.valid) return;
    const auto &lut=cachedLut;
    // The current host returns native ARGB32; undo the legacy helper swap.
    const QImage source=fxmanager::readImage(device,rect).rgbSwapped();
    if(source.isNull()) return;
    QImage output=source.copy();
    uchar *bits=output.bits();
    const qsizetype stride=output.bytesPerLine();
    const int width=output.width();
    fxmanager::parallelRows(output.height(),[&](int y0,int y1) {
        for(int y=y0;y<y1;++y) {
            QRgb *row=reinterpret_cast<QRgb*>(bits+y*stride);
            for(int x=0;x<width;++x) {
                const QRgb pixel=row[x];
                if(!qAlpha(pixel)) continue;
                const QColor mapped=lut.sample(QColor::fromRgba(pixel));
                row[x]=qRgba(mapped.red(),mapped.green(),mapped.blue(),qAlpha(pixel));
            }
        }
    });
    fxmanager::writeImage(device,output.rgbSwapped(),rect);
    if(updater) updater->setProgress(100);
}

