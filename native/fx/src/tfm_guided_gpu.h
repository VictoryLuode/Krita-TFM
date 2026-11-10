#pragma once

#include <functional>

#include "fxmanager_guided_color_match.h"
#include <QImage>
#include <QString>

namespace tfm_guided_gpu {

bool render(const QImage &source, const fxmanager::guided::Lut &lut,
            QImage &output, QString &reason, QString &deviceName, const std::function<bool()> &cancelled = {});

} // namespace tfm_guided_gpu
