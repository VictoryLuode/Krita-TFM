#include "tfm_motion_gpu.h"
#include "fxmanager_vulkan.h"
#include "tfm_motion_spv.h"

#include <QDebug>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iterator>
#include <new>
#include <utility>
#include <vector>

namespace tfm_motion_gpu {
namespace {
struct Parameters {
    std::int32_t storedX, storedY, storedW, storedH;
    std::int32_t readX, readY, readW, readH;
    std::int32_t outX, outY, outW, outH;
    std::int32_t frameX, frameY, frameW, frameH;
    float centerX, centerY, angle, factor;
    std::int32_t circular, samples, reserved0, reserved1;
    float defaultR, defaultG, defaultB, defaultA;
};
static_assert(sizeof(Parameters) == 112, "Motion shader parameter layout mismatch");
static_assert(offsetof(Parameters, centerX) == 64, "Motion shader float layout mismatch");
static_assert(offsetof(Parameters, defaultR) == 96, "Motion shader default pixel layout mismatch");
constexpr std::uint64_t memoryBudget = 128ULL * 1024 * 1024;
}

bool render(const fxmanager::FloatRgbaImage &source, const QRect &stored,
            const fxmanager::FloatRgbaImage &defaultImage, const QRect &read,
            const QRect &outputRect, const QRect &frame, bool circular,
            double centerX, double centerY, double angle, double factor,
            fxmanager::FloatRgbaImage &output, QString &reason, QString &deviceName, const std::function<bool()> &cancelled)
{
    deviceName.clear();
    if (qEnvironmentVariableIntValue("TFM_VULKAN_DISABLE") != 0) {
        reason = QStringLiteral("Vulkan disabled by TFM_VULKAN_DISABLE");
        return false;
    }
    // The CPU zero-factor formula can retain double-precision cancellation
    // residuals at fully transparent pixels. Preserve that special case.
    if (!circular && factor == 0.0) {
        reason = QStringLiteral("Zero-factor Zoom uses CPU precision semantics");
        return false;
    }
    if (source.isNull() || stored.isEmpty() || source.width != stored.width()
        || source.height != stored.height() || defaultImage.isNull()) {
        reason = QStringLiteral("Dense snapshot unavailable");
        return false;
    }
    if (outputRect.isEmpty() || read.isEmpty() || !std::isfinite(centerX)
        || !std::isfinite(centerY) || !std::isfinite(angle) || !std::isfinite(factor)) {
        reason = QStringLiteral("Invalid motion geometry");
        return false;
    }
    const std::uint64_t inputBytes = std::uint64_t(source.width) * source.height * 4 * sizeof(float);
    const std::uint64_t outputBytes = std::uint64_t(outputRect.width()) * outputRect.height() * 4 * sizeof(float);
    if (inputBytes > memoryBudget || outputBytes > memoryBudget
        || inputBytes + outputBytes + sizeof(Parameters) > memoryBudget) {
        reason = QStringLiteral("Motion buffers exceed 128 MiB budget");
        return false;
    }
    // Single precision cannot preserve unit pixel coordinates arbitrarily far
    // from the origin. Keep that case on the existing double precision path.
    constexpr double maxCoordinate = 1048576.0;
    if (std::abs(centerX) > maxCoordinate || std::abs(centerY) > maxCoordinate
        || std::abs(double(read.left())) > maxCoordinate || std::abs(double(read.top())) > maxCoordinate
        || std::abs(double(read.right())) > maxCoordinate || std::abs(double(read.bottom())) > maxCoordinate
        || std::abs(double(outputRect.left())) > maxCoordinate || std::abs(double(outputRect.top())) > maxCoordinate
        || std::abs(double(outputRect.right())) > maxCoordinate || std::abs(double(outputRect.bottom())) > maxCoordinate) {
        reason = QStringLiteral("Motion coordinates exceed GPU precision range");
        return false;
    }
    const float *d = defaultImage.pixels.constData();
    const Parameters params{
        stored.x(), stored.y(), stored.width(), stored.height(),
        read.x(), read.y(), read.width(), read.height(),
        outputRect.x(), outputRect.y(), outputRect.width(), outputRect.height(),
        frame.x(), frame.y(), frame.width(), frame.height(),
        float(centerX), float(centerY), float(angle), float(factor),
        circular ? 1 : 0, (circular ? angle == 0.0 : factor == 0.0) ? 1 : 200, 0, 0,
        d[0], d[1], d[2], d[3]
    };
    try {
        // The Vulkan singleton is process-scoped. Khronos loader/driver teardown
        // during Windows DLL detach runs under the loader lock and can crash.
        // Keep it alive until the OS releases process resources at exit.
        static FxManagerVulkan *vulkanInstance = new FxManagerVulkan();
        FxManagerVulkan &vulkan = *vulkanInstance;
        static const std::vector<std::uint32_t> shader(std::begin(kMotionSpv), std::end(kMotionSpv));
        FxManagerVulkan::Dispatch dispatch;
        dispatch.cancelled = cancelled;
        dispatch.parametersBinding = 2;
        dispatch.groupsX = (std::uint32_t(outputRect.width()) + 15) / 16;
        dispatch.groupsY = (std::uint32_t(outputRect.height()) + 15) / 16;
        std::vector<std::uint8_t> bytes;
        const auto outcome = vulkan.dispatchResult(shader, source.pixels.constData(), std::size_t(inputBytes),
                             &params, sizeof(params), std::size_t(outputBytes), dispatch, bytes);
        if (!outcome) {
            reason = QString::fromStdString(outcome.message);
            return false;
        }
        if (bytes.size() != outputBytes) {
            reason = QStringLiteral("Motion GPU returned an incomplete image");
            return false;
        }
        fxmanager::FloatRgbaImage result;
        result.width = outputRect.width();
        result.height = outputRect.height();
        result.linearHdr = true;
        result.pixels.resize(int(outputBytes / sizeof(float)));
        std::memcpy(result.pixels.data(), bytes.data(), std::size_t(outputBytes));
        output = std::move(result);
        deviceName = QString::fromStdString(vulkan.deviceName());
        reason.clear();
        qInfo().noquote() << "TFM Vulkan motion dispatch completed:" << (circular ? "Circular" : "Zoom")
                          << outputRect << "device:" << QString::fromStdString(vulkan.deviceName());
        return true;
    } catch (const std::bad_alloc &) {
        reason = QStringLiteral("Motion GPU buffer allocation failed");
        return false;
    }
}
} // namespace tfm_motion_gpu
