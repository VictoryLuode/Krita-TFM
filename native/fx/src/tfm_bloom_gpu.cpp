#include "tfm_bloom_gpu.h"
#include "bloom_algorithm.h"
#include "tfm_processing.h"
#include "tfm_vulkan.h"
#include "tfm_bloom_legacy_spv.h"
#include "tfm_bloom_legacy_float_spv.h"
#include "tfm_bloom_extract_spv.h"
#include "tfm_bloom_extract_float_spv.h"
#include "tfm_bloom_box_spv.h"
#include "tfm_bloom_box_float_spv.h"
#include "tfm_bloom_composite_spv.h"
#include "tfm_bloom_composite_float_spv.h"

#include <cmath>
#include <cstdint>
#include <cstring>
#include <new>
#include <vector>

namespace tfm_bloom_gpu {
namespace {

struct LegacyShaderParameters {
    std::int32_t sourceW, sourceH, outputX, outputY, outputW, outputH, radius, step;
    float threshold, strength;
};
static_assert(sizeof(LegacyShaderParameters) == 40, "Bloom legacy shader parameter layout mismatch");

struct ExtractParameters {
    std::int32_t width, height, padding;
    float threshold, softness, invDenom;
};
static_assert(sizeof(ExtractParameters) == 24, "Bloom extract parameter layout mismatch");

struct BoxParameters {
    std::int32_t width, height, radius, horizontal;
};
static_assert(sizeof(BoxParameters) == 16, "Bloom box parameter layout mismatch");

struct CompositeAuxHeader {
    std::int32_t width, height, padding;
    float strength;
};
static_assert(sizeof(CompositeAuxHeader) == 16, "Bloom composite header layout mismatch");

TfmVulkan &vulkanInstance()
{
    static TfmVulkan *instance = new TfmVulkan();
    return *instance;
}

bool disabled(QString &reason)
{
    if (qEnvironmentVariableIntValue("TFM_VULKAN_DISABLE") != 0) {
        reason = QStringLiteral("Vulkan disabled by TFM_VULKAN_DISABLE");
        return true;
    }
    return false;
}

TfmVulkan::Dispatch gridFor(int width, int height)
{
    TfmVulkan::Dispatch dispatch;
    dispatch.parametersBinding = 2;
    dispatch.groupsX = (std::uint32_t(width) + 15u) / 16u;
    dispatch.groupsY = (std::uint32_t(height) + 15u) / 16u;
    return dispatch;
}

bool dispatchOne(const std::vector<std::uint32_t> &spirv, const void *input, std::size_t inputBytes,
                 const void *params, std::size_t paramsBytes, std::size_t outputBytes,
                 TfmVulkan::Dispatch dispatch, std::vector<std::uint8_t> &output, QString &reason,
                 const std::function<bool()> &cancelled)
{
    dispatch.cancelled = cancelled;
    const auto outcome = vulkanInstance().dispatchResult(spirv, input, inputBytes, params,
                                                         paramsBytes, outputBytes, dispatch, output);
    if (!outcome) {
        reason = QString::fromStdString(outcome.message);
        return false;
    }
    if (output.size() != outputBytes) {
        reason = QStringLiteral("Bloom GPU returned an incomplete buffer");
        return false;
    }
    return true;
}

std::vector<std::uint8_t> makeCompositeAux(int width, int height, double strength,
                                           const std::vector<std::uint8_t> &light)
{
    CompositeAuxHeader header{width, height, 0, float(strength)};
    std::vector<std::uint8_t> aux(sizeof(CompositeAuxHeader) + light.size());
    std::memcpy(aux.data(), &header, sizeof(header));
    std::memcpy(aux.data() + sizeof(header), light.data(), light.size());
    return aux;
}

bool diffusePipeline(const void *source, std::size_t sourceBytes, bool isFloat, int width, int height,
                     double threshold, int radius, double strength, double softness,
                     std::vector<std::uint8_t> &output, QString &reason,
                     const std::function<bool()> &cancelled)
{
    const std::uint64_t pixels = std::uint64_t(width) * height;
    const std::uint64_t lightBytes = pixels * 3u * sizeof(float);
    const std::uint64_t imageBytes = isFloat ? pixels * 4u * sizeof(float) : pixels * sizeof(std::uint32_t);
    const std::uint64_t memoryBudget = tfm::gpuMemoryBudgetBytes();
    if (pixels == 0 || lightBytes * 3u + imageBytes * 2u + 4096u > memoryBudget) {
        reason = tfm::gpuMemoryBudgetExceeded(QStringLiteral("Bloom diffusion buffers"));
        return false;
    }
  radius = tfm::bloom::boundedRadius(radius);
    threshold = std::clamp(threshold, 0.0, 1.0);
    softness = std::clamp(softness, 0.0, 1.0);
    ExtractParameters extract{width, height, 0, float(threshold), float(softness),
                              float(1.0 / std::max(0.001, 1.0 - threshold))};
    std::vector<std::uint32_t> extractSpv;
    std::vector<std::uint32_t> boxSpv;
    std::vector<std::uint32_t> compositeSpv;
    if (isFloat) {
        extractSpv.assign(std::begin(kBloomExtractFloatSpv), std::end(kBloomExtractFloatSpv));
        boxSpv.assign(std::begin(kBloomBoxFloatSpv), std::end(kBloomBoxFloatSpv));
        compositeSpv.assign(std::begin(kBloomCompositeFloatSpv), std::end(kBloomCompositeFloatSpv));
    } else {
        extractSpv.assign(std::begin(kBloomExtractSpv), std::end(kBloomExtractSpv));
        boxSpv.assign(std::begin(kBloomBoxSpv), std::end(kBloomBoxSpv));
        compositeSpv.assign(std::begin(kBloomCompositeSpv), std::end(kBloomCompositeSpv));
    }
    std::vector<std::uint8_t> lightA(lightBytes), lightB(lightBytes);
    auto dispatch = gridFor(width, height);
    if (!dispatchOne(extractSpv, source, sourceBytes, &extract, sizeof(extract), lightBytes,
                     dispatch, lightA, reason, cancelled)) {
        return false;
    }
    // Match CPU multi-scale diffusion: grow the box radius each level and
    // accumulate weighted glow into lightB, then composite from lightB.
    std::vector<std::uint8_t> lightAccum(lightBytes, 0);
    constexpr float weights[tfm::bloom::blurPasses] = {0.45f, 0.35f, 0.20f};
    for (int level = 0; level < tfm::bloom::blurPasses; ++level) {
        const int levelR = tfm::bloom::levelRadius(radius, level);
        BoxParameters boxH{width, height, levelR, 1};
        if (!dispatchOne(boxSpv, lightA.data(), lightBytes, &boxH, sizeof(boxH), lightBytes,
                         dispatch, lightB, reason, cancelled)) {
            return false;
        }
        BoxParameters boxV{width, height, levelR, 0};
        if (!dispatchOne(boxSpv, lightB.data(), lightBytes, &boxV, sizeof(boxV), lightBytes,
                         dispatch, lightA, reason, cancelled)) {
            return false;
        }
        const float w = weights[level];
        auto *accum = reinterpret_cast<float *>(lightAccum.data());
        const auto *src = reinterpret_cast<const float *>(lightA.data());
        for (std::uint64_t i = 0; i < pixels * 3u; ++i) accum[i] += src[i] * w;
    }
    const auto aux = makeCompositeAux(width, height, strength, lightAccum);
    if (!dispatchOne(compositeSpv, source, sourceBytes, aux.data(), aux.size(), imageBytes,
                     dispatch, output, reason, cancelled)) {
        return false;
    }
    return true;
}
} // namespace

bool renderLegacy(const QImage &source, const QRect &outputRect, double threshold,
                  int radius, double strength, QImage &output, QString &reason,
                  QString &deviceName, const std::function<bool()> &cancelled)
{
    reason.clear();
    deviceName.clear();
    if (disabled(reason)) return false;
    if (source.isNull() || source.format() != QImage::Format_ARGB32 || source.isNull()
        || outputRect.isEmpty() || outputRect.x() < 0 || outputRect.y() < 0
        || outputRect.right() >= source.width() || outputRect.bottom() >= source.height()
        || radius < 1 || radius > 64 || !std::isfinite(threshold) || !std::isfinite(strength)) {
        reason = QStringLiteral("Bloom legacy GPU requires a dense ARGB32 source and bounded output");
        return false;
    }
    LegacyShaderParameters params{};
    params.sourceW = source.width(); params.sourceH = source.height();
    params.outputX = outputRect.x(); params.outputY = outputRect.y();
    params.outputW = outputRect.width(); params.outputH = outputRect.height();
    params.radius = radius; params.step = std::max(1, radius / 8);
    params.threshold = float(threshold); params.strength = float(strength);
    const std::size_t inputBytes = std::size_t(source.width()) * source.height() * sizeof(std::uint32_t);
    const std::size_t outputBytes = std::size_t(outputRect.width()) * outputRect.height() * sizeof(std::uint32_t);
    try {
        std::vector<std::uint8_t> result;
        auto dispatch = gridFor(outputRect.width(), outputRect.height());
        if (!dispatchOne(std::vector<std::uint32_t>(std::begin(kBloomLegacySpv), std::end(kBloomLegacySpv)),
                         source.constBits(), inputBytes, &params, sizeof(params), outputBytes,
                         dispatch, result, reason, cancelled)) {
            return false;
        }
        output = QImage(outputRect.size(), QImage::Format_ARGB32);
        std::memcpy(output.bits(), result.data(), outputBytes);
        deviceName = QString::fromStdString(vulkanInstance().deviceName());
        return true;
    } catch (const std::bad_alloc &) {
        reason = QStringLiteral("Bloom GPU buffer allocation failed");
        return false;
    }
}

bool renderLegacyFloat(const tfm::EncodedRgbaImage &source, const QRect &outputRect,
                       double threshold, int radius, double strength,
                       tfm::EncodedRgbaImage &output, QString &reason, QString &deviceName,
                       const std::function<bool()> &cancelled)
{
    reason.clear();
    deviceName.clear();
    if (disabled(reason)) return false;
    Q_UNUSED(outputRect);
    if (source.isNull() || radius < 1 || radius > 64 || !std::isfinite(threshold) || !std::isfinite(strength)) {
        reason = QStringLiteral("Bloom legacy float GPU requires a dense EncodedRgbaImage");
        return false;
    }
    const std::uint64_t inputBytes = std::uint64_t(source.width) * source.height * 4ull * sizeof(float);
    const std::uint64_t outputBytes = inputBytes;
    const std::uint64_t memoryBudget = tfm::gpuMemoryBudgetBytes();
    if (inputBytes == 0 || inputBytes > memoryBudget || inputBytes * 2 + sizeof(LegacyShaderParameters) > memoryBudget) {
        reason = tfm::gpuMemoryBudgetExceeded(QStringLiteral("Bloom float buffers"));
        return false;
    }
    LegacyShaderParameters params{};
    params.sourceW = source.width; params.sourceH = source.height;
    params.outputX = 0; params.outputY = 0;
    params.outputW = source.width; params.outputH = source.height;
    params.radius = radius; params.step = std::max(1, radius / 8);
    params.threshold = float(threshold); params.strength = float(strength);
    try {
        std::vector<std::uint8_t> result;
        auto dispatch = gridFor(source.width, source.height);
        if (!dispatchOne(std::vector<std::uint32_t>(std::begin(kBloomLegacyFloatSpv), std::end(kBloomLegacyFloatSpv)),
                         source.pixels.constData(), std::size_t(inputBytes), &params, sizeof(params),
                         std::size_t(outputBytes), dispatch, result, reason, cancelled)) {
            return false;
        }
        tfm::EncodedRgbaImage out;
        out.width = source.width;
        out.height = source.height;
        out.pixels.resize(int(outputBytes / sizeof(float)));
        std::memcpy(out.pixels.data(), result.data(), std::size_t(outputBytes));
        output = std::move(out);
        deviceName = QString::fromStdString(vulkanInstance().deviceName());
        return true;
    } catch (const std::bad_alloc &) {
        reason = QStringLiteral("Bloom float GPU buffer allocation failed");
        return false;
    }
}

bool renderDiffuse(const QImage &source, double threshold, int radius, double strength,
                   double softness, QImage &output, QString &reason, QString &deviceName,
                   const std::function<bool()> &cancelled)
{
    reason.clear();
    deviceName.clear();
    if (disabled(reason)) return false;
    const QImage dense = source.convertToFormat(QImage::Format_ARGB32);
    if (dense.isNull() || strength <= 0.0) {
        reason = QStringLiteral("Bloom diffusion GPU requires a dense ARGB32 source");
        return false;
    }
    const std::size_t inputBytes = std::size_t(dense.width()) * dense.height() * sizeof(std::uint32_t);
    try {
        std::vector<std::uint8_t> result;
        if (!diffusePipeline(dense.constBits(), inputBytes, false, dense.width(), dense.height(),
                             threshold, radius, strength, softness, result, reason, cancelled)) {
            return false;
        }
        output = QImage(dense.size(), QImage::Format_ARGB32);
        std::memcpy(output.bits(), result.data(), inputBytes);
        deviceName = QString::fromStdString(vulkanInstance().deviceName());
        return true;
    } catch (const std::bad_alloc &) {
        reason = QStringLiteral("Bloom diffusion GPU buffer allocation failed");
        return false;
    }
}

bool renderDiffuseFloat(const tfm::EncodedRgbaImage &source, double threshold, int radius,
                        double strength, double softness, tfm::EncodedRgbaImage &output,
                        QString &reason, QString &deviceName,
                        const std::function<bool()> &cancelled)
{
    reason.clear();
    deviceName.clear();
    if (disabled(reason)) return false;
    if (source.isNull() || strength <= 0.0) {
        reason = QStringLiteral("Bloom diffusion float GPU requires a dense EncodedRgbaImage");
        return false;
    }
    const std::size_t inputBytes = std::size_t(source.width) * source.height * 4ull * sizeof(float);
    try {
        std::vector<std::uint8_t> result;
        if (!diffusePipeline(source.pixels.constData(), inputBytes, true, source.width, source.height,
                             threshold, radius, strength, softness, result, reason, cancelled)) {
            return false;
        }
        tfm::EncodedRgbaImage out;
        out.width = source.width;
        out.height = source.height;
        out.pixels.resize(source.pixels.size());
        std::memcpy(out.pixels.data(), result.data(), inputBytes);
        output = std::move(out);
        deviceName = QString::fromStdString(vulkanInstance().deviceName());
        return true;
    } catch (const std::bad_alloc &) {
        reason = QStringLiteral("Bloom diffusion float GPU buffer allocation failed");
        return false;
    }
}
} // namespace tfm_bloom_gpu
