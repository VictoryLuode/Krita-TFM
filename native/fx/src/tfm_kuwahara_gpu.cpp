#include "tfm_kuwahara_gpu.h"
#include "tfm_processing.h"
#include "tfm_vulkan.h"
#include "tfm_kuwahara_spv.h"
#include "tfm_kuwahara_float_spv.h"

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
        reason = QStringLiteral("Kuwahara float GPU requires a dense EncodedRgbaImage source region");
        return false;
    }
    const std::uint64_t memoryBudget = tfm::gpuMemoryBudgetBytes();
    const std::uint64_t bytes = std::uint64_t(source.width) * source.height * 4ull * sizeof(float);
    if (bytes == 0 || bytes > memoryBudget || bytes * 2 + sizeof(ShaderParameters) > memoryBudget) {
        reason = tfm::gpuMemoryBudgetExceeded(QStringLiteral("Kuwahara float buffers"));
        return false;
    }
    ShaderParameters params{};
    params.width = source.width;
    params.height = source.height;
    params.radius = p.radius;
    params.padding = 0;
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
            std::vector<std::uint32_t>(std::begin(kKuwaharaFloatSpv), std::end(kKuwaharaFloatSpv)),
            source.pixels.constData(), std::size_t(bytes), &params, sizeof(params),
            std::size_t(bytes), dispatch, result);
        if (!outcome) {
            reason = QString::fromStdString(outcome.message);
            return false;
        }
        if (result.size() != bytes) {
            reason = QStringLiteral("Kuwahara float GPU returned an incomplete image");
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
        reason = QStringLiteral("Kuwahara float GPU buffer allocation failed");
        return false;
    }
}
} // namespace tfm_kuwahara_gpu
