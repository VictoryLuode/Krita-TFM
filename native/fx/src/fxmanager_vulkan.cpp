// Plugin-side Vulkan client. This process must not call LoadLibrary on
// vulkan-1.dll. NVIDIA keeps a mixed OpenGL/ANGLE + Vulkan state for the
// whole process, which is what makes canvas zoom stutter after a GPU filter.
// The device lives in tfm_vulkan_worker.exe and dies with that process.

#include "fxmanager_vulkan.h"
#include "fxmanager_vulkan_ipc.h"

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace {

struct Worker {
    HANDLE job = nullptr;
    HANDLE process = nullptr;
    HANDLE toWorker = nullptr;
    HANDLE fromWorker = nullptr;
    bool ready = false;
    bool float64 = false;
    bool idleArmed = false;
    std::string name;
    std::uint64_t generation = 0;
    std::chrono::steady_clock::time_point idleDeadline{};

    void closePipes()
    {
        if (toWorker) CloseHandle(toWorker);
        if (fromWorker) CloseHandle(fromWorker);
        toWorker = fromWorker = nullptr;
    }

    void closeProcess()
    {
        if (process) CloseHandle(process);
        process = nullptr;
        ready = false;
    }
};

Worker &worker()
{
    static Worker instance;
    return instance;
}

std::mutex &gate()
{
    static std::mutex mutex;
    return mutex;
}

std::condition_variable &idleCv()
{
    static std::condition_variable cv;
    return cv;
}

bool pipeIo(HANDLE handle, void *data, std::size_t size, std::size_t &moved, bool writing)
{
    DWORD count = 0;
    const DWORD chunk = static_cast<DWORD>(std::min<std::size_t>(size, 1u << 20));
    const BOOL ok = writing
        ? WriteFile(handle, data, chunk, &count, nullptr)
        : ReadFile(handle, data, chunk, &count, nullptr);
    if (!ok) return false;
    moved = count;
    return true;
}

std::wstring executableDirectory()
{
    wchar_t path[32768];
    const DWORD length = GetModuleFileNameW(nullptr, path, 32768);
    if (!length || length >= 32768) return {};
    std::wstring text(path, length);
    const auto slash = text.find_last_of(L"\\/");
    return slash == std::wstring::npos ? std::wstring() : text.substr(0, slash);
}

std::wstring workerExecutable()
{
    HMODULE module = GetModuleHandleW(L"kritatfm.dll");
    if (!module) return {};
    wchar_t path[32768];
    const DWORD length = GetModuleFileNameW(module, path, 32768);
    if (!length || length >= 32768) return {};
    std::wstring text(path, length);
    const auto slash = text.find_last_of(L"\\/");
    if (slash == std::wstring::npos) return {};
    return text.substr(0, slash + 1) + L"tfm_vulkan_worker.exe";
}

std::wstring environmentWith(const std::wstring &binDirectory)
{
    std::wstring block;
    wchar_t *source = GetEnvironmentStringsW();
    bool sawPath = false;
    if (source) {
        for (const wchar_t *cursor = source; *cursor; ) {
            const std::wstring entry = cursor;
            cursor += entry.size() + 1;
            std::wstring rewritten = entry;
            if (entry.size() >= 5 && _wcsnicmp(entry.c_str(), L"PATH=", 5) == 0) {
                rewritten = L"PATH=" + binDirectory + L";" + entry.substr(5);
                sawPath = true;
            }
            block.append(rewritten);
            block.push_back(L'\0');
        }
        FreeEnvironmentStringsW(source);
    }
    if (!sawPath) {
        block.append(L"PATH=" + binDirectory);
        block.push_back(L'\0');
    }
    block.push_back(L'\0');
    return block;
}

void abandonProcess()
{
    Worker &current = worker();
    current.closePipes();
    if (current.process) {
        TerminateProcess(current.process, 1);
        WaitForSingleObject(current.process, 2000);
    }
    current.closeProcess();
}

void stopWorker()
{
    Worker &current = worker();
    if (current.toWorker) {
        auto write = [&](const void *data, std::size_t size, std::size_t &moved) {
            return pipeIo(current.toWorker, const_cast<void *>(data), size, moved, true);
        };
        tfm_vulkan_ipc::writeMagic(write);
        tfm_vulkan_ipc::writeU32(write, tfm_vulkan_ipc::kShutdown);
    }
    current.closePipes();
    if (current.process) {
        if (WaitForSingleObject(current.process, 3000) != WAIT_OBJECT_0)
            TerminateProcess(current.process, 1);
        WaitForSingleObject(current.process, 1000);
    }
    current.closeProcess();
}

void ensureIdleThread()
{
    static std::once_flag once;
    std::call_once(once, [] {
        std::thread([] {
            std::unique_lock<std::mutex> lock(gate());
            for (;;) {
                idleCv().wait(lock, [] { return worker().idleArmed; });
                const auto token = worker().generation;
                const auto deadline = worker().idleDeadline;
                const bool cancelled = idleCv().wait_until(lock, deadline, [&] {
                    return !worker().idleArmed || worker().generation != token
                        || worker().idleDeadline != deadline;
                });
                if (cancelled) continue;
                if (worker().idleArmed && worker().generation == token) {
                    worker().idleArmed = false;
                    stopWorker();
                }
            }
        }).detach();
    });
}

void armIdle()
{
    ensureIdleThread();
    Worker &current = worker();
    current.idleDeadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    current.idleArmed = true;
    idleCv().notify_all();
}

void disarmIdle()
{
    worker().idleArmed = false;
    idleCv().notify_all();
}

bool readHello(std::string &error)
{
    Worker &current = worker();
    auto read = [&](void *data, std::size_t size, std::size_t &moved) {
        return pipeIo(current.fromWorker, data, size, moved, false);
    };
    std::uint32_t kind = 0, ok = 0, float64 = 0, nameLen = 0, errorLen = 0;
    if (!tfm_vulkan_ipc::readMagic(read) || !tfm_vulkan_ipc::readU32(read, kind) || kind != tfm_vulkan_ipc::kHello
        || !tfm_vulkan_ipc::readU32(read, ok) || !tfm_vulkan_ipc::readU32(read, float64)
        || !tfm_vulkan_ipc::readU32(read, nameLen) || nameLen > 4096) {
        error = "Vulkan worker closed before it was ready";
        return false;
    }
    current.name.assign(nameLen, '\0');
    if ((nameLen && !tfm_vulkan_ipc::readExact(read, current.name.data(), nameLen))
        || !tfm_vulkan_ipc::readU32(read, errorLen) || errorLen > (1u << 20)) {
        error = "Vulkan worker closed before it was ready";
        return false;
    }
    error.assign(errorLen, '\0');
    if (errorLen && !tfm_vulkan_ipc::readExact(read, error.data(), errorLen)) {
        error = "Vulkan worker closed before it was ready";
        return false;
    }
    current.float64 = float64 != 0;
    if (!ok) {
        if (error.empty()) error = "Vulkan worker failed to create a device";
        return false;
    }
    current.ready = true;
    return true;
}

bool ensureWorker(std::string &error)
{
    if (const char *disabled = std::getenv("TFM_VULKAN_DISABLE")) {
        if (disabled[0] && disabled[0] != '0') {
            error = "Vulkan disabled by TFM_VULKAN_DISABLE";
            return false;
        }
    }
    Worker &current = worker();
    if (current.process) {
        DWORD code = 0;
        if (current.ready && GetExitCodeProcess(current.process, &code) && code == STILL_ACTIVE) return true;
        abandonProcess();
    }
    const std::wstring exe = workerExecutable();
    if (exe.empty() || GetFileAttributesW(exe.c_str()) == INVALID_FILE_ATTRIBUTES) {
        error = "TFM Vulkan worker is not installed next to kritatfm.dll";
        return false;
    }
    SECURITY_ATTRIBUTES inherit{sizeof(inherit), nullptr, TRUE};
    HANDLE childInRead = nullptr, childInWrite = nullptr, childOutRead = nullptr, childOutWrite = nullptr, nul = nullptr;
    auto cleanupHandles = [&] {
        if (childInRead) CloseHandle(childInRead);
        if (childInWrite) CloseHandle(childInWrite);
        if (childOutRead) CloseHandle(childOutRead);
        if (childOutWrite) CloseHandle(childOutWrite);
        if (nul) CloseHandle(nul);
        childInRead = childInWrite = childOutRead = childOutWrite = nul = nullptr;
    };
    if (!CreatePipe(&childInRead, &childInWrite, &inherit, 1u << 20)
        || !CreatePipe(&childOutRead, &childOutWrite, &inherit, 1u << 20)) {
        cleanupHandles();
        error = "Could not create the Vulkan worker pipes";
        return false;
    }
    SetHandleInformation(childInWrite, HANDLE_FLAG_INHERIT, 0);
    SetHandleInformation(childOutRead, HANDLE_FLAG_INHERIT, 0);
    nul = CreateFileW(L"NUL", GENERIC_WRITE, FILE_SHARE_WRITE | FILE_SHARE_READ, &inherit, OPEN_EXISTING, 0, nullptr);
    if (nul == INVALID_HANDLE_VALUE) {
        nul = nullptr;
        cleanupHandles();
        error = "Could not start the Vulkan worker";
        return false;
    }

    SIZE_T attributeSize = 0;
    InitializeProcThreadAttributeList(nullptr, 1, 0, &attributeSize);
    std::vector<std::uint8_t> attributeStorage(attributeSize);
    auto *attributes = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(attributeStorage.data());
    if (!attributeSize || !InitializeProcThreadAttributeList(attributes, 1, 0, &attributeSize)) {
        cleanupHandles();
        error = "Could not start the Vulkan worker";
        return false;
    }
    HANDLE inherited[3] = {childInRead, childOutWrite, nul};
    const BOOL listed = UpdateProcThreadAttribute(attributes, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                                                   inherited, sizeof(inherited), nullptr, nullptr);
    if (!listed) {
        DeleteProcThreadAttributeList(attributes);
        cleanupHandles();
        error = "Could not start the Vulkan worker";
        return false;
    }

    std::wstring command = L"\"" + exe + L"\"";
    std::vector<wchar_t> commandBuffer(command.begin(), command.end());
    commandBuffer.push_back(L'\0');
    std::wstring environment = environmentWith(executableDirectory());
    STARTUPINFOEXW startup{};
    startup.StartupInfo.cb = sizeof(startup);
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = childInRead;
    startup.StartupInfo.hStdOutput = childOutWrite;
    startup.StartupInfo.hStdError = nul;
    startup.lpAttributeList = attributes;
    PROCESS_INFORMATION process{};
    const DWORD flags = CREATE_NO_WINDOW | CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT;
    const BOOL created = CreateProcessW(exe.c_str(), commandBuffer.data(), nullptr, nullptr, TRUE, flags,
                                         environment.empty() ? nullptr : environment.data(), nullptr,
                                         &startup.StartupInfo, &process);
    DeleteProcThreadAttributeList(attributes);
    if (!created) {
        cleanupHandles();
        error = "Could not start the Vulkan worker";
        return false;
    }
    if (!current.job) {
        current.job = CreateJobObjectW(nullptr, nullptr);
        if (current.job) {
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            SetInformationJobObject(current.job, JobObjectExtendedLimitInformation, &limits, sizeof(limits));
        }
    }
    if (current.job) AssignProcessToJobObject(current.job, process.hProcess);
    ResumeThread(process.hThread);
    CloseHandle(process.hThread);
    CloseHandle(childInRead);
    CloseHandle(childOutWrite);
    if (nul) CloseHandle(nul);
    childInRead = childOutWrite = nul = nullptr;
    current.process = process.hProcess;
    current.toWorker = childInWrite;
    current.fromWorker = childOutRead;
    childInWrite = childOutRead = nullptr;
    if (!readHello(error)) {
        abandonProcess();
        return false;
    }
    return true;
}

bool sendDispatch(const std::vector<std::uint32_t> &spirv, const void *inputData, std::size_t inputSize,
                  const void *parametersData, std::size_t parametersSize, std::size_t outputSize,
                  const FxManagerVulkan::Dispatch &config, std::vector<std::uint8_t> &outputData, std::string &error)
{
    Worker &current = worker();
    auto write = [&](const void *data, std::size_t size, std::size_t &moved) {
        return pipeIo(current.toWorker, const_cast<void *>(data), size, moved, true);
    };
    auto read = [&](void *data, std::size_t size, std::size_t &moved) {
        return pipeIo(current.fromWorker, data, size, moved, false);
    };
    const std::uint32_t groups[3] = {config.groupsX, config.groupsY, config.groupsZ};
    const std::uint32_t bindings[3] = {config.inputBinding, config.outputBinding, config.parametersBinding};
    const auto spirvBytes = static_cast<std::uint32_t>(spirv.size() * sizeof(std::uint32_t));
    if (!tfm_vulkan_ipc::writeMagic(write) || !tfm_vulkan_ipc::writeU32(write, tfm_vulkan_ipc::kDispatch)
        || !tfm_vulkan_ipc::writeU32(write, spirvBytes)
        || !tfm_vulkan_ipc::writeU32(write, static_cast<std::uint32_t>(inputSize))
        || !tfm_vulkan_ipc::writeU32(write, static_cast<std::uint32_t>(parametersSize))
        || !tfm_vulkan_ipc::writeU32(write, static_cast<std::uint32_t>(outputSize))
        || !tfm_vulkan_ipc::writeExact(write, groups, sizeof(groups))
        || !tfm_vulkan_ipc::writeExact(write, bindings, sizeof(bindings))
        || !tfm_vulkan_ipc::writeExact(write, spirv.data(), spirvBytes)
        || (inputSize && !tfm_vulkan_ipc::writeExact(write, inputData, inputSize))
        || (parametersSize && !tfm_vulkan_ipc::writeExact(write, parametersData, parametersSize))) {
        error = "Could not send a Vulkan job";
        abandonProcess();
        return false;
    }
    std::uint32_t kind = 0, ok = 0, nameLen = 0, errorLen = 0;
    if (!tfm_vulkan_ipc::readMagic(read) || !tfm_vulkan_ipc::readU32(read, kind) || kind != tfm_vulkan_ipc::kResult
        || !tfm_vulkan_ipc::readU32(read, ok)
        || !tfm_vulkan_ipc::readU32(read, nameLen) || nameLen > 4096) {
        error = "Vulkan worker ended during the job";
        abandonProcess();
        return false;
    }
    current.name.assign(nameLen, '\0');
    if ((nameLen && !tfm_vulkan_ipc::readExact(read, current.name.data(), nameLen))
        || !tfm_vulkan_ipc::readU32(read, errorLen) || errorLen > (1u << 20)) {
        error = "Vulkan worker ended during the job";
        abandonProcess();
        return false;
    }
    error.assign(errorLen, '\0');
    if (errorLen && !tfm_vulkan_ipc::readExact(read, error.data(), errorLen)) {
        error = "Vulkan worker ended during the job";
        abandonProcess();
        return false;
    }
    if (!ok) {
        if (error.empty()) error = "Vulkan dispatch failed";
        return false;
    }
    outputData.resize(outputSize);
    if (outputSize && !tfm_vulkan_ipc::readExact(read, outputData.data(), outputSize)) {
        error = "Vulkan worker returned a short image";
        abandonProcess();
        return false;
    }
    return true;
}

} // namespace

struct FxManagerVulkan::Impl {};

FxManagerVulkan::FxManagerVulkan() : m_impl(std::make_unique<Impl>()) {}
FxManagerVulkan::~FxManagerVulkan() = default;

void FxManagerVulkan::shutdown()
{
    std::lock_guard<std::mutex> self(m_mutex);
    std::lock_guard<std::mutex> lock(gate());
    ++worker().generation;
    disarmIdle();
    stopWorker();
}

void FxManagerVulkan::scheduleIdleShutdown()
{
    std::lock_guard<std::mutex> lock(gate());
    armIdle();
}

bool FxManagerVulkan::initialize(std::string *errorOut)
{
    std::lock_guard<std::mutex> self(m_mutex);
    std::lock_guard<std::mutex> lock(gate());
    ++worker().generation;
    disarmIdle();
    std::string error;
    const bool ok = ensureWorker(error);
    if (!ok && errorOut) *errorOut = error;
    if (ok && errorOut) errorOut->clear();
    return ok;
}

bool FxManagerVulkan::isInitialized() const
{
    std::lock_guard<std::mutex> self(m_mutex);
    std::lock_guard<std::mutex> lock(gate());
    return worker().ready;
}

std::string FxManagerVulkan::deviceName() const
{
    std::lock_guard<std::mutex> self(m_mutex);
    std::lock_guard<std::mutex> lock(gate());
    return worker().name;
}

bool FxManagerVulkan::supportsShaderFloat64() const
{
    std::lock_guard<std::mutex> self(m_mutex);
    std::lock_guard<std::mutex> lock(gate());
    return worker().ready && worker().float64;
}

bool FxManagerVulkan::dispatch(const std::vector<std::uint32_t> &spirv,
                               const void *inputData, std::size_t inputSize,
                               const void *parametersData, std::size_t parametersSize,
                               std::size_t outputSize, const Dispatch &config,
                               std::vector<std::uint8_t> &outputData,
                               std::string *errorOut)
{
    std::lock_guard<std::mutex> self(m_mutex);
    auto fail = [&](const std::string &message) {
        if (errorOut) *errorOut = message;
        return false;
    };
    constexpr std::size_t budget = 128ull * 1024 * 1024;
    if (inputSize > budget || outputSize > budget || parametersSize > budget)
        return fail("Vulkan buffer exceeds 128 MiB processing budget");
    if (spirv.empty() || spirv.front() != 0x07230203u || (spirv.size() * sizeof(std::uint32_t)) % 4 != 0)
        return fail("Invalid SPIR-V module (expected 32-bit words with SPIR-V magic)");
    if (!inputData && inputSize) return fail("inputData is null while inputSize is non-zero");
    if (!parametersData && parametersSize) return fail("parametersData is null while parametersSize is non-zero");
    if (!outputSize || !config.groupsX || !config.groupsY || !config.groupsZ)
        return fail("Output size and dispatch group counts must be non-zero");
    if (config.groupsX > 65535 || config.groupsY > 65535 || config.groupsZ > 65535)
        return fail("Vulkan dispatch exceeds portable group-count limits");
    if (config.inputBinding == config.outputBinding || config.inputBinding == config.parametersBinding
        || config.outputBinding == config.parametersBinding)
        return fail("Descriptor binding numbers must be distinct");
    if (inputSize > 0xffffffffu || parametersSize > 0xffffffffu || outputSize > 0xffffffffu)
        return fail("Vulkan buffer exceeds 128 MiB processing budget");

    std::string error;
    {
        std::lock_guard<std::mutex> lock(gate());
        ++worker().generation;
        disarmIdle();
        if (!ensureWorker(error)) return fail(error);
        if (!sendDispatch(spirv, inputData, inputSize, parametersData, parametersSize, outputSize, config, outputData, error))
            return fail(error);
    }
    scheduleIdleShutdown();
    if (errorOut) errorOut->clear();
    return true;
}
