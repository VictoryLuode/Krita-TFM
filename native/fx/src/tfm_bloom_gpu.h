#pragma once

#include "tfm_processing.h"

#include <functional>

#include <QImage>
#include <QString>

namespace tfm_bloom_gpu {

bool renderLegacy(const QImage &source, const QRect &outputRect, double threshold,
                  int radius, double strength, QImage &output, QString &reason,
                  QString &deviceName, const std::function<bool()> &cancelled = {});

bool renderLegacyFloat(const tfm::EncodedRgbaImage &source, const QRect &outputRect,
                       double threshold, int radius, double strength,
                       tfm::EncodedRgbaImage &output, QString &reason, QString &deviceName,
                       const std::function<bool()> &cancelled = {});

bool renderDiffuse(const QImage &source, double threshold, int radius, double strength,
                   double softness, QImage &output, QString &reason, QString &deviceName,
                   const std::function<bool()> &cancelled = {});

bool renderDiffuseFloat(const tfm::EncodedRgbaImage &source, double threshold, int radius,
                        double strength, double softness, tfm::EncodedRgbaImage &output,
                        QString &reason, QString &deviceName,
                        const std::function<bool()> &cancelled = {});

} // namespace tfm_bloom_gpu
