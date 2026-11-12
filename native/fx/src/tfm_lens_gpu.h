#pragma once

#include <functional>

#include "tfm_processing.h"

#include <QImage>
#include <QRect>
#include <QString>

namespace tfm_lens_gpu {

bool render(const QImage &source, const QRect &frame, const QRect &outputRect,
            bool horizontal, double distortion, double dispersion, bool fit, bool jitter,
            QImage &output, QString &reason, QString &deviceName, const std::function<bool()> &cancelled = {});

bool renderFloat(const tfm::EncodedRgbaImage &source, const QRect &frame, const QRect &outputRect,
                 bool horizontal, double distortion, double dispersion, bool fit, bool jitter,
                 tfm::EncodedRgbaImage &output, QString &reason, QString &deviceName,
                 const std::function<bool()> &cancelled = {});

} // namespace tfm_lens_gpu
