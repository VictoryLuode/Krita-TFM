#pragma once

#include <functional>

#include <QImage>
#include <QRect>
#include <QString>

namespace tfm_lens_gpu {

bool render(const QImage &source, const QRect &frame, const QRect &outputRect,
            bool horizontal, double distortion, double dispersion, bool fit, bool jitter,
            QImage &output, QString &reason, QString &deviceName, const std::function<bool()> &cancelled = {});

} // namespace tfm_lens_gpu
