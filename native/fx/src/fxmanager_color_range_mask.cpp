#include "fxmanager_color_range_mask.h"
#include "fxmanager_color_range_mask_algorithm.h"
#include "fxmanager_color_range_mask_widget.h"
#include "fxmanager_processing.h"

#include <algorithm>
#include <cmath>

#include <QImage>

#include <filter/kis_filter_category_ids.h>
#include <kis_paint_device.h>
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
    c->setProperty("channel", "gray");
    c->setProperty("range_min", 0.0);
    c->setProperty("range_max", 1.0);
    c->setProperty("softness", 0.05);
    c->setProperty("invert", false);
    c->setProperty("preserve_rgb", true);
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
    if (applyRect.isEmpty()) return;

    const colormask::Settings s = settingsFrom(config);

    QImage image = device->convertToQImage(device->colorSpace()->profile(),
                                           applyRect.x(), applyRect.y(),
                                           applyRect.width(), applyRect.height());
    if (image.isNull()) return;
    image = image.convertToFormat(QImage::Format_ARGB32);
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

    device->convertFromQImage(image, device->colorSpace()->profile(),
                              applyRect.x(), applyRect.y());
    if (progressUpdater) progressUpdater->setProgress(100);
}
