#include "tfm_flare_gpu.h"
#include "fxmanager_vulkan.h"
#include "tfm_flare_spv.h"

#include <QDebug>
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <new>
#include <vector>

namespace tfm_flare_gpu {
namespace {
struct ShaderParameters {
    int width;
    int height;
    int mode;
    int sourceCount;
    float threshold;
    float span;          // named span, not length: GLSL reserves length()
    float intensity;
    float tintShift;
    float decay;
    float aspect;
    float blend;
    float padding;
    float sources[32]; // 8 * (x, y, strength, radius)
};
static_assert(sizeof(ShaderParameters) == 176, "Flare shader parameter layout mismatch");
static_assert(offsetof(ShaderParameters, sources) == 48, "Flare sources offset mismatch");
static_assert(offsetof(ShaderParameters, mode) == 8, "Flare mode offset mismatch");
}

QVector<FlareSource> detectSources(const QImage &source, double threshold, int maxSources)
{
    QVector<FlareSource> found;
    if (source.isNull() || maxSources <= 0) return found;
    const int step = std::max(1, std::max(source.width(), source.height()) / 192);
    const int gridW = std::max(1, source.width() / step);
    const int gridH = std::max(1, source.height() / step);
    std::vector<float> luminance(std::size_t(gridW) * gridH, 0.0f);
    for (int gy = 0; gy < gridH; ++gy) {
        for (int gx = 0; gx < gridW; ++gx) {
            const int px = std::min(source.width() - 1, gx * step);
            const int py = std::min(source.height() - 1, gy * step);
            const QRgb p = reinterpret_cast<const QRgb *>(source.constScanLine(py))[px];
            luminance[std::size_t(gy) * gridW + gx] =
                float((0.2126 * qRed(p) + 0.7152 * qGreen(p) + 0.0722 * qBlue(p)) / 255.0);
        }
    }
    struct Candidate { float value; int gx; int gy; };
    std::vector<Candidate> candidates;
    for (int gy = 0; gy < gridH; ++gy) {
        for (int gx = 0; gx < gridW; ++gx) {
            const float value = luminance[std::size_t(gy) * gridW + gx];
            if (value <= threshold) continue;
            bool isPeak = true;
            for (int ny = std::max(0, gy - 1); ny <= std::min(gridH - 1, gy + 1) && isPeak; ++ny) {
                for (int nx = std::max(0, gx - 1); nx <= std::min(gridW - 1, gx + 1); ++nx) {
                    if (nx == gx && ny == gy) continue;
                    if (luminance[std::size_t(ny) * gridW + nx] > value) { isPeak = false; break; }
                }
            }
            if (isPeak) candidates.push_back({value, gx, gy});
        }
    }
    std::sort(candidates.begin(), candidates.end(),
              [](const Candidate &a, const Candidate &b) { return a.value > b.value; });
    const double range = std::max(1e-4, 1.0 - threshold);
    for (const Candidate &c : candidates) {
        if (found.size() >= maxSources) break;
        const float x = float((c.gx + 0.5) / double(gridW));
        const float y = float((c.gy + 0.5) / double(gridH));
        // Skip peaks that land almost on top of one already accepted.
        bool tooClose = false;
        for (const FlareSource &existing : found) {
            if (std::abs(existing.x - x) < 0.05f && std::abs(existing.y - y) < 0.05f) { tooClose = true; break; }
        }
        if (tooClose) continue;
        FlareSource source;
        source.x = x;
        source.y = y;
        source.strength = float(std::clamp((c.value - threshold) / range, 0.0, 1.0));
        source.radius = 0.06f;
        found.push_back(source);
    }
    if (found.isEmpty()) {
        // Always give the effects something to work with: aim at the brightest
        // cell so a dim image still produces a faint, well-placed flare.
        int bestIndex = 0;
        for (std::size_t i = 1; i < luminance.size(); ++i) {
            if (luminance[i] > luminance[bestIndex]) bestIndex = int(i);
        }
        FlareSource source;
        source.x = float((bestIndex % gridW + 0.5) / double(gridW));
        source.y = float((bestIndex / gridW + 0.5) / double(gridH));
        source.strength = 0.25f;
        source.radius = 0.06f;
        found.push_back(source);
    }
    return found;
}

bool render(const QImage &source, const Parameters &p, QImage &output,
            QString &reason, QString &deviceName)
{
    reason.clear();
    deviceName.clear();
    if (qEnvironmentVariableIntValue("TFM_VULKAN_DISABLE") != 0) {
        reason = QStringLiteral("Vulkan disabled by TFM_VULKAN_DISABLE");
        return false;
    }
    if (source.isNull() || source.format() != QImage::Format_ARGB32 || p.srcRect.isEmpty()
        || source.width() != p.srcRect.width() || source.height() != p.srcRect.height()) {
        reason = QStringLiteral("Flare GPU requires a dense ARGB32 source region");
        return false;
    }
    ShaderParameters params{};
    params.width = source.width();
    params.height = source.height();
    params.mode = int(p.mode);
    params.threshold = p.threshold;
    params.span = p.length;
    params.intensity = p.intensity;
    params.tintShift = p.tintShift;
    params.decay = p.decay;
    params.aspect = p.aspect;
    params.blend = p.blend;
    params.padding = 0.0f;
    const int count = std::min(8, int(p.sources.size()));
    params.sourceCount = std::max(1, count);
    for (int i = 0; i < count; ++i) {
        params.sources[i * 4 + 0] = p.sources[i].x;
        params.sources[i * 4 + 1] = p.sources[i].y;
        params.sources[i * 4 + 2] = p.sources[i].strength;
        params.sources[i * 4 + 3] = p.sources[i].radius;
    }
    const std::size_t bytes = std::size_t(source.width()) * source.height() * sizeof(std::uint32_t);
    try {
        static FxManagerVulkan *instance = new FxManagerVulkan();
        FxManagerVulkan &vulkan = *instance;
        FxManagerVulkan::Dispatch dispatch;
        dispatch.parametersBinding = 2;
        dispatch.groupsX = (std::uint32_t(source.width()) + 15u) / 16u;
        dispatch.groupsY = (std::uint32_t(source.height()) + 15u) / 16u;
        std::vector<std::uint8_t> result;
        std::string error;
        if (!vulkan.initialize(&error)) { reason = QString::fromStdString(error); return false; }
        if (!vulkan.dispatch(std::vector<std::uint32_t>(std::begin(kFlareSpv), std::end(kFlareSpv)),
                             source.constBits(), bytes, &params, sizeof(params), bytes,
                             dispatch, result, &error)) {
            reason = QString::fromStdString(error);
            return false;
        }
        if (result.size() != bytes) { reason = QStringLiteral("Flare GPU returned an incomplete image"); return false; }
        output = QImage(source.size(), QImage::Format_ARGB32);
        std::memcpy(output.bits(), result.data(), bytes);
        deviceName = QString::fromStdString(vulkan.deviceName());
        qInfo().noquote() << "TFM Vulkan flare dispatch completed mode:" << params.mode
                          << "sources:" << params.sourceCount << "device:" << deviceName;
        return true;
    } catch (const std::bad_alloc &) {
        reason = QStringLiteral("Flare GPU buffer allocation failed");
        return false;
    }
}
} // namespace tfm_flare_gpu
