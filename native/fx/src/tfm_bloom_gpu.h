#pragma once

#include <QImage>
#include <QString>

namespace tfm_bloom_gpu {

bool renderLegacy(const QImage &source, const QRect &outputRect, double threshold,
                  int radius, double strength, QImage &output, QString &reason,
                  QString &deviceName);

} // namespace tfm_bloom_gpu
