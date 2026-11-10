#include "fxmanager_color_range_mask.h"
#include "fxmanager_color_range_mask_algorithm.h"
#include "fxmanager_color_range_mask_widget.h"
#include "fxmanager_processing.h"
#include "tfm_pointwise_gpu.h"

#include <algorithm>
#include <cmath>

#include <QImage>

#include <filter/kis_filter_category_ids.h>
#include <kis_paint_device.h>
#include <KoColorSpace.h>
#include <KisGlobalResourcesInterface.h>
#include <KoUpdater.h>
#include <klocalizedstring.h>

namespace {

colormask::Settings settingsFrom(const KisFilterConfigurationSP &c)
{
    colormask::Settings s;
    if (!c) return s;

    const QString channel = c->getString("channel", "gray");
    if (channel == QLatin1String("r")) s.channel = colormask::Settings::Channel::Red;
    else if (channel == QLatin1String("g")) s.channel = colormask::Settings::Channel::Green;
    else if (channel == QLatin1String("b")) s.channel = colormask::Settings::Channel::Blue;
    else if (channel == QLatin1String("hue")) s.channel = colormask::Settings::Channel::Hue;
    else if (channel == QLatin1String("saturation")) s.channel = colormask::Settings::Channel::Saturation;
    else s.channel = colormask::Settings::Channel::Gray;
    s.rangeMin = colormask::clamp01(c->getDouble("range_min", 0.0));
    s.rangeMax = colormask::clamp01(c->getDouble("range_max", 1.0));
    s.softness = std::clamp(c->getDouble("softness", 0.05), 0.0, 0.5);
    s.invert = c->getBool("invert", false);
    s.preserveRgb = c->getBool("preserve_rgb", true);
    return s;
}

} // namespace

KisFilterColorRangeMask::KisFilterColorRangeMask()
    : KisFilter(id(), FiltersCategoryArtisticId, i18n("&Color Range Mask..."))
{
    setSupportsAdjustmentLayers(true);
    setColorSpaceIndependence(FULLY_INDEPENDENT);
}

KisFilterConfigurationSP KisFilterColorRangeMask::defaultConfiguration(KisResourcesInterfaceSP resourcesInterface) const
{
    auto c = factoryConfiguration(resourcesInterface);

    fxmanager::applyBuiltinDefaults(id().id(), c);
    fxmanager::applyFilterDefaults(id().id(), c); return c;
}

KisConfigWidget *KisFilterColorRangeMask::createConfigurationWidget(QWidget *parent,
                                                                   const KisPaintDeviceSP,
                                                                   bool) const
{
    return new ColorRangeMaskConfigurationWidget(id().id(), parent);
}

void KisFilterColorRangeMask::processImpl(KisPaintDeviceSP device,
                                          const QRect &applyRect,
                                          const KisFilterConfigurationSP config,
                                          KoUpdater *progressUpdater) const
{
    if (applyRect.isEmpty() || !device || (progressUpdater && progressUpdater->interrupted())) return;

    const colormask::Settings s = settingsFrom(config);

    if(fxmanager::requiresFloatProcessing(device)) {
        const auto colours=fxmanager::readEncodedImage(device,applyRect);
        if(colours.isNull()) return;
        // The colour conversion is used only to evaluate selection. Keep the
        // original colour bytes, including out-of-gamut and hidden RGB.
        const auto *space=device->colorSpace();
        QByteArray raw(applyRect.width()*applyRect.height()*space->pixelSize(),Qt::Uninitialized);
        device->readBytes(reinterpret_cast<quint8*>(raw.data()),applyRect);
        auto *dst=reinterpret_cast<quint8*>(raw.data());
        fxmanager::parallelRows(applyRect.height(),[&](int y0,int y1) {
            for(int y=y0;y<y1;++y) {
                if(progressUpdater && progressUpdater->interrupted()) return;
                for(int x=0;x<applyRect.width();++x) {
                    const int i=y*applyRect.width()+x;
                    const auto *p=colours.pixels.constData()+i*4;
                    const double factor=colormask::alphaFactor(p[0],p[1],p[2],s);
                    auto *pixel=dst+i*space->pixelSize();
                    if(factor!=1.0) space->setOpacity(pixel,space->opacityF(pixel)*factor,1);
                }
            }
        });
        if(progressUpdater && progressUpdater->interrupted()) return;
        device->writeBytes(reinterpret_cast<const quint8*>(raw.constData()),applyRect);
        fxmanager::reportBackend(id().id(),QStringLiteral("cpu"),QStringLiteral("High-depth CPU mask; original colour channels retained"));
        if(progressUpdater) progressUpdater->setProgress(100);
        return;
    }

    QImage image = device->convertToQImage(device->colorSpace()->profile(),
                                           applyRect.x(), applyRect.y(),
                                           applyRect.width(), applyRect.height());
    if (image.isNull()) return;
    image = image.convertToFormat(QImage::Format_ARGB32);
    image.detach(); // Detach before parallel scanLine writes.

    if (fxmanager::gpuRequested(id().id(),qint64(applyRect.width())*applyRect.height())) {
        tfm_pointwise_gpu::Parameters gpu;
        gpu.operation = tfm_pointwise_gpu::Operation::ColorRangeMask;
        gpu.outputRect = applyRect; gpu.channel = static_cast<int>(s.channel);
        gpu.rangeMin = float(s.rangeMin); gpu.rangeMax = float(s.rangeMax);
        gpu.softness = float(s.softness); gpu.invert = s.invert ? 1 : 0;
        QImage output; QString reason, gpuDevice;
        if (tfm_pointwise_gpu::render(image, gpu, output, reason, gpuDevice, [progressUpdater] { return progressUpdater && progressUpdater->interrupted(); })) {
            if(progressUpdater && progressUpdater->interrupted()) return;
            device->convertFromQImage(output, device->colorSpace()->profile(), applyRect.x(), applyRect.y());
            fxmanager::reportBackend(id().id(), QStringLiteral("gpu"), QString(), gpuDevice);
            if (progressUpdater) progressUpdater->setProgress(100);
            return;
        }
        if(progressUpdater && progressUpdater->interrupted()) return;
        fxmanager::reportBackend(id().id(), QStringLiteral("cpu"), reason);
    } else {
        fxmanager::reportBackend(id().id(), QStringLiteral("cpu"), fxmanager::cpuBackendReason(id().id(),qint64(applyRect.width())*applyRect.height()));
    }

    image.detach(); // Detach before parallel scanLine writes.
    const int height = image.height();
    const int width = image.width();
    fxmanager::parallelRows(height, [&](int y0, int y1) {
    for (int y = y0; y < y1; ++y) {
        QRgb *row = reinterpret_cast<QRgb *>(image.scanLine(y));
        for (int x = 0; x < width; ++x) {
            const QRgb p = row[x];
            row[x] = colormask::maskArgb32(p, s);
        }
    }
    });

    if(progressUpdater && progressUpdater->interrupted()) return;
    device->convertFromQImage(image, device->colorSpace()->profile(),
                              applyRect.x(), applyRect.y());
    if (progressUpdater) progressUpdater->setProgress(100);
}
