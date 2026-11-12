#include "tfm_flare_gpu.h"
#include "tfm_processing.h"
#include "tfm_vulkan.h"
#include "tfm_flare_spv.h"
#include "tfm_flare_float_spv.h"

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

template <typename Sample>
QVector<FlareSource> detectSourcesImpl(int width,int height,double threshold,int maxSources,Sample sample)
{
    QVector<FlareSource> found;
    if (width<=0 || height<=0 || maxSources <= 0) return found;
    const int step = std::max(1, std::max(width, height) / 192);
    const int gridW = std::max(1, width / step);
    const int gridH = std::max(1, height / step);
    std::vector<float> luminance(std::size_t(gridW) * gridH, 0.0f);
    for (int gy = 0; gy < gridH; ++gy) {
        for (int gx = 0; gx < gridW; ++gx) {
            const int px = std::min(width - 1, gx * step);
            const int py = std::min(height - 1, gy * step);
            luminance[std::size_t(gy) * gridW + gx] = sample(px,py);
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
        // Refine peak to a luminance-weighted centroid in a 3x3 grid neighbourhood.
        double sumW = 0.0, sumX = 0.0, sumY = 0.0;
        for (int ny = std::max(0, c.gy - 1); ny <= std::min(gridH - 1, c.gy + 1); ++ny) {
            for (int nx = std::max(0, c.gx - 1); nx <= std::min(gridW - 1, c.gx + 1); ++nx) {
                const double w = std::max(0.0, double(luminance[std::size_t(ny) * gridW + nx]) - threshold);
                sumW += w;
                sumX += (nx + 0.5) * w;
                sumY += (ny + 0.5) * w;
            }
        }
        const float x = float((sumW > 1e-6 ? sumX / sumW : (c.gx + 0.5)) / double(gridW));
        const float y = float((sumW > 1e-6 ? sumY / sumW : (c.gy + 0.5)) / double(gridH));
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
        // Brighter sources throw a slightly larger core halo.
        source.radius = float(0.045 + 0.05 * source.strength);
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

QVector<FlareSource> detectSources(const QImage &source,double threshold,int maxSources)
{
    return detectSourcesImpl(source.width(),source.height(),threshold,maxSources,[&](int x,int y) {
        const auto p=reinterpret_cast<const QRgb*>(source.constScanLine(y))[x];
        return float((0.2126*qRed(p)+0.7152*qGreen(p)+0.0722*qBlue(p))/255.0);
    });
}
QVector<FlareSource> detectSources(const tfm::EncodedRgbaImage &source,double threshold,int maxSources)
{
    if(source.isNull()) return {};
    return detectSourcesImpl(source.width,source.height,threshold,maxSources,[&](int x,int y) {
        const auto *p=source.pixels.constData()+4*(y*source.width+x);
        return float(0.2126*p[0]+0.7152*p[1]+0.0722*p[2]);
    });
}

bool render(const QImage &source, const Parameters &p, QImage &output,
            QString &reason, QString &deviceName, const std::function<bool()> &cancelled)
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
        static TfmVulkan *instance = new TfmVulkan();
        TfmVulkan &vulkan = *instance;
        TfmVulkan::Dispatch dispatch;
        dispatch.cancelled = cancelled;
        dispatch.parametersBinding = 2;
        dispatch.groupsX = (std::uint32_t(source.width()) + 15u) / 16u;
        dispatch.groupsY = (std::uint32_t(source.height()) + 15u) / 16u;
        std::vector<std::uint8_t> result;
        const auto outcome = vulkan.dispatchResult(std::vector<std::uint32_t>(std::begin(kFlareSpv), std::end(kFlareSpv)),
                             source.constBits(), bytes, &params, sizeof(params), bytes,
                             dispatch, result);
        if (!outcome) {
            reason = QString::fromStdString(outcome.message);
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

bool renderFloat(const tfm::EncodedRgbaImage &source, const Parameters &p,
                 tfm::EncodedRgbaImage &output, QString &reason, QString &deviceName,
                 const std::function<bool()> &cancelled)
{
    reason.clear();
    deviceName.clear();
    if (qEnvironmentVariableIntValue("TFM_VULKAN_DISABLE") != 0) {
        reason = QStringLiteral("Vulkan disabled by TFM_VULKAN_DISABLE");
        return false;
    }
    if (source.isNull() || p.srcRect.isEmpty()
        || source.width != p.srcRect.width() || source.height != p.srcRect.height()) {
        reason = QStringLiteral("Flare float GPU requires a dense EncodedRgbaImage source region");
        return false;
    }
    const std::uint64_t memoryBudget = tfm::gpuMemoryBudgetBytes();
    const std::uint64_t bytes = std::uint64_t(source.width) * source.height * 4ull * sizeof(float);
    if (bytes == 0 || bytes > memoryBudget || bytes * 2 + sizeof(ShaderParameters) > memoryBudget) {
        reason = tfm::gpuMemoryBudgetExceeded(QStringLiteral("Flare float buffers"));
        return false;
    }
    ShaderParameters params{};
    params.width = source.width;
    params.height = source.height;
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
    try {
        static TfmVulkan *instance = new TfmVulkan();
        TfmVulkan &vulkan = *instance;
        TfmVulkan::Dispatch dispatch;
        dispatch.cancelled = cancelled;
        dispatch.parametersBinding = 2;
        dispatch.groupsX = (std::uint32_t(source.width) + 15u) / 16u;
        dispatch.groupsY = (std::uint32_t(source.height) + 15u) / 16u;
        std::vector<std::uint8_t> result;
        const auto outcome = vulkan.dispatchResult(
            std::vector<std::uint32_t>(std::begin(kFlareFloatSpv), std::end(kFlareFloatSpv)),
            source.pixels.constData(), std::size_t(bytes), &params, sizeof(params),
            std::size_t(bytes), dispatch, result);
        if (!outcome) {
            reason = QString::fromStdString(outcome.message);
            return false;
        }
        if (result.size() != bytes) {
            reason = QStringLiteral("Flare float GPU returned an incomplete image");
            return false;
        }
        tfm::EncodedRgbaImage out;
        out.width = source.width;
        out.height = source.height;
        out.pixels.resize(int(bytes / sizeof(float)));
        std::memcpy(out.pixels.data(), result.data(), std::size_t(bytes));
        output = std::move(out);
        deviceName = QString::fromStdString(vulkan.deviceName());
        qInfo().noquote() << "TFM Vulkan flare float dispatch completed mode:" << params.mode
                          << "sources:" << params.sourceCount << "device:" << deviceName;
        return true;
    } catch (const std::bad_alloc &) {
        reason = QStringLiteral("Flare float GPU buffer allocation failed");
        return false;
    }
}
} // namespace tfm_flare_gpu
