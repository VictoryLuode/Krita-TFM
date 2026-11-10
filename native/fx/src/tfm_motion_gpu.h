#pragma once

#include <functional>

#include "tfm_processing.h"
#include <QString>

namespace tfm_motion_gpu {

// Input is the immutable old-data snapshot in global device coordinates.
// Returns false without modifying output on unsupported input/dispatch failure.
bool render(const tfm::FloatRgbaImage &source, const QRect &stored,
            const tfm::FloatRgbaImage &defaultImage, const QRect &read,
            const QRect &outputRect, const QRect &frame, bool circular,
            double centerX, double centerY, double angle, double factor,
            tfm::FloatRgbaImage &output, QString &reason, QString &deviceName, const std::function<bool()> &cancelled = {});

} // namespace tfm_motion_gpu
