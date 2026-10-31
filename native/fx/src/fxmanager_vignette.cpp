#include "fxmanager_vignette.h"
#include "fxmanager_vignette_widget.h"
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

KisFilterVignette::KisFilterVignette()
    : KisFilter(id(), FiltersCategoryArtisticId, i18n("&Vignette..."))
{
    setSupportsAdjustmentLayers(true);
    setColorSpaceIndependence(FULLY_INDEPENDENT);
    // Vignette uses one global centre. Krita's patch threading would create
    // one independent centre per patch, so keep host tiling disabled and
    // parallelise rows inside the complete-frame operation instead.
    setSupportsThreading(false);
}

KisFilterConfigurationSP KisFilterVignette::defaultConfiguration(KisResourcesInterfaceSP r) const
{
    auto c = factoryConfiguration(r);
    c->setProperty("factor", 1.0);
    c->setProperty("feather", 0.4);
    c->setProperty("corner_roundness", 1.0);
    c->setProperty("scale_x", 0.8);
    c->setProperty("scale_y", 0.8);
    c->setProperty("offset_x", 0.0);
    c->setProperty("offset_y", 0.0);
    c->setProperty("angle", 0.0);
    fxmanager::applyFilterDefaults(id().id(), c); return c;
}

KisConfigWidget *KisFilterVignette::createConfigurationWidget(QWidget *p, const KisPaintDeviceSP, bool) const
{
    return new VignetteConfigurationWidget(id().id(), p);
}

void KisFilterVignette::processImpl(KisPaintDeviceSP d, const QRect &r,
                                    const KisFilterConfigurationSP c, KoUpdater *u) const
{
    if (r.isEmpty() || !d) return;
    const double factor = std::clamp(c ? c->getDouble("factor", c->getDouble("intensity", 1.0)) : 1.0, 0.0, 1.0);
    const double feather = std::clamp(c ? c->getDouble("feather", c->getDouble("smoothness", 0.4)) : 0.4, 0.0, 1.0);
    const double roundness = std::clamp(c ? c->getDouble("corner_roundness", c->getDouble("roundness", 1.0)) : 1.0, 0.0, 1.0);
    const double scaleX = std::clamp(c ? c->getDouble("scale_x", 0.8) : 0.8, 0.0001, 4.0);
    const double scaleY = std::clamp(c ? c->getDouble("scale_y", 0.8) : 0.8, 0.0001, 4.0);
    const double offsetX = c ? c->getDouble("offset_x", 0.0) : 0.0;
    const double offsetY = c ? c->getDouble("offset_y", 0.0) : 0.0;
    const double angle = c ? c->getDouble("angle", 0.0) : 0.0;

    QRect frame = d->defaultBounds()->bounds();
    if (frame.isEmpty()) frame = d->extent();
    if (frame.isEmpty()) frame = r;
    const QRect outputRect = r.intersected(frame);
    if (outputRect.isEmpty()) return;

    // Vignette is pointwise: only the current output area is needed. The
    // centre and aspect ratio still come from the complete frame.
    const QImage source = fxmanager::readImage(d, outputRect);
    if (source.isNull()) return;
    if (fxmanager::gpuRequested()) {
        tfm_pointwise_gpu::Parameters gpu;
        gpu.operation = tfm_pointwise_gpu::Operation::Vignette;
        gpu.outputRect = outputRect; gpu.frame = frame;
        gpu.factor = float(factor); gpu.feather = float(feather); gpu.roundness = float(roundness);
        gpu.scaleX = float(scaleX); gpu.scaleY = float(scaleY); gpu.offsetX = float(offsetX);
        gpu.offsetY = float(offsetY); gpu.angle = float(angle);
        QImage output; QString reason, device;
        if (tfm_pointwise_gpu::render(source, gpu, output, reason, device)) {
            fxmanager::writeImage(d, output, outputRect);
            fxmanager::reportBackend(id().id(), QStringLiteral("gpu"), QString(), device);
            if (u) u->setProgress(100);
            return;
        }
        fxmanager::reportBackend(id().id(), QStringLiteral("cpu"), reason);
    } else {
        fxmanager::reportBackend(id().id(), QStringLiteral("cpu"), QStringLiteral("CPU selected"));
    }
    QImage output(outputRect.size(), QImage::Format_ARGB32);

    const double width = std::max(1, frame.width());
    const double height = std::max(1, frame.height());
    const double angleRadians = angle * 3.14159265358979323846 / 180.0;
    const double cosAngle = std::cos(angleRadians);
    const double sinAngle = std::sin(angleRadians);

    fxmanager::parallelRows(output.height(), [&](int y0, int y1) {
        for (int y = y0; y < y1; ++y) {
            QRgb *row = reinterpret_cast<QRgb *>(output.scanLine(y));
            const double imageY = outputRect.y() - frame.y() + y + 0.5;
            const QRgb *sourceRow = reinterpret_cast<const QRgb *>(source.constScanLine(y));
            for (int x = 0; x < output.width(); ++x) {
                const double imageX = outputRect.x() - frame.x() + x + 0.5;
                const double normalizedX = (imageX / width) - 0.5 - offsetX;
                const double normalizedY = (imageY / height) - 0.5 - offsetY;
                const double rotatedX = (normalizedX * cosAngle + normalizedY * sinAngle) / scaleX;
                const double rotatedY = (-normalizedX * sinAngle + normalizedY * cosAngle) / scaleY;
                const double centeredX = std::abs(rotatedX) * 2.0;
                const double centeredY = std::abs(rotatedY) * 2.0;
                const double squareDistance = std::max(centeredX, centeredY);
                const double ellipseDistance = std::hypot(centeredX, centeredY);
                const double distance = squareDistance * (1.0 - roundness) + ellipseDistance * roundness;
                const double edge = feather <= 1e-6
                    ? (distance >= 1.0 ? 1.0 : 0.0)
                    : std::clamp((distance - (1.0 - feather)) / feather, 0.0, 1.0);
                const double mask = edge * factor;
                const double factorOut = 1.0 - mask;
                const QRgb pixel = sourceRow[x];
                row[x] = qRgba(int(qRed(pixel) * factorOut), int(qGreen(pixel) * factorOut),
                               int(qBlue(pixel) * factorOut), qAlpha(pixel));
            }
        }
    });

    fxmanager::writeImage(d, output, outputRect);
    if (u) u->setProgress(100);
}
