#include "tfm_bloom_gpu.h"
#include "fxmanager_vulkan.h"
#include "tfm_bloom_legacy_spv.h"

#include <cmath>
#include <cstdint>
#include <cstring>
#include <new>
#include <vector>

namespace tfm_bloom_gpu {
namespace {
struct ShaderParameters {
    std::int32_t sourceW, sourceH, outputX, outputY, outputW, outputH, radius, step;
    float threshold, strength;
};
static_assert(sizeof(ShaderParameters) == 40, "Bloom shader parameter layout mismatch");
static_assert(offsetof(ShaderParameters, threshold) == 32, "Bloom shader float layout mismatch");
}

bool renderLegacy(const QImage &source, const QRect &outputRect, double threshold,
                  int radius, double strength, QImage &output, QString &reason,
                  QString &deviceName, const std::function<bool()> &cancelled)
{
    reason.clear();
    deviceName.clear();
    if (qEnvironmentVariableIntValue("TFM_VULKAN_DISABLE") != 0) {
        reason = QStringLiteral("Vulkan disabled by TFM_VULKAN_DISABLE");
        return false;
    }
    if (source.isNull() || source.format() != QImage::Format_ARGB32 || source.isNull()
        || outputRect.isEmpty() || outputRect.x() < 0 || outputRect.y() < 0
        || outputRect.right() >= source.width() || outputRect.bottom() >= source.height()
        || radius < 1 || radius > 64 || !std::isfinite(threshold) || !std::isfinite(strength)) {
        reason = QStringLiteral("Bloom legacy GPU requires a dense ARGB32 source and bounded output");
        return false;
    }
    ShaderParameters params{};
    params.sourceW = source.width(); params.sourceH = source.height();
    params.outputX = outputRect.x(); params.outputY = outputRect.y();
    params.outputW = outputRect.width(); params.outputH = outputRect.height();
    params.radius = radius; params.step = std::max(1, radius / 8);
    params.threshold = float(threshold); params.strength = float(strength);
    const std::size_t inputBytes = std::size_t(source.width()) * source.height() * sizeof(std::uint32_t);
    const std::size_t outputBytes = std::size_t(outputRect.width()) * outputRect.height() * sizeof(std::uint32_t);
    try {
        static FxManagerVulkan *instance = new FxManagerVulkan();
        FxManagerVulkan &vulkan = *instance;
        FxManagerVulkan::Dispatch dispatch;
        dispatch.cancelled = cancelled;
        dispatch.parametersBinding = 2;
        dispatch.groupsX = (std::uint32_t(outputRect.width()) + 15u) / 16u;
        dispatch.groupsY = (std::uint32_t(outputRect.height()) + 15u) / 16u;
        std::vector<std::uint8_t> result;
        const auto outcome = vulkan.dispatchResult(std::vector<std::uint32_t>(std::begin(kBloomLegacySpv), std::end(kBloomLegacySpv)),
                             source.constBits(), inputBytes, &params, sizeof(params), outputBytes,
                             dispatch, result);
        if (!outcome) {
            reason = QString::fromStdString(outcome.message); return false;
        }
        if (result.size() != outputBytes) { reason = QStringLiteral("Bloom GPU returned an incomplete image"); return false; }
        output = QImage(outputRect.size(), QImage::Format_ARGB32);
        std::memcpy(output.bits(), result.data(), outputBytes);
        deviceName = QString::fromStdString(vulkan.deviceName());
        return true;
    } catch (const std::bad_alloc &) {
        reason = QStringLiteral("Bloom GPU buffer allocation failed");
        return false;
    }
}
} // namespace tfm_bloom_gpu
