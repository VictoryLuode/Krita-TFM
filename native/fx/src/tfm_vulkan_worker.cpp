// Process that owns the Vulkan device for TFM filters. The Krita process
// launches this and speaks fxmanager_vulkan_ipc.h. When this process exits,
// the Vulkan driver state exits with it and cannot stick to the canvas.

#include "fxmanager_vulkan.h"
#include "fxmanager_vulkan_ipc.h"

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

namespace {

struct Io {
    HANDLE in;
    HANDLE out;
    bool read(void *data, std::size_t size, std::size_t &moved) const
    {
        DWORD got = 0;
        const DWORD chunk = static_cast<DWORD>(std::min<std::size_t>(size, 1u << 20));
        if (!ReadFile(in, data, chunk, &got, nullptr)) return false;
        moved = got;
        return true;
    }
    bool write(const void *data, std::size_t size, std::size_t &moved) const
    {
        DWORD put = 0;
        const DWORD chunk = static_cast<DWORD>(std::min<std::size_t>(size, 1u << 20));
        if (!WriteFile(out, data, chunk, &put, nullptr)) return false;
        moved = put;
        return true;
    }
};

bool writeHello(const Io &io, bool ok, bool float64, const std::string &name, const std::string &error)
{
    auto write = [&](const void *data, std::size_t size, std::size_t &moved) { return io.write(data, size, moved); };
    if (!tfm_vulkan_ipc::writeMagic(write) || !tfm_vulkan_ipc::writeU32(write, tfm_vulkan_ipc::kHello)) return false;
    if (!tfm_vulkan_ipc::writeU32(write, ok ? 1u : 0u) || !tfm_vulkan_ipc::writeU32(write, float64 ? 1u : 0u)) return false;
    if (!tfm_vulkan_ipc::writeBytes(write, name.data(), static_cast<std::uint32_t>(name.size()))) return false;
    return tfm_vulkan_ipc::writeBytes(write, error.data(), static_cast<std::uint32_t>(error.size()));
}

int serve()
{
    const Io io{GetStdHandle(STD_INPUT_HANDLE), GetStdHandle(STD_OUTPUT_HANDLE)};
    auto read = [&](void *data, std::size_t size, std::size_t &moved) { return io.read(data, size, moved); };
    auto write = [&](const void *data, std::size_t size, std::size_t &moved) { return io.write(data, size, moved); };

    FxManagerVulkan vulkan;
    std::string error;
    const bool ready = vulkan.initialize(&error);
    if (!writeHello(io, ready, ready && vulkan.supportsShaderFloat64(), vulkan.deviceName(), error)) return 1;
    if (!ready) return 1;

    for (;;) {
        if (!tfm_vulkan_ipc::readMagic(read)) break;
        std::uint32_t kind = 0;
        if (!tfm_vulkan_ipc::readU32(read, kind)) return 1;
        if (kind == tfm_vulkan_ipc::kShutdown) break;
        if (kind != tfm_vulkan_ipc::kDispatch) return 1;

        std::uint32_t spirvBytes = 0, inputBytes = 0, paramBytes = 0, outputBytes = 0;
        std::uint32_t groups[3] = {}, bindings[3] = {};
        if (!tfm_vulkan_ipc::readU32(read, spirvBytes) || !tfm_vulkan_ipc::readU32(read, inputBytes)
            || !tfm_vulkan_ipc::readU32(read, paramBytes) || !tfm_vulkan_ipc::readU32(read, outputBytes)
            || !tfm_vulkan_ipc::readExact(read, groups, sizeof(groups))
            || !tfm_vulkan_ipc::readExact(read, bindings, sizeof(bindings))) return 1;
        constexpr std::uint32_t kBudget = 128u * 1024u * 1024u;
        if (spirvBytes == 0 || spirvBytes > kBudget || inputBytes > kBudget || paramBytes > kBudget
            || outputBytes == 0 || outputBytes > kBudget || spirvBytes % sizeof(std::uint32_t) != 0) {
            return 1;
        }

        std::vector<std::uint8_t> spirvRaw, input, parameters;
        if (!tfm_vulkan_ipc::readBytes(read, spirvBytes, spirvRaw)
            || !tfm_vulkan_ipc::readBytes(read, inputBytes, input)
            || !tfm_vulkan_ipc::readBytes(read, paramBytes, parameters)) return 1;

        std::vector<std::uint32_t> spirv(spirvBytes / sizeof(std::uint32_t));
        if (!spirvRaw.empty()) std::memcpy(spirv.data(), spirvRaw.data(), spirvRaw.size());
        FxManagerVulkan::Dispatch dispatch;
        dispatch.groupsX = groups[0];
        dispatch.groupsY = groups[1];
        dispatch.groupsZ = groups[2];
        dispatch.inputBinding = bindings[0];
        dispatch.outputBinding = bindings[1];
        dispatch.parametersBinding = bindings[2];

        std::vector<std::uint8_t> output;
        std::string dispatchError;
        const bool ok = vulkan.dispatch(spirv,
                                        input.empty() ? nullptr : input.data(), input.size(),
                                        parameters.empty() ? nullptr : parameters.data(), parameters.size(),
                                        outputBytes, dispatch, output, &dispatchError);
        const std::string name = vulkan.deviceName();
        if (!tfm_vulkan_ipc::writeMagic(write) || !tfm_vulkan_ipc::writeU32(write, tfm_vulkan_ipc::kResult)
            || !tfm_vulkan_ipc::writeU32(write, ok ? 1u : 0u)) return 1;
        if (!tfm_vulkan_ipc::writeBytes(write, name.data(), static_cast<std::uint32_t>(name.size()))) return 1;
        if (!tfm_vulkan_ipc::writeBytes(write, dispatchError.data(), static_cast<std::uint32_t>(dispatchError.size()))) return 1;
        if (ok) {
            if (output.size() != outputBytes) return 1;
            if (!tfm_vulkan_ipc::writeExact(write, output.data(), output.size())) return 1;
        }
    }
    vulkan.shutdown();
    return 0;
}

} // namespace

int main(int argc, char **argv)
{
    if (argc > 1 && std::strcmp(argv[1], "--ping") == 0) {
        FxManagerVulkan vulkan;
        std::string error;
        if (!vulkan.initialize(&error)) {
            std::fprintf(stderr, "%s\n", error.c_str());
            return 1;
        }
        std::fprintf(stdout, "%s\n", vulkan.deviceName().c_str());
        vulkan.shutdown();
        return 0;
    }
    return serve();
}
