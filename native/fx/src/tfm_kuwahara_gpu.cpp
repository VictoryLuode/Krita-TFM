#include "tfm_kuwahara_gpu.h"
#include "tfm_vulkan.h"
#include "tfm_kuwahara_spv.h"

#include <QDebug>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <new>
#include <vector>

namespace tfm_kuwahara_gpu {
namespace {
struct ShaderParameters {
    int width;
    int height;
    int radius;
    int padding;
};
static_assert(sizeof(ShaderParameters) == 16, "Kuwahara shader parameter layout mismatch");
static_assert(offsetof(ShaderParameters, radius) == 8, "Kuwahara radius offset mismatch");
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
        reason = QStringLiteral("Kuwahara GPU requires a dense ARGB32 source region");
        return false;
    }
    ShaderParameters params{};
    params.width = source.width();
    params.height = source.height();
    params.radius = p.radius;
    params.padding = 0;
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
        const auto outcome = vulkan.dispatchResult(std::vector<std::uint32_t>(std::begin(kKuwaharaSpv), std::end(kKuwaharaSpv)),
                             source.constBits(), bytes, &params, sizeof(params), bytes,
                             dispatch, result);
        if (!outcome) {
            reason = QString::fromStdString(outcome.message);
            return false;
        }
        if (result.size() != bytes) { reason = QStringLiteral("Kuwahara GPU returned an incomplete image"); return false; }
        output = QImage(source.size(), QImage::Format_ARGB32);
        std::memcpy(output.bits(), result.data(), bytes);
        deviceName = QString::fromStdString(vulkan.deviceName());
        qInfo().noquote() << "TFM Vulkan Kuwahara dispatch completed device:" << deviceName;
        return true;
    } catch (const std::bad_alloc &) {
        reason = QStringLiteral("Kuwahara GPU buffer allocation failed");
        return false;
    }
}
} // namespace tfm_kuwahara_gpu
