// Links the actual plugin IPC implementation; the child is a deliberately
// faulty protocol peer, never the user's installed worker or Krita instance.
#include "fxmanager_vulkan.h"
#include "fxmanager_vulkan_ipc.h"
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <thread>
#include <atomic>

using namespace tfm_vulkan_ipc;
using Clock = std::chrono::steady_clock;
using Status = FxManagerVulkan::Status;

void require(bool ok, const char *message) {
    if (!ok) { std::cerr << message << std::endl; std::exit(1); }
}

int peer() {
    const std::string mode = std::getenv("TFM_PEER_MODE");
    std::ofstream("peer.pid") << GetCurrentProcessId();
    auto read = [](void *data, std::size_t size, std::size_t &moved) {
        DWORD n = 0;
        const bool ok = ReadFile(GetStdHandle(STD_INPUT_HANDLE), data, DWORD(size), &n, nullptr);
        moved = n; return ok;
    };
    auto write = [](const void *data, std::size_t size, std::size_t &moved) {
        DWORD n = 0;
        const bool ok = WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), data, DWORD(size), &n, nullptr);
        moved = n; return ok;
    };
    if (mode == "hello_hang") Sleep(60000);
    if (mode == "hello_bad") { writeU32(write, 0); Sleep(60000); }
    writeMagic(write); writeU32(write, kHello); writeU32(write, mode != "unavailable");
    writeU32(write, 0); writeU32(write, 0); writeU32(write, 0);
    if (mode == "unavailable") return 0;
    if (mode == "write_hang") Sleep(60000);
    for (;;) {
        std::uint32_t kind = 0, sizes[4]{}, layout[6]{};
        if (!readMagic(read) || !readU32(read, kind)) return 0;
        if (kind == kShutdown) return 0;
        if (!readExact(read, sizes, sizeof(sizes)) || !readExact(read, layout, sizeof(layout))) return 1;
        std::vector<std::uint8_t> payload(sizes[0] + sizes[1] + sizes[2]);
        if (!readExact(read, payload.data(), payload.size())) return 1;
        if (mode == "result_hang") Sleep(60000);
        if (mode == "exit") return 0;
        if (mode == "result_bad") { writeU32(write, 0); Sleep(60000); }
        writeMagic(write); writeU32(write, kResult); writeU32(write, 1);
        writeU32(write, 0); writeU32(write, 0);
        std::vector<std::uint8_t> output(sizes[3], 42);
        if (mode == "short") { writeExact(write, output.data(), output.size()/2); return 0; }
        writeExact(write, output.data(), output.size());
    }
}

DWORD childPid() { DWORD pid = 0; std::ifstream("peer.pid") >> pid; return pid; }
bool childExited(DWORD pid) {
    HANDLE process = OpenProcess(SYNCHRONIZE, FALSE, pid);
    if (!process) return true;
    const bool exited = WaitForSingleObject(process, 1000) == WAIT_OBJECT_0;
    CloseHandle(process); return exited;
}

int main(int argc, char **) {
    if (argc == 1) return peer();
    require(LoadLibraryW(L"kritatfm.dll") != nullptr, "fixture DLL load failed");
    SetEnvironmentVariableA("TFM_VULKAN_DISABLE", "0"); _putenv_s("TFM_VULKAN_DISABLE", "0");
    _putenv_s("TFM_VULKAN_STARTUP_TIMEOUT_MS", "250");
    _putenv_s("TFM_VULKAN_DISPATCH_TIMEOUT_MS", "250");
    FxManagerVulkan client;
    std::vector<std::uint32_t> shader{0x07230203};
    std::vector<std::uint8_t> input(4u*1024*1024, 7), output{1,2,3};
    auto run = [&](const char *mode, Status expected, bool cancel) {
        client.shutdown();
        _putenv_s("TFM_PEER_MODE", mode);
        const auto start = Clock::now();
        FxManagerVulkan::Dispatch dispatch;
        dispatch.cancelled = [=] { return cancel && Clock::now()-start > std::chrono::milliseconds(100); };
        output = {1,2,3};
        const auto result = client.dispatchResult(shader,input.data(),input.size(),nullptr,0,1024,dispatch,output);
        const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now()-start).count();
        std::cout << mode << " cancel=" << cancel << " status=" << int(result.status) << " ms=" << ms << " " << result.message << std::endl;
        require(result.status == expected, "incorrect outcome");
        require(ms < 2000, "unbounded operation");
        if (expected == Status::Success) require(output == std::vector<std::uint8_t>(1024,42), "bad successful output");
        else {
            require(output == std::vector<std::uint8_t>({1,2,3}), "failure published partial output");
            require(childExited(childPid()), "owned worker leaked");
        }
    };
    for (const auto mode : {"hello_hang","write_hang","result_hang"}) {
        run(mode, Status::Timeout, false);
        run("success", Status::Success, false);
        run(mode, Status::Cancelled, true);
        run("success", Status::Success, false);
    }
    run("hello_bad", Status::ProtocolError, false);
    run("result_bad", Status::ProtocolError, false);
    run("exit", Status::ProcessExited, false);
    run("short", Status::ProcessExited, false);
    run("unavailable", Status::Unavailable, false);
    run("success", Status::Success, false);
    // The serialized service gate must also be interruptible, without killing
    // a different request's worker.
    client.shutdown(); _putenv_s("TFM_PEER_MODE","result_hang");
    std::atomic<bool> entered{false};
    std::thread busy([&] {
        FxManagerVulkan other; FxManagerVulkan::Dispatch config;
        config.cancelled = [&] { entered = true; return false; };
        std::vector<std::uint8_t> data;
        const auto result = other.dispatchResult(shader,input.data(),input.size(),nullptr,0,1024,config,data);
        require(result.status == Status::Timeout, "cancelled waiter killed another request");
    });
    while (!entered) std::this_thread::yield();
    Sleep(50);
    FxManagerVulkan::Dispatch waiting;
    const auto start = Clock::now();
    waiting.cancelled = [=] { return Clock::now()-start > std::chrono::milliseconds(50); };
    const auto result = client.dispatchResult(shader,input.data(),input.size(),nullptr,0,1024,waiting,output);
    require(result.status == Status::Cancelled, "gate wait ignored cancellation");
    require(Clock::now()-start < std::chrono::milliseconds(200), "gate wait exceeded cancellation bound");
    busy.join();
    run("success", Status::Success, false);
    const auto pid = childPid();
    Sleep(2300);
    require(childExited(pid), "idle shutdown failed");
    client.shutdown();
    std::cout << "Production IPC lifecycle PASS" << std::endl;
}
