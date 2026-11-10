#pragma once

#include <functional>

#include <QImage>
#include <QRect>
#include <QString>
#include <QVector>

namespace tfm { struct EncodedRgbaImage; }

namespace tfm_flare_gpu {

enum class Mode {
    GhostFlare = 0,
    Anamorphic = 1,
    LightRays = 2,
};

struct FlareSource {
    float x = 0.0f;         // normalised 0..1 across the frame
    float y = 0.0f;
    float strength = 1.0f;  // 0..1, how far above the threshold
    float radius = 0.06f;   // normalised ghost/halo radius
};

struct Parameters {
    // Flare sampling reads the whole frame, so callers pass the entire image as
    // srcRect and only crop the result.
    QRect srcRect;
    QRect outputRect;
    Mode mode = Mode::GhostFlare;
    float threshold = 0.85f;
    float length = 0.35f;
    float intensity = 1.0f;
    float tintShift = 1.0f;
    float decay = 3.0f;
    float aspect = 0.02f;
    float blend = 1.0f;
    QVector<FlareSource> sources;
};

// Finds up to maxSources bright points above threshold, spread out so a single
// large highlight does not fill every slot. Shared by all three flare filters
// so the GPU and CPU paths agree on where the light comes from.
QVector<FlareSource> detectSources(const QImage &source, double threshold, int maxSources);
QVector<FlareSource> detectSources(const tfm::EncodedRgbaImage &source, double threshold, int maxSources);

// Processes the whole srcRect and returns an image of the same size.
// Returns false without modifying output when Vulkan is unavailable.
bool render(const QImage &source, const Parameters &parameters,
            QImage &output, QString &reason, QString &deviceName, const std::function<bool()> &cancelled = {});

} // namespace tfm_flare_gpu
