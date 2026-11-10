#pragma once

#include <functional>

#include <QImage>
#include <QRect>
#include <QString>

namespace tfm_pointwise_gpu {

enum class Operation {
    FilmGrain = 0,
    Vignette = 1,
    ColorRangeMask = 2,
    ColorTemperature = 3,
    Vibrance = 4,
    LightLeaks = 5,
    LightPatch = 6,
};

struct Parameters {
    Operation operation = Operation::FilmGrain;
    QRect outputRect;
    QRect frame;
    float amount = 0.0f;
    float size = 1.0f;
    float seed = 0.0f;
    float factor = 1.0f;
    float feather = 0.4f;
    float roundness = 1.0f;
    float scaleX = 0.8f;
    float scaleY = 0.8f;
    float offsetX = 0.0f;
    float offsetY = 0.0f;
    float angle = 0.0f;
    float rangeMin = 0.0f;
    float rangeMax = 1.0f;
    float softness = 0.05f;
    int channel = 0;
    int invert = 0;
    int monochrome = 1;

    // Generic slots used by Color Temperature, Vibrance, Light Leaks and Light Patch so new
    // pointwise operations do not need another buffer-layout change.
    float p0 = 0.0f;
    float p1 = 0.0f;
    float p2 = 0.0f;
    float p3 = 0.0f;
    float p4 = 0.0f;
    float p5 = 0.0f;
    float p6 = 0.0f;
    float p7 = 0.0f;
    int mode = 0;
};

// Processes an ARGB32 QImage without changing its alpha for Film Grain/Vignette.
// Returns false without modifying output when Vulkan is unavailable or inputs are unsupported.
bool render(const QImage &source, const Parameters &parameters,
            QImage &output, QString &reason, QString &deviceName, const std::function<bool()> &cancelled = {});

} // namespace tfm_pointwise_gpu
