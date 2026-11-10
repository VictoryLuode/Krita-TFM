#include "tfm_guided_gpu.h"
#include "tfm_vulkan.h"
#include "tfm_guided_lut_spv.h"

#include <cmath>
#include <cstdint>
#include <cstring>
#include <new>
#include <vector>

namespace tfm_guided_gpu {
namespace {
struct ShaderParameters {
    std::int32_t sourceW, sourceH, outputW, outputH;
    float lut[tfm::guided::Lut::Size * tfm::guided::Lut::Size * tfm::guided::Lut::Size * 3];
};
static_assert(offsetof(ShaderParameters, lut) == 16, "Guided LUT parameter layout mismatch");
}

bool render(const QImage &source, const tfm::guided::Lut &lut,
            QImage &output, QString &reason, QString &deviceName, const std::function<bool()> &cancelled)
{
    reason.clear();
    deviceName.clear();
    if (qEnvironmentVariableIntValue("TFM_VULKAN_DISABLE") != 0) {
        reason = QStringLiteral("Vulkan disabled by TFM_VULKAN_DISABLE");
        return false;
    }
    if (source.isNull() || source.format() != QImage::Format_ARGB32 || !lut.valid) {
        reason = QStringLiteral("Guided GPU requires a dense ARGB32 image and valid LUT");
        return false;
    }
    ShaderParameters params{};
    params.sourceW = source.width(); params.sourceH = source.height();
    params.outputW = source.width(); params.outputH = source.height();
    std::copy(lut.values.begin(), lut.values.end(), std::begin(params.lut));
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
        const auto outcome = vulkan.dispatchResult(std::vector<std::uint32_t>(std::begin(kGuidedLutSpv), std::end(kGuidedLutSpv)),
                             source.constBits(), bytes, &params, sizeof(params), bytes,
                             dispatch, result);
        if (!outcome) {
            reason = QString::fromStdString(outcome.message); return false;
        }
        if (result.size() != bytes) { reason = QStringLiteral("Guided GPU returned an incomplete image"); return false; }
        output = QImage(source.size(), QImage::Format_ARGB32);
        std::memcpy(output.bits(), result.data(), bytes);
        deviceName = QString::fromStdString(vulkan.deviceName());
        return true;
    } catch (const std::bad_alloc &) {
        reason = QStringLiteral("Guided GPU buffer allocation failed");
        return false;
    }
}
} // namespace tfm_guided_gpu
