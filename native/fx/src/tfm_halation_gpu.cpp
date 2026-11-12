#include "tfm_halation_gpu.h"
#include "tfm_processing.h"
#include "tfm_vulkan.h"
#include "tfm_halation_spv.h"
#include "tfm_halation_float_spv.h"

#include <QDebug>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <new>
#include <vector>

namespace tfm_halation_gpu {
namespace {
struct ShaderParameters {
    int width;
    int height;
    float threshold;
    float radius;
    float intensity;
    float tintShift;
    float blend;
    int samples;
    float colorR;
    float colorG;
    float colorB;
    int channelR;
    int channelG;
    int channelB;
    int mode;
};
static_assert(sizeof(ShaderParameters) == 60, "Halation shader parameter layout mismatch");
static_assert(offsetof(ShaderParameters, threshold) == 8, "Halation threshold offset mismatch");
static_assert(offsetof(ShaderParameters, samples) == 28, "Halation samples offset mismatch");
static_assert(offsetof(ShaderParameters, colorR) == 32, "Halation colour offset mismatch");
static_assert(offsetof(ShaderParameters, channelR) == 44, "Halation channel offset mismatch");
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
        reason = QStringLiteral("Halation GPU requires a dense ARGB32 source region");
        return false;
    }
    ShaderParameters params{};
    params.width = source.width();
    params.height = source.height();
    params.threshold = p.threshold;
    params.radius = p.radius;
    params.intensity = p.intensity;
    params.tintShift = p.tintShift;
    params.blend = p.blend;
    params.samples = p.samples;
    params.colorR = p.colorR;
    params.colorG = p.colorG;
    params.colorB = p.colorB;
    params.channelR = p.channelR ? 1 : 0;
    params.channelG = p.channelG ? 1 : 0;
    params.channelB = p.channelB ? 1 : 0;
    params.mode = p.mode;
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
        const auto outcome = vulkan.dispatchResult(std::vector<std::uint32_t>(std::begin(kHalationSpv), std::end(kHalationSpv)),
                             source.constBits(), bytes, &params, sizeof(params), bytes,
                             dispatch, result);
        if (!outcome) {
            reason = QString::fromStdString(outcome.message);
            return false;
        }
        if (result.size() != bytes) { reason = QStringLiteral("Halation GPU returned an incomplete image"); return false; }
        output = QImage(source.size(), QImage::Format_ARGB32);
        std::memcpy(output.bits(), result.data(), bytes);
        deviceName = QString::fromStdString(vulkan.deviceName());
        qInfo().noquote() << "TFM Vulkan halation dispatch completed device:" << deviceName;
        return true;
    } catch (const std::bad_alloc &) {
        reason = QStringLiteral("Halation GPU buffer allocation failed");
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
        reason = QStringLiteral("Halation float GPU requires a dense EncodedRgbaImage source region");
        return false;
    }
    const std::uint64_t memoryBudget = tfm::gpuMemoryBudgetBytes();
    const std::uint64_t bytes = std::uint64_t(source.width) * source.height * 4ull * sizeof(float);
    if (bytes == 0 || bytes > memoryBudget || bytes * 2 + sizeof(ShaderParameters) > memoryBudget) {
        reason = tfm::gpuMemoryBudgetExceeded(QStringLiteral("Halation float buffers"));
        return false;
    }
    ShaderParameters params{};
    params.width = source.width;
    params.height = source.height;
    params.threshold = p.threshold;
    params.radius = p.radius;
    params.intensity = p.intensity;
    params.tintShift = p.tintShift;
    params.blend = p.blend;
    params.samples = p.samples;
    params.colorR = p.colorR;
    params.colorG = p.colorG;
    params.colorB = p.colorB;
    params.channelR = p.channelR ? 1 : 0;
    params.channelG = p.channelG ? 1 : 0;
    params.channelB = p.channelB ? 1 : 0;
    params.mode = p.mode;
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
            std::vector<std::uint32_t>(std::begin(kHalationFloatSpv), std::end(kHalationFloatSpv)),
            source.pixels.constData(), std::size_t(bytes), &params, sizeof(params),
            std::size_t(bytes), dispatch, result);
        if (!outcome) {
            reason = QString::fromStdString(outcome.message);
            return false;
        }
        if (result.size() != bytes) {
            reason = QStringLiteral("Halation float GPU returned an incomplete image");
            return false;
        }
        tfm::EncodedRgbaImage out;
        out.width = source.width;
        out.height = source.height;
        out.pixels.resize(int(bytes / sizeof(float)));
        std::memcpy(out.pixels.data(), result.data(), std::size_t(bytes));
        output = std::move(out);
        deviceName = QString::fromStdString(vulkan.deviceName());
        return true;
    } catch (const std::bad_alloc &) {
        reason = QStringLiteral("Halation float GPU buffer allocation failed");
        return false;
    }
}
} // namespace tfm_halation_gpu
