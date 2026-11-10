#pragma once

#include <functional>

#include <QImage>
#include <QRect>
#include <QString>

namespace tfm_halation_gpu {

struct Parameters {
    // Region actually processed on the GPU; must include a halo of at least
    // radius pixels around outputRect so the highlight gather stays valid.
    QRect srcRect;
    QRect outputRect;
    float threshold = 0.75f;   // 0..1 luminance above which a pixel glows
    float radius = 24.0f;      // gather radius in pixels
    float intensity = 1.0f;    // glow gain
    float tintShift = 1.0f;    // 0 = neutral glow, 1 = full glow colour
    float blend = 1.0f;
    int samples = 32;          // quality: gather taps (8..64)
    float colorR = 1.0f;       // glow colour, 0..1 per channel
    float colorG = 0.42f;
    float colorB = 0.22f;
    bool channelR = true;      // switch glow off for a channel
    bool channelG = true;
    bool channelB = true;
    int mode = 0;              // 0 = custom colour, 1 = channel mix
};

// Processes the whole srcRect and returns an image of the same size.
// Returns false without modifying output when Vulkan is unavailable.
bool render(const QImage &source, const Parameters &parameters,
            QImage &output, QString &reason, QString &deviceName, const std::function<bool()> &cancelled = {});

} // namespace tfm_halation_gpu
