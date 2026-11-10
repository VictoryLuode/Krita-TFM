#include "tfm_lens_gpu.h"
#include "fxmanager_vulkan.h"
#include "tfm_lens_spv.h"

#include <QDebug>
#include <cstdint>
#include <cmath>
#include <cstring>
#include <new>
#include <vector>

namespace tfm_lens_gpu {
namespace {
struct ShaderParameters {
    std::int32_t sourceW, sourceH;
    std::int32_t frameX, frameY, frameW, frameH;
    std::int32_t outputX, outputY, outputW, outputH;
    std::int32_t horizontal, fit, jitter;
    float distortion, dispersion;
};
static_assert(sizeof(ShaderParameters) == 60, "Lens shader parameter layout mismatch");
static_assert(offsetof(ShaderParameters, distortion) == 52, "Lens shader float layout mismatch");
}

bool render(const QImage &source, const QRect &frame, const QRect &outputRect,
            bool horizontal, double distortion, double dispersion, bool fit, bool jitter,
            QImage &output, QString &reason, QString &deviceName, const std::function<bool()> &cancelled)
{
    reason.clear();
    deviceName.clear();
    if (qEnvironmentVariableIntValue("TFM_VULKAN_DISABLE") != 0) {
        reason = QStringLiteral("Vulkan disabled by TFM_VULKAN_DISABLE");
        return false;
    }
    if (source.isNull() || source.format() != QImage::Format_ARGB32
        || frame.isEmpty() || outputRect.isEmpty()
        || source.width() != frame.width() || source.height() != frame.height()
        || !std::isfinite(distortion) || !std::isfinite(dispersion)) {
        reason = QStringLiteral("Lens GPU requires a dense full-frame ARGB32 source");
        return false;
    }
    if (outputRect.width() <= 0 || outputRect.height() <= 0
        || outputRect.width() > 32768 || outputRect.height() > 32768) {
        reason = QStringLiteral("Lens GPU output geometry is unsupported");
        return false;
    }
    ShaderParameters params{};
    params.sourceW = source.width();
    params.sourceH = source.height();
    params.frameX = frame.x();
    params.frameY = frame.y();
    params.frameW = frame.width();
    params.frameH = frame.height();
    params.outputX = outputRect.x();
    params.outputY = outputRect.y();
    params.outputW = outputRect.width();
    params.outputH = outputRect.height();
    params.horizontal = horizontal ? 1 : 0;
    params.fit = fit ? 1 : 0;
    params.jitter = jitter ? 1 : 0;
    params.distortion = float(distortion);
    params.dispersion = float(dispersion);
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
        static const std::vector<std::uint32_t> shader(std::begin(kLensSpv), std::end(kLensSpv));
        const auto outcome = vulkan.dispatchResult(shader, source.constBits(), inputBytes, &params, sizeof(params),
                             outputBytes, dispatch, result);
        if (!outcome) {
            reason = QString::fromStdString(outcome.message);
            return false;
        }
        if (result.size() != outputBytes) {
            reason = QStringLiteral("Lens GPU returned an incomplete image");
            return false;
        }
        output = QImage(outputRect.size(), QImage::Format_ARGB32);
        std::memcpy(output.bits(), result.data(), outputBytes);
        deviceName = QString::fromStdString(vulkan.deviceName());
        return true;
    } catch (const std::bad_alloc &) {
        reason = QStringLiteral("Lens GPU buffer allocation failed");
        return false;
    }
}
} // namespace tfm_lens_gpu
