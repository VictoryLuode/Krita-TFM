#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

// Compute service used by TFM GPU filters.
// kritatfm.dll forwards these calls to tfm_vulkan_worker.exe and does not load
// Vulkan into the Krita process. The worker executable links the device
// implementation and exits when the filter goes idle, so the driver state
// leaves with that process instead of sticking to the canvas.
class FxManagerVulkan final
{
public:
    struct Dispatch
    {
        // Descriptor set binding numbers for input, output, and optional
        // parameter buffers. The shader must declare storage buffers at these
        // bindings in set 0. Use UINT32_MAX to omit a buffer.
        std::uint32_t inputBinding = 0;
        std::uint32_t outputBinding = 1;
        std::uint32_t parametersBinding = UINT32_MAX;
        std::uint32_t groupsX = 1;
        std::uint32_t groupsY = 1;
        std::uint32_t groupsZ = 1;
    };

    FxManagerVulkan();
    ~FxManagerVulkan();

    FxManagerVulkan(const FxManagerVulkan &) = delete;
    FxManagerVulkan &operator=(const FxManagerVulkan &) = delete;
    FxManagerVulkan(FxManagerVulkan &&) = delete;
    FxManagerVulkan &operator=(FxManagerVulkan &&) = delete;

    // Selects the highest-scoring discrete GPU with a compute queue and
    // creates the Vulkan device. Returns false and stores a diagnostic on
    // failure. Safe to call repeatedly after a failed attempt.
    bool initialize(std::string *error = nullptr);
    // Drops the Vulkan device/instance so OpenGL/ANGLE canvas can recover.
    void shutdown();
    bool isInitialized() const;
    std::string deviceName() const;
    // True only when the selected device advertises shaderFloat64 and the
    // Vulkan core can enable the feature during device creation.
    bool supportsShaderFloat64() const;

    // Executes a caller-provided SPIR-V compute shader. Input and output are
    // storage-buffer bytes; parameters may be empty. The result replaces
    // outputData. All calls are serialized internally.
    bool dispatch(const std::vector<std::uint32_t> &spirv,
                  const void *inputData,
                  std::size_t inputSize,
                  const void *parametersData,
                  std::size_t parametersSize,
                  std::size_t outputSize,
                  const Dispatch &dispatch,
                  std::vector<std::uint8_t> &outputData,
                  std::string *error = nullptr);

private:
    void scheduleIdleShutdown();

    struct Impl;
    std::unique_ptr<Impl> m_impl;
    mutable std::mutex m_mutex;
    std::uint64_t m_idleGeneration = 0;
};
