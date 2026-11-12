#pragma once

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <string>

namespace tfm {

inline constexpr std::uint64_t kDefaultGpuMemoryBudgetMb = 1024;
inline constexpr std::uint64_t kMinGpuMemoryBudgetMb = 128;
inline constexpr std::uint64_t kMaxGpuMemoryBudgetMb = 8192;

inline std::uint64_t clampGpuMemoryBudgetMb(std::uint64_t mb)
{
    return std::clamp(mb, kMinGpuMemoryBudgetMb, kMaxGpuMemoryBudgetMb);
}

// Worker / device path: env only (host injects TFM_VULKAN_MEMORY_MB on spawn).
inline std::uint64_t gpuMemoryBudgetBytesFromEnv(std::uint64_t fallbackMb = kDefaultGpuMemoryBudgetMb)
{
    if (const char *raw = std::getenv("TFM_VULKAN_MEMORY_MB")) {
        char *end = nullptr;
        const long value = std::strtol(raw, &end, 10);
        if (end && !*end && value > 0)
            return clampGpuMemoryBudgetMb(std::uint64_t(value)) * 1024ull * 1024ull;
    }
    return clampGpuMemoryBudgetMb(fallbackMb) * 1024ull * 1024ull;
}

inline std::string gpuMemoryBudgetExceededMessage(const char *what, std::uint64_t budgetBytes)
{
    const std::uint64_t mb = std::max<std::uint64_t>(1, budgetBytes / (1024ull * 1024ull));
    return std::string(what) + " exceed " + std::to_string(mb) + " MiB budget";
}

} // namespace tfm
