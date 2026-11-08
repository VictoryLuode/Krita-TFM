#include "fxmanager_guided_color_match_filter.h"
#include "fxmanager_guided_color_match.h"
#include "fxmanager_processing.h"
#include "tfm_guided_gpu.h"
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
    // Keep host tiling so the canvas can refresh while Vulkan works one patch
    // at a time. The out-of-process worker serialises dispatches itself.
    setSupportsThreading(true);
    setSupportsAdjustmentLayers(true);
}
KisFilterConfigurationSP KisFilterGuidedColorMatch::defaultConfiguration(KisResourcesInterfaceSP resources) const
{
    auto config=factoryConfiguration(resources);
    config->setProperty("guided_version",1);
    config->setProperty("align_brightness",1.0);
    config->setProperty("match_strength",1.0);
    config->setProperty("luminance",0.0);
    config->setProperty("chroma",1.0);
    config->setProperty("keep_local",1.0);
    config->setProperty("match_local",0.0);
    config->setProperty("shadow_color",1.0);
    config->setProperty("highlight_warmth",1.0);
    config->setProperty("neutral_protection",0.0);
    config->setProperty("smoothness",0.35);
    config->setProperty("guided_pairs",QByteArray());
    config->setProperty("guided_look",QByteArray());
    config->setProperty("guided_lightness",QByteArray());
    config->setProperty("guided_lut",QByteArray());
    config->setProperty("guided_lut_valid",false);
    fxmanager::applyFilterDefaults(id().id(), config); return config;
}
KisConfigWidget *KisFilterGuidedColorMatch::createConfigurationWidget(QWidget *parent,const KisPaintDeviceSP device,bool) const
{
    return new fxmanager::guided::GuidedWidget(id().id(),[device] {
        if(!device) return QImage();
        const QRect bounds=device->exactBounds();
        if(bounds.isEmpty()) return QImage();
        // The widget keeps a 768px preview. Reading the full layer here runs on
        // the GUI thread and stalls the canvas fence.
        QSize size=bounds.size();
        size.scale(768,768,Qt::KeepAspectRatio);
        const KisPaintDeviceSP thumb=device->createThumbnailDevice(qMax(1,size.width()),qMax(1,size.height()),bounds);
        if(!thumb) return QImage();
        const QRect thumbBounds=thumb->exactBounds();
        if(thumbBounds.isEmpty()) return QImage();
        return fxmanager::readImage(thumb,thumbBounds).rgbSwapped();
    },parent);
}
void KisFilterGuidedColorMatch::processImpl(KisPaintDeviceSP device,const QRect &rect,
    const KisFilterConfigurationSP config,KoUpdater *updater) const
{
    if(!device || rect.isEmpty() || !config || !config->getBool("guided_lut_valid",false)) return;
    // One grid per stored grade. Tiles of the same apply reuse it.
    const QByteArray lookBytes=fxmanager::guided::inflateStored(config->getProperty("guided_look").toByteArray());
    const QByteArray legacyBytes=fxmanager::guided::inflateStored(config->getProperty("guided_lut").toByteArray());
    const QByteArray pairBytes=config->getProperty("guided_pairs").toByteArray();
    const QByteArray lightBytes=config->getProperty("guided_lightness").toByteArray();
    const double chroma=config->getDouble("chroma",1.0);
    const double strength=config->getDouble("match_strength",1.0);
    const double smoothness=config->getDouble("smoothness",0.35);
    const bool align=config->getDouble("align_brightness",1.0)>0.0;
    QByteArray key;
    {
        QDataStream stream(&key,QIODevice::WriteOnly);
        stream.setVersion(QDataStream::Qt_5_15);
        stream.setFloatingPointPrecision(QDataStream::DoublePrecision);
        stream<<lookBytes<<legacyBytes<<pairBytes<<lightBytes<<chroma<<strength<<smoothness<<quint8(align?1:0);
    }
    thread_local QByteArray cachedKey;
    thread_local fxmanager::guided::Lut cachedLut;
    if(key!=cachedKey || !cachedLut.valid) {
        fxmanager::guided::LightnessStats sourceStats,referenceStats;
        fxmanager::guided::decodeLightness(lightBytes,sourceStats,referenceStats);
        cachedLut=fxmanager::guided::lutForGuidedStorage(
            lookBytes,legacyBytes,fxmanager::guided::decodePairs(pairBytes),
            chroma,strength,smoothness,align,sourceStats,referenceStats);
        cachedKey=key;
    }
    if(!cachedLut.valid) return;
    const auto &lut=cachedLut;
    // The current host returns native ARGB32; undo the legacy helper swap.
    const QImage source=fxmanager::readImage(device,rect).rgbSwapped();
    if(source.isNull()) return;
    QImage output;
    QString gpuReason, gpuDevice;
    const bool wantGpu = fxmanager::gpuRequested(id().id());
    if (wantGpu && tfm_guided_gpu::render(source, lut, output, gpuReason, gpuDevice)) {
        fxmanager::reportBackend(id().id(), QStringLiteral("gpu"), QString(), gpuDevice);
    } else {
        fxmanager::reportBackend(id().id(), QStringLiteral("cpu"),
            wantGpu ? gpuReason : QStringLiteral("CPU selected"));
        output = source.copy();
        uchar *bits=output.bits();
        const qsizetype stride=output.bytesPerLine();
        const int width=output.width();
        // Host already tiles this filter; stay single-threaded inside a patch.
        for(int y=0;y<output.height();++y) {
            QRgb *row=reinterpret_cast<QRgb*>(bits+y*stride);
            for(int x=0;x<width;++x) {
                const QRgb pixel=row[x];
                if(!qAlpha(pixel)) continue;
                const QColor mapped=lut.sample(QColor::fromRgba(pixel));
                row[x]=qRgba(mapped.red(),mapped.green(),mapped.blue(),qAlpha(pixel));
            }
        }
    }
    fxmanager::writeImage(device,output.rgbSwapped(),rect);
    if(updater) updater->setProgress(100);
}
