#pragma once

#include <QImage>
#include <QRect>
#include <QVector>
#include <functional>

#include <kis_paint_device.h>
#include <filter/kis_filter_configuration.h>

class KoUpdater;

namespace tfm {

struct FloatRgbaImage {
    int width = 0;
    int height = 0;
    // Bridge buffers are always unassociated F32 linear sRGB (Rec.709).
    // This flag describes the buffer, never the source storage depth.
    bool linearHdr = true;
    QVector<float> pixels; // width * height * 4; HDR/negative RGB are retained

    bool isNull() const { return width <= 0 || height <= 0 || qint64(pixels.size()) < qint64(width) * height * 4; }
};

// Explicitly encoded colour, distinct from both the linear bridge and raw AOVs.
struct EncodedRgbaImage {
    int width = 0, height = 0;
    QVector<float> pixels;
    bool isNull() const { return width <= 0 || height <= 0 || qint64(pixels.size()) < qint64(width)*height*4; }
    EncodedRgbaImage copy(const QRect &rect) const;
};
struct RawFloatRgbaData {
    int width=0,height=0;
    QVector<float> pixels;
    bool isNull() const { return width<=0 || height<=0 || qint64(pixels.size())<qint64(width)*height*4; }
};
bool requiresFloatProcessing(KisPaintDeviceSP device);
EncodedRgbaImage readEncodedImage(KisPaintDeviceSP device, const QRect &rect);
bool writeEncodedImage(KisPaintDeviceSP device, const EncodedRgbaImage &image, const QRect &rect);
// Stages the full result before publishing; callback coordinates are global.
bool transformEncoded(KisPaintDeviceSP device, const QRect &rect, const QString &filter,
                      KoUpdater *updater, const std::function<void(float *, int, int)> &transform);

void applyFilterDefaults(const QString &filterId, KisFilterConfigurationSP config);
void applyBuiltinDefaults(const QString &filterId, KisFilterConfigurationSP config);
// True when TFM/settings.json has no enabled_filters list, or lists this id.
bool filterEnabled(const QString &filterId);
// Per-filter backend from TFM/settings.json filter_backends, else global backend.
// Auto applies measured area thresholds to lightweight filters. An explicit
// GPU request bypasses these thresholds; CPU remains a live failure fallback.
bool gpuRequested(const QString &filterId = QString(), qint64 pixels = -1);
QString cpuBackendReason(const QString &filterId, qint64 pixels);
void reportBackend(const QString &filter, const QString &actual, const QString &reason,
                   const QString &device = QString());

QImage readImage(KisPaintDeviceSP device, const QRect &rect);
void writeImage(KisPaintDeviceSP device, const QImage &image, const QRect &rect);
FloatRgbaImage readFloatImage(KisPaintDeviceSP device, const QRect &rect);
// Raw RGBA F32 when the device already stores float data channels (Position/Depth AOVs).
// Other storage returns an empty result; raw data never undergoes an ICC transform.
RawFloatRgbaData readDataFloatRgba(KisPaintDeviceSP device, const QRect &rect);
// Reports validation/conversion failure; true means writeBytes returned.
// Does not provide rollback if the device write itself fails.
bool writeFloatImage(KisPaintDeviceSP device, const FloatRgbaImage &image, const QRect &rect);
void parallelRows(int rows, const std::function<void(int, int)> &body);

double deterministicNoise(int x, int y, int seed, int channel = 0);

// Krita resource directory (kritarc ResourceDirectory).
// Settings: TFM/settings.json. Legacy locations are read-only
// migration sources. Background removal models/runtime live below
// TFM/background-removal/.
QString resourceDirectory();
QString settingsPath();

} // namespace tfm
