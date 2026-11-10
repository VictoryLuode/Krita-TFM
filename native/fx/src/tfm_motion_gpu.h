#pragma once

#include <functional>

#include "fxmanager_processing.h"
#include <QString>

namespace tfm_motion_gpu {

// Input is the immutable old-data snapshot in global device coordinates.
// Returns false without modifying output on unsupported input/dispatch failure.
bool render(const fxmanager::FloatRgbaImage &source, const QRect &stored,
            const fxmanager::FloatRgbaImage &defaultImage, const QRect &read,
            const QRect &outputRect, const QRect &frame, bool circular,
            double centerX, double centerY, double angle, double factor,
            fxmanager::FloatRgbaImage &output, QString &reason, QString &deviceName, const std::function<bool()> &cancelled = {});

} // namespace tfm_motion_gpu
