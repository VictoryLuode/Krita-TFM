#pragma once

#include <QImage>
#include <QRect>
#include <QString>

namespace tfm_kuwahara_gpu {

struct Parameters {
    // Region actually processed on the GPU; must include a halo of at least
    // radius pixels around outputRect so neighbourhood samples stay valid.
    QRect srcRect;
    QRect outputRect;
    int radius = 2;
};

// Processes the whole srcRect and returns an image of the same size.
// Returns false without modifying output when Vulkan is unavailable.
bool render(const QImage &source, const Parameters &parameters,
            QImage &output, QString &reason, QString &deviceName);

} // namespace tfm_kuwahara_gpu
