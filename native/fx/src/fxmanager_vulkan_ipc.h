#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

// Binary framing shared by kritatfm.dll and tfm_vulkan_worker.exe.
// The plugin process only speaks this protocol. It never loads Vulkan.
namespace tfm_vulkan_ipc {

inline constexpr char kMagic[4] = {'T', 'F', 'M', 'V'};
inline constexpr std::uint32_t kHello = 0;
inline constexpr std::uint32_t kDispatch = 1;
inline constexpr std::uint32_t kShutdown = 2;
inline constexpr std::uint32_t kResult = 3;

template <typename Io>
bool transferAll(Io io, void *data, std::size_t size)
{
    auto *bytes = static_cast<std::uint8_t *>(data);
    while (size) {
        std::size_t moved = 0;
        if (!io(bytes, size, moved) || !moved) return false;
        bytes += moved;
        size -= moved;
    }
    return true;
}

template <typename Read>
bool readExact(Read read, void *data, std::size_t size)
{
    return transferAll([&](std::uint8_t *bytes, std::size_t n, std::size_t &moved) {
        return read(bytes, n, moved);
    }, data, size);
}

template <typename Write>
bool writeExact(Write write, const void *data, std::size_t size)
{
    return transferAll([&](std::uint8_t *bytes, std::size_t n, std::size_t &moved) {
        return write(bytes, n, moved);
    }, const_cast<void *>(data), size);
}

template <typename Read>
bool readU32(Read read, std::uint32_t &value)
{
    return readExact(read, &value, sizeof(value));
}

template <typename Write>
bool writeU32(Write write, std::uint32_t value)
{
    return writeExact(write, &value, sizeof(value));
}

template <typename Read>
bool readMagic(Read read)
{
    char magic[4] = {};
    return readExact(read, magic, 4) && std::memcmp(magic, kMagic, 4) == 0;
}

template <typename Write>
bool writeMagic(Write write)
{
    return writeExact(write, kMagic, 4);
}

template <typename Read>
bool readBytes(Read read, std::uint32_t size, std::string &out)
{
    out.assign(size, '\0');
    return size == 0 || readExact(read, out.data(), size);
}

template <typename Read>
bool readBytes(Read read, std::uint32_t size, std::vector<std::uint8_t> &out)
{
    out.resize(size);
    return size == 0 || readExact(read, out.data(), size);
}

template <typename Write>
bool writeBytes(Write write, const void *data, std::uint32_t size)
{
    return writeU32(write, size) && (size == 0 || writeExact(write, data, size));
}

} // namespace tfm_vulkan_ipc
