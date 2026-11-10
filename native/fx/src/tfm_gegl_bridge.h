#pragma once

#include <QImage>
#include <QMap>
#include <QRect>
#include <QString>
#include <QVariant>

#include "tfm_processing.h"

namespace tfm_gegl {

using ParamMap = QMap<QString, QVariant>;

struct FocusBlurParams {
    QString blurType = QStringLiteral("gaussian");
    double blurRadius = 25.0;
    double highlightFactor = 0.0;
    double highlightThresholdLow = 0.0;
    double highlightThresholdHigh = 1.0;
    QString shape = QStringLiteral("circle");
    double x = 0.5;
    double y = 0.5;
    double radius = 0.75;
    double focus = 0.25;
    double midpoint = 0.5;
    double aspectRatio = 0.0;
    double rotation = 0.0;
    bool highQuality = false;
};

bool ensureRuntime(QString *errorOut = nullptr);
QString runtimeStatusText();

// Full-buffer convenience helper (source == target == reference frame).
QImage renderRgba8(const QImage &source,
                   const QString &operation,
                   const ParamMap &params,
                   QString *errorOut = nullptr);

// Region/tile-aware float32 renderer for gegl:motion-blur-circular and gegl:motion-blur-zoom.
// `source` covers `readRect` in global coordinates; output covers `targetRect` in global coordinates.
tfm::FloatRgbaImage renderOperationRegion(const tfm::FloatRgbaImage &source,
                                                const QRect &readRect,
                                                const QRect &targetRect,
                                                const QString &operation,
                                                const ParamMap &params,
                                                QString *errorOut = nullptr);

// Region/tile-aware float32 renderer for gegl:focus-blur.
// Evaluates the focus mask over `refFrame` in global coordinates while blurring only `readRect`
// and blitting `targetRect`.
tfm::FloatRgbaImage renderFocusBlurRegion(const tfm::FloatRgbaImage &source,
                                                const QRect &readRect,
                                                const QRect &targetRect,
                                                const QRect &refFrame,
                                                const FocusBlurParams &params,
                                                QString *errorOut = nullptr);

} // namespace tfm_gegl
