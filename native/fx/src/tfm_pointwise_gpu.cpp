#include "tfm_pointwise_gpu.h"
#include "fxmanager_vulkan.h"
#include "tfm_pointwise_spv.h"

#include <QDebug>
#include <cstdint>
#include <cstring>
#include <new>
#include <vector>

namespace tfm_pointwise_gpu {
namespace {
struct ShaderParameters {
    int operation, width, height, outputX, outputY, frameX, frameY, frameW, frameH;
    int channel, invert, monochrome, seed;
    float amount, size, factor, feather, roundness, scaleX, scaleY;
    float offsetX, offsetY, angle, rangeMin, rangeMax, softness;
    float p0, p1, p2, p3, p4, p5, p6, p7;
    int mode;
};
static_assert(sizeof(ShaderParameters) == 140, "Pointwise shader parameter layout mismatch");
static_assert(offsetof(ShaderParameters, amount) == 52, "Pointwise shader float layout mismatch");
static_assert(offsetof(ShaderParameters, p0) == 104, "Pointwise shader generic slot layout mismatch");
static_assert(offsetof(ShaderParameters, mode) == 136, "Pointwise shader mode layout mismatch");

int channelCode(const Parameters &p)
{
    return p.channel < 0 || p.channel > 5 ? -1 : p.channel;
}
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
    if (source.isNull() || source.format() != QImage::Format_ARGB32
        || source.width() != p.outputRect.width() || source.height() != p.outputRect.height()
        || p.outputRect.isEmpty()) {
        reason = QStringLiteral("Pointwise GPU requires a dense ARGB32 image");
        return false;
    }
    if (p.operation == Operation::ColorRangeMask && channelCode(p) < 0) {
        reason = QStringLiteral("Unsupported color-range channel");
        return false;
    }
    ShaderParameters params{};
    params.operation = static_cast<std::int32_t>(p.operation);
    params.width = source.width();
    params.height = source.height();
    params.outputX = p.outputRect.x();
    params.outputY = p.outputRect.y();
    params.frameX = p.frame.x(); params.frameY = p.frame.y();
    params.frameW = p.frame.width(); params.frameH = p.frame.height();
    params.channel = channelCode(p);
    params.invert = p.invert ? 1 : 0;
    params.monochrome = p.monochrome ? 1 : 0;
    params.seed = static_cast<std::int32_t>(p.seed);
    params.amount = p.amount; params.size = p.size; params.factor = p.factor;
    params.feather = p.feather; params.roundness = p.roundness;
    params.scaleX = p.scaleX; params.scaleY = p.scaleY;
    params.offsetX = p.offsetX; params.offsetY = p.offsetY; params.angle = p.angle;
    params.rangeMin = p.rangeMin; params.rangeMax = p.rangeMax; params.softness = p.softness;
    params.p0 = p.p0; params.p1 = p.p1; params.p2 = p.p2; params.p3 = p.p3;
    params.p4 = p.p4; params.p5 = p.p5; params.p6 = p.p6; params.p7 = p.p7;
    params.mode = p.mode;
    const std::size_t bytes = std::size_t(source.width()) * source.height() * sizeof(std::uint32_t);
    try {
        static FxManagerVulkan *instance = new FxManagerVulkan();
        FxManagerVulkan &vulkan = *instance;
        FxManagerVulkan::Dispatch dispatch;
        dispatch.cancelled = cancelled;
        dispatch.parametersBinding = 2;
        dispatch.groupsX = (std::uint32_t(source.width()) + 15u) / 16u;
        dispatch.groupsY = (std::uint32_t(source.height()) + 15u) / 16u;
        std::vector<std::uint8_t> result;
        const auto outcome = vulkan.dispatchResult(std::vector<std::uint32_t>(std::begin(kPointwiseSpv), std::end(kPointwiseSpv)),
                             source.constBits(), bytes, &params, sizeof(params), bytes,
                             dispatch, result);
        if (!outcome) {
            reason = QString::fromStdString(outcome.message); return false;
        }
        if (result.size() != bytes) { reason = QStringLiteral("Pointwise GPU returned an incomplete image"); return false; }
        output = QImage(source.size(), QImage::Format_ARGB32);
        std::memcpy(output.bits(), result.data(), bytes);
        deviceName = QString::fromStdString(vulkan.deviceName());
        qInfo().noquote() << "TFM Vulkan pointwise dispatch completed" << int(p.operation)
                          << "device:" << deviceName;
        return true;
    } catch (const std::bad_alloc &) {
        reason = QStringLiteral("Pointwise GPU buffer allocation failed");
        return false;
    }
}
} // namespace tfm_pointwise_gpu
