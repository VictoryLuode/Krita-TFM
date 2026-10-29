#pragma once

#include <QImage>
#include <QRect>
#include <functional>

#include <kis_paint_device.h>
#include <filter/kis_filter_configuration.h>

namespace fxmanager {

void applyFilterDefaults(const QString &filterId, KisFilterConfigurationSP config);

QImage readImage(KisPaintDeviceSP device, const QRect &rect);
void writeImage(KisPaintDeviceSP device, const QImage &image, const QRect &rect);
void parallelRows(int rows, const std::function<void(int, int)> &body);

double deterministicNoise(int x, int y, int seed, int channel = 0);

// Krita resource directory (kritarc ResourceDirectory).
// Settings: TFM/settings.json. Legacy locations are read-only
// migration sources. Background removal models/runtime live below
// TFM/background-removal/.
QString resourceDirectory();
QString settingsPath();

} // namespace fxmanager
