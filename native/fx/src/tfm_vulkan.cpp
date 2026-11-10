// Plugin-side Vulkan client. This process must not call LoadLibrary on
// vulkan-1.dll. NVIDIA keeps a mixed OpenGL/ANGLE + Vulkan state for the
// whole process, which is what makes canvas zoom stutter after a GPU filter.
// The device lives in tfm_vulkan_worker.exe and dies with that process.

#include "tfm_vulkan.h"
#include "tfm_vulkan_ipc.h"

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include <algorithm>
#include <atomic>
#include <limits>
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
    static Worker *instance = new Worker;
    return *instance;
}

std::timed_mutex &gate()
{
    static auto *mutex = new std::timed_mutex;
    return *mutex;
}

std::condition_variable_any &idleCv()
{
    static auto *cv = new std::condition_variable_any;
    return *cv;
}

using Status = TfmVulkan::Status;
using Clock = std::chrono::steady_clock;

std::chrono::milliseconds timeout(const char *variable, long fallback)
{
    const char *value = std::getenv(variable);
    if (!value || !*value) return std::chrono::milliseconds(fallback);
    char *end = nullptr;
    const long parsed = std::strtol(value, &end, 10);
    // Diagnostic settings cannot disable bounded waits.
    return std::chrono::milliseconds(end && !*end && parsed >= 1 && parsed <= 3600000 ? parsed : fallback);
}

struct Operation {
    std::function<bool()> cancelled;
    Clock::time_point deadline;
    Status status = Status::Success;

    bool interrupted()
    {
        if (status != Status::Success) return true;
        if (cancelled && cancelled()) status = Status::Cancelled;
        else if (Clock::now() >= deadline) status = Status::Timeout;
        return status != Status::Success;
    }
    TfmVulkan::Result result(std::string error) const
    {
        switch (status) {
        case Status::Cancelled: error = "Vulkan operation cancelled"; break;
        case Status::Timeout: error = "Vulkan worker deadline exceeded"; break;
        case Status::ProcessExited: error = "Vulkan worker exited or disconnected"; break;
        default: break;
        }
        return {status, std::move(error)};
    }
};

bool pipeIo(HANDLE handle, void *data, std::size_t size, std::size_t &moved,
            bool writing, Operation &operation)
{
    moved = 0;
    if (operation.interrupted()) return false;
    OVERLAPPED pending{};
    pending.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!pending.hEvent) { operation.status = Status::Unavailable; return false; }
    DWORD count = 0;
    const DWORD chunk = static_cast<DWORD>(std::min<std::size_t>(size, 1u << 20));
    BOOL ok = writing ? WriteFile(handle, data, chunk, &count, &pending)
                      : ReadFile(handle, data, chunk, &count, &pending);
    if (!ok && GetLastError() == ERROR_IO_PENDING) {
        HANDLE events[2] = {pending.hEvent, worker().process};
        while (!operation.interrupted()) {
            const DWORD wait = WaitForMultipleObjects(worker().process ? 2 : 1, events, FALSE, 20);
            if (wait == WAIT_OBJECT_0) break;
            if (wait == WAIT_OBJECT_0 + 1) { operation.status = Status::ProcessExited; break; }
            if (wait == WAIT_FAILED) { operation.status = Status::ProtocolError; break; }
        }
        if (operation.status != Status::Success) CancelIoEx(handle, &pending);
        // Drain the cancelled kernel request before releasing its stack buffer/event.
        ok = GetOverlappedResult(handle, &pending, &count, TRUE);
    }
    CloseHandle(pending.hEvent);
    if (!ok || !count) {
        if (operation.status == Status::Success) operation.status = Status::ProcessExited;
        return false;
    }
    if (operation.interrupted()) return false;
    moved = count;
    return true;
}

// Anonymous pipes cannot do overlapped I/O. Only the parent endpoint is
// overlapped; the owned worker keeps its ordinary stdin/stdout protocol.
bool createPipePair(HANDLE &parent, HANDLE &child, bool parentReads,
                    SECURITY_ATTRIBUTES &inherit)
{
    static std::atomic<unsigned long> sequence{0};
    const std::wstring name = L"\\\\.\\pipe\\tfm-vulkan-" + std::to_wstring(GetCurrentProcessId())
        + L"-" + std::to_wstring(++sequence);
    parent = CreateNamedPipeW(name.c_str(), (parentReads ? PIPE_ACCESS_INBOUND : PIPE_ACCESS_OUTBOUND)
        | FILE_FLAG_OVERLAPPED | FILE_FLAG_FIRST_PIPE_INSTANCE,
        PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
        1, 1u << 20, 1u << 20, 0, nullptr);
    if (parent == INVALID_HANDLE_VALUE) { parent = nullptr; return false; }
    child = CreateFileW(name.c_str(), parentReads ? GENERIC_WRITE : GENERIC_READ,
                        0, &inherit, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (child == INVALID_HANDLE_VALUE) { child = nullptr; CloseHandle(parent); parent = nullptr; return false; }
    // CreateFile connected before ConnectNamedPipe; no blocking connect needed.
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
    Operation operation{{}, Clock::now() + std::chrono::milliseconds(200)};
    if (current.toWorker) {
        auto write = [&](const void *data, std::size_t size, std::size_t &moved) {
            return pipeIo(current.toWorker, const_cast<void *>(data), size, moved, true, operation);
        };
        tfm_vulkan_ipc::writeMagic(write);
        tfm_vulkan_ipc::writeU32(write, tfm_vulkan_ipc::kShutdown);
    }
    current.closePipes();
    if (current.process) {
        if (WaitForSingleObject(current.process, 300) != WAIT_OBJECT_0)
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
            std::unique_lock<std::timed_mutex> lock(gate());
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

std::chrono::milliseconds idleTtl()
{
    // Keep the warm worker around across interactive filter tweaks. Override
    // with TFM_VULKAN_IDLE_MS (milliseconds); tests pin this to 2000.
    return timeout("TFM_VULKAN_IDLE_MS", 30000);
}

void armIdle()
{
    ensureIdleThread();
    Worker &current = worker();
    current.idleDeadline = std::chrono::steady_clock::now() + idleTtl();
    current.idleArmed = true;
    idleCv().notify_all();
}

void disarmIdle()
{
    worker().idleArmed = false;
    idleCv().notify_all();
}

bool readHello(std::string &error, Operation &operation)
{
    Worker &current = worker();
    auto read = [&](void *data, std::size_t size, std::size_t &moved) {
        return pipeIo(current.fromWorker, data, size, moved, false, operation);
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
        operation.status = Status::Unavailable;
        if (error.empty()) error = "Vulkan worker failed to create a device";
        return false;
    }
    current.ready = true;
    return true;
}

bool ensureWorker(std::string &error, Operation &operation)
{
    if (operation.interrupted()) return false;
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
    if (!createPipePair(childInWrite, childInRead, false, inherit)
        || !createPipePair(childOutRead, childOutWrite, true, inherit)) {
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
    if (!readHello(error, operation)) {
        if (operation.status == Status::Success) operation.status = Status::ProtocolError;
        abandonProcess();
        return false;
    }
    return true;
}

bool sendDispatch(const std::vector<std::uint32_t> &spirv, const void *inputData, std::size_t inputSize,
                  const void *parametersData, std::size_t parametersSize, std::size_t outputSize,
                  const TfmVulkan::Dispatch &config, std::vector<std::uint8_t> &outputData, std::string &error, Operation &operation)
{
    Worker &current = worker();
    auto write = [&](const void *data, std::size_t size, std::size_t &moved) {
        return pipeIo(current.toWorker, const_cast<void *>(data), size, moved, true, operation);
    };
    auto read = [&](void *data, std::size_t size, std::size_t &moved) {
        return pipeIo(current.fromWorker, data, size, moved, false, operation);
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
        if (operation.status == Status::Success) operation.status = Status::ProtocolError;
        abandonProcess();
        return false;
    }
    std::uint32_t kind = 0, ok = 0, nameLen = 0, errorLen = 0;
    if (!tfm_vulkan_ipc::readMagic(read) || !tfm_vulkan_ipc::readU32(read, kind) || kind != tfm_vulkan_ipc::kResult
        || !tfm_vulkan_ipc::readU32(read, ok)
        || !tfm_vulkan_ipc::readU32(read, nameLen) || nameLen > 4096) {
        error = "Vulkan worker ended during the job";
        if (operation.status == Status::Success) operation.status = Status::ProtocolError;
        abandonProcess();
        return false;
    }
    current.name.assign(nameLen, '\0');
    if ((nameLen && !tfm_vulkan_ipc::readExact(read, current.name.data(), nameLen))
        || !tfm_vulkan_ipc::readU32(read, errorLen) || errorLen > (1u << 20)) {
        error = "Vulkan worker ended during the job";
        if (operation.status == Status::Success) operation.status = Status::ProtocolError;
        abandonProcess();
        return false;
    }
    error.assign(errorLen, '\0');
    if (errorLen && !tfm_vulkan_ipc::readExact(read, error.data(), errorLen)) {
        error = "Vulkan worker ended during the job";
        if (operation.status == Status::Success) operation.status = Status::ProtocolError;
        abandonProcess();
        return false;
    }
    if (!ok) {
        operation.status = Status::Unavailable;
        if (error.empty()) error = "Vulkan dispatch failed";
        return false;
    }
    std::vector<std::uint8_t> staged(outputSize);
    if (outputSize && !tfm_vulkan_ipc::readExact(read, staged.data(), outputSize)) {
        error = "Vulkan worker returned a short image";
        if (operation.status == Status::Success) operation.status = Status::ProtocolError;
        abandonProcess();
        return false;
    }
    if (operation.interrupted()) { abandonProcess(); return false; }
    outputData.swap(staged);
    return true;
}

} // namespace

bool vulkanWorkerReady()
{
    std::unique_lock<std::timed_mutex> lock(gate(), std::try_to_lock);
    // A held gate means a dispatch is in flight — treat that as warm.
    if (!lock.owns_lock()) return true;
    return worker().ready;
}

struct TfmVulkan::Impl {};

TfmVulkan::TfmVulkan() : m_impl(std::make_unique<Impl>()) {}
TfmVulkan::~TfmVulkan() = default;

void TfmVulkan::shutdown()
{
    std::lock_guard<std::mutex> self(m_mutex);
    std::lock_guard<std::timed_mutex> lock(gate());
    ++worker().generation;
    disarmIdle();
    stopWorker();
}

void TfmVulkan::scheduleIdleShutdown()
{
    std::lock_guard<std::timed_mutex> lock(gate());
    armIdle();
}

bool TfmVulkan::initialize(std::string *errorOut)
{
    Operation operation{{}, Clock::now() + timeout("TFM_VULKAN_STARTUP_TIMEOUT_MS", 10000)};
    std::unique_lock<std::timed_mutex> lock(gate(), std::defer_lock);
    while (!lock.try_lock_for(std::chrono::milliseconds(20))) {
        if (operation.interrupted()) { if (errorOut) *errorOut = operation.result({}).message; return false; }
    }
    ++worker().generation;
    disarmIdle();
    std::string error;
    const bool ok = ensureWorker(error, operation);
    if (ok) armIdle();
    else if (operation.status == Status::Success) operation.status = Status::Unavailable;
    if (errorOut) *errorOut = ok ? std::string() : operation.result(error).message;
    return ok;
}

bool TfmVulkan::isInitialized() const
{
    std::lock_guard<std::mutex> self(m_mutex);
    std::lock_guard<std::timed_mutex> lock(gate());
    return worker().ready;
}

std::string TfmVulkan::deviceName() const
{
    std::lock_guard<std::mutex> self(m_mutex);
    std::lock_guard<std::timed_mutex> lock(gate());
    return worker().name;
}

bool TfmVulkan::supportsShaderFloat64() const
{
    std::lock_guard<std::mutex> self(m_mutex);
    std::lock_guard<std::timed_mutex> lock(gate());
    return worker().ready && worker().float64;
}

bool TfmVulkan::dispatch(const std::vector<std::uint32_t> &spirv,
                               const void *inputData, std::size_t inputSize,
                               const void *parametersData, std::size_t parametersSize,
                               std::size_t outputSize, const Dispatch &config,
                               std::vector<std::uint8_t> &outputData, std::string *errorOut)
{
    const Result result = dispatchResult(spirv, inputData, inputSize, parametersData,
                                         parametersSize, outputSize, config, outputData);
    if (errorOut) *errorOut = result.message;
    return bool(result);
}

TfmVulkan::Result TfmVulkan::dispatchResult(const std::vector<std::uint32_t> &spirv,
                               const void *inputData, std::size_t inputSize,
                               const void *parametersData, std::size_t parametersSize,
                               std::size_t outputSize, const Dispatch &config,
                               std::vector<std::uint8_t> &outputData)
{
    auto fail = [](const std::string &message) { return Result{Status::ProtocolError, message}; };
    constexpr std::size_t budget = 128ull * 1024 * 1024;
    if (inputSize > budget || outputSize > budget || parametersSize > budget)
        return fail("Vulkan buffer exceeds 128 MiB processing budget");
    if (spirv.size() > budget / sizeof(std::uint32_t) || spirv.empty() || spirv.front() != 0x07230203u || (spirv.size() * sizeof(std::uint32_t)) % 4 != 0)
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

    Operation operation{config.cancelled, Clock::now() + timeout("TFM_VULKAN_STARTUP_TIMEOUT_MS", 10000)};
    if (operation.interrupted()) return operation.result({});
    std::unique_lock<std::timed_mutex> lock(gate(), std::defer_lock);
    // Waiting for another filter belongs to this request's computation budget.
    operation.deadline = Clock::now() + timeout("TFM_VULKAN_DISPATCH_TIMEOUT_MS", 120000);
    while (!lock.try_lock_for(std::chrono::milliseconds(20))) {
        if (operation.interrupted()) return operation.result({});
    }
    ++worker().generation;
    disarmIdle();
    operation.deadline = Clock::now() + timeout("TFM_VULKAN_STARTUP_TIMEOUT_MS", 10000);
    try {
        std::string error;
        if (!ensureWorker(error, operation)) {
            if (operation.status == Status::Success) operation.status = Status::Unavailable;
            return operation.result(error);
        }
        operation.deadline = Clock::now() + timeout("TFM_VULKAN_DISPATCH_TIMEOUT_MS", 120000);
        const bool ok = sendDispatch(spirv, inputData, inputSize, parametersData, parametersSize,
                                      outputSize, config, outputData, error, operation);
        if (worker().ready) armIdle();
        if (!ok) return operation.result(error);
        return {};
    } catch (const std::exception &) {
        // Allocation/thread-start failures after sending may leave unread protocol
        // bytes. Never return this connection to the next request or leave idle off.
        abandonProcess();
        return {Status::Unavailable, "Vulkan client resource allocation failed"};
    }
}
