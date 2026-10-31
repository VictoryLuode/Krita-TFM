#include "fxmanager_vulkan.h"

#include <algorithm>
#include <cstring>
#include <limits>
#include <sstream>
#include <utility>
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan_core.h>

#if defined(_WIN32)
#  define NOMINMAX
#  include <windows.h>
#else
#  include <dlfcn.h>
#endif

namespace
{
#if defined(_WIN32)
using Library = HMODULE;
void *loadSymbol(Library lib, const char *name) { return reinterpret_cast<void *>(GetProcAddress(lib, name)); }
#else
using Library = void *;
void *loadSymbol(Library lib, const char *name) { return dlsym(lib, name); }
#endif

template<typename T> bool loadProc(Library lib, const char *name, T &out)
{
    out = reinterpret_cast<T>(loadSymbol(lib, name));
    return out != nullptr;
}

std::string resultMessage(const char *operation, VkResult result)
{
    std::ostringstream s;
    s << operation << " failed (VkResult " << result << ')';
    return s.str();
}
}

struct FxManagerVulkan::Impl
{
    Library library = nullptr;
    VkInstance instance = nullptr;
    VkPhysicalDevice physicalDevice = nullptr;
    VkDevice device = nullptr;
    VkQueue queue = nullptr;
    VkCommandPool commandPool = VK_NULL_HANDLE;
    std::uint32_t queueFamily = 0;
    std::uint32_t memoryTypeCount = 0;
    VkMemoryType memoryTypes[32]{};
    std::string gpuName;

#define FX_VK_PROC(name) decltype(&::vk##name) name = nullptr
    // Function pointer signatures are listed explicitly below; no Vulkan
    // declarations or symbols are imported from the SDK or loader.
    using CreateInstanceFn = PFN_vkCreateInstance;
    using DestroyInstanceFn = PFN_vkDestroyInstance;
    using EnumeratePhysicalDevicesFn = PFN_vkEnumeratePhysicalDevices;
    using GetPhysicalDevicePropertiesFn = PFN_vkGetPhysicalDeviceProperties;
    using GetPhysicalDeviceQueueFamilyPropertiesFn = PFN_vkGetPhysicalDeviceQueueFamilyProperties;
    using GetPhysicalDeviceMemoryPropertiesFn = PFN_vkGetPhysicalDeviceMemoryProperties;
    using CreateDeviceFn = PFN_vkCreateDevice;
    using DestroyDeviceFn = PFN_vkDestroyDevice;
    using GetDeviceQueueFn = PFN_vkGetDeviceQueue;
    using CreateCommandPoolFn = PFN_vkCreateCommandPool;
    using DestroyCommandPoolFn = PFN_vkDestroyCommandPool;
    using CreateBufferFn = PFN_vkCreateBuffer;
    using DestroyBufferFn = PFN_vkDestroyBuffer;
    using GetBufferMemoryRequirementsFn = PFN_vkGetBufferMemoryRequirements;
    using AllocateMemoryFn = PFN_vkAllocateMemory;
    using FreeMemoryFn = PFN_vkFreeMemory;
    using BindBufferMemoryFn = PFN_vkBindBufferMemory;
    using MapMemoryFn = PFN_vkMapMemory;
    using UnmapMemoryFn = PFN_vkUnmapMemory;
    using CreateShaderModuleFn = PFN_vkCreateShaderModule;
    using DestroyShaderModuleFn = PFN_vkDestroyShaderModule;
    using CreateDescriptorSetLayoutFn = PFN_vkCreateDescriptorSetLayout;
    using DestroyDescriptorSetLayoutFn = PFN_vkDestroyDescriptorSetLayout;
    using CreatePipelineLayoutFn = PFN_vkCreatePipelineLayout;
    using DestroyPipelineLayoutFn = PFN_vkDestroyPipelineLayout;
    using CreateComputePipelinesFn = PFN_vkCreateComputePipelines;
    using DestroyPipelineFn = PFN_vkDestroyPipeline;
    using CreateDescriptorPoolFn = PFN_vkCreateDescriptorPool;
    using DestroyDescriptorPoolFn = PFN_vkDestroyDescriptorPool;
    using AllocateDescriptorSetsFn = PFN_vkAllocateDescriptorSets;
    using UpdateDescriptorSetsFn = PFN_vkUpdateDescriptorSets;
    using AllocateCommandBuffersFn = PFN_vkAllocateCommandBuffers;
    using FreeCommandBuffersFn = PFN_vkFreeCommandBuffers;
    using BeginCommandBufferFn = PFN_vkBeginCommandBuffer;
    using EndCommandBufferFn = PFN_vkEndCommandBuffer;
    using CmdBindPipelineFn = PFN_vkCmdBindPipeline;
    using CmdBindDescriptorSetsFn = PFN_vkCmdBindDescriptorSets;
    using CmdDispatchFn = PFN_vkCmdDispatch;
    using CmdPipelineBarrierFn = PFN_vkCmdPipelineBarrier;
    using CreateFenceFn = PFN_vkCreateFence;
    using DestroyFenceFn = PFN_vkDestroyFence;
    using QueueSubmitFn = PFN_vkQueueSubmit;
    using WaitForFencesFn = PFN_vkWaitForFences;
    using DeviceWaitIdleFn = PFN_vkDeviceWaitIdle;

    CreateInstanceFn createInstance = nullptr;
    DestroyInstanceFn destroyInstance = nullptr;
    EnumeratePhysicalDevicesFn enumeratePhysicalDevices = nullptr;
    GetPhysicalDevicePropertiesFn getPhysicalDeviceProperties = nullptr;
    GetPhysicalDeviceQueueFamilyPropertiesFn getQueueFamilies = nullptr;
    GetPhysicalDeviceMemoryPropertiesFn getMemoryProperties = nullptr;
    CreateDeviceFn createDevice = nullptr;
    DestroyDeviceFn destroyDevice = nullptr;
    GetDeviceQueueFn getDeviceQueue = nullptr;
    CreateCommandPoolFn createCommandPool = nullptr;
    DestroyCommandPoolFn destroyCommandPool = nullptr;
    CreateBufferFn createBuffer = nullptr;
    DestroyBufferFn destroyBuffer = nullptr;
    GetBufferMemoryRequirementsFn getBufferMemoryRequirements = nullptr;
    AllocateMemoryFn allocateMemory = nullptr;
    FreeMemoryFn freeMemory = nullptr;
    BindBufferMemoryFn bindBufferMemory = nullptr;
    MapMemoryFn mapMemory = nullptr;
    UnmapMemoryFn unmapMemory = nullptr;
    CreateShaderModuleFn createShaderModule = nullptr;
    DestroyShaderModuleFn destroyShaderModule = nullptr;
    CreateDescriptorSetLayoutFn createDescriptorSetLayout = nullptr;
    DestroyDescriptorSetLayoutFn destroyDescriptorSetLayout = nullptr;
    CreatePipelineLayoutFn createPipelineLayout = nullptr;
    DestroyPipelineLayoutFn destroyPipelineLayout = nullptr;
    CreateComputePipelinesFn createComputePipelines = nullptr;
    DestroyPipelineFn destroyPipeline = nullptr;
    CreateDescriptorPoolFn createDescriptorPool = nullptr;
    DestroyDescriptorPoolFn destroyDescriptorPool = nullptr;
    AllocateDescriptorSetsFn allocateDescriptorSets = nullptr;
    UpdateDescriptorSetsFn updateDescriptorSets = nullptr;
    AllocateCommandBuffersFn allocateCommandBuffers = nullptr;
    FreeCommandBuffersFn freeCommandBuffers = nullptr;
    BeginCommandBufferFn beginCommandBuffer = nullptr;
    EndCommandBufferFn endCommandBuffer = nullptr;
    CmdBindPipelineFn cmdBindPipeline = nullptr;
    CmdBindDescriptorSetsFn cmdBindDescriptorSets = nullptr;
    CmdDispatchFn cmdDispatch = nullptr;
    CmdPipelineBarrierFn cmdPipelineBarrier = nullptr;
    CreateFenceFn createFence = nullptr;
    DestroyFenceFn destroyFence = nullptr;
    QueueSubmitFn queueSubmit = nullptr;
    WaitForFencesFn waitForFences = nullptr;
    DeviceWaitIdleFn deviceWaitIdle = nullptr;
#undef FX_VK_PROC

    ~Impl() { shutdown(); }

    void shutdown()
    {
        if (device) {
            if (deviceWaitIdle) deviceWaitIdle(device);
            if (commandPool && destroyCommandPool) destroyCommandPool(device, commandPool, nullptr);
            if (destroyDevice) destroyDevice(device, nullptr);
            device = nullptr;
        }
        if (instance && destroyInstance) destroyInstance(instance, nullptr);
        instance = nullptr;
#if defined(_WIN32)
        if (library) FreeLibrary(library);
#else
        if (library) dlclose(library);
#endif
        library = nullptr;
        physicalDevice = nullptr; queue = nullptr; commandPool = VK_NULL_HANDLE;
        gpuName.clear(); memoryTypeCount = 0;
    }

    bool loadGlobal(std::string &error)
    {
#if defined(_WIN32)
        library = LoadLibraryW(L"vulkan-1.dll");
#elif defined(__APPLE__)
        library = dlopen("libvulkan.1.dylib", RTLD_NOW | RTLD_LOCAL);
        if (!library) library = dlopen("libvulkan.dylib", RTLD_NOW | RTLD_LOCAL);
#else
        library = dlopen("libvulkan.so.1", RTLD_NOW | RTLD_LOCAL);
        if (!library) library = dlopen("libvulkan.so", RTLD_NOW | RTLD_LOCAL);
#endif
        if (!library) { error = "Unable to load the system Vulkan loader"; return false; }
#define LOAD_GLOBAL(field, symbol) if (!loadProc(library, symbol, field)) { error = std::string("Missing Vulkan entry point: ") + symbol; return false; }
        LOAD_GLOBAL(createInstance, "vkCreateInstance");
#undef LOAD_GLOBAL
        return true;
    }

    template<typename T> bool loadInstanceProc(const char *name, T &out)
    {
        out = reinterpret_cast<T>(loadSymbol(library, name));
        return out != nullptr;
    }

    bool loadInstanceFunctions(std::string &error)
    {
#define LOAD_INSTANCE(field, symbol) if (!loadInstanceProc(symbol, field)) { error = std::string("Missing Vulkan entry point: ") + symbol; return false; }
        LOAD_INSTANCE(destroyInstance, "vkDestroyInstance");
        LOAD_INSTANCE(enumeratePhysicalDevices, "vkEnumeratePhysicalDevices");
        LOAD_INSTANCE(getPhysicalDeviceProperties, "vkGetPhysicalDeviceProperties");
        LOAD_INSTANCE(getQueueFamilies, "vkGetPhysicalDeviceQueueFamilyProperties");
        LOAD_INSTANCE(getMemoryProperties, "vkGetPhysicalDeviceMemoryProperties");
        LOAD_INSTANCE(createDevice, "vkCreateDevice");
        LOAD_INSTANCE(destroyDevice, "vkDestroyDevice");
        LOAD_INSTANCE(getDeviceQueue, "vkGetDeviceQueue");
        LOAD_INSTANCE(createCommandPool, "vkCreateCommandPool");
        LOAD_INSTANCE(destroyCommandPool, "vkDestroyCommandPool");
        LOAD_INSTANCE(createBuffer, "vkCreateBuffer");
        LOAD_INSTANCE(destroyBuffer, "vkDestroyBuffer");
        LOAD_INSTANCE(getBufferMemoryRequirements, "vkGetBufferMemoryRequirements");
        LOAD_INSTANCE(allocateMemory, "vkAllocateMemory");
        LOAD_INSTANCE(freeMemory, "vkFreeMemory");
        LOAD_INSTANCE(bindBufferMemory, "vkBindBufferMemory");
        LOAD_INSTANCE(mapMemory, "vkMapMemory");
        LOAD_INSTANCE(unmapMemory, "vkUnmapMemory");
        LOAD_INSTANCE(createShaderModule, "vkCreateShaderModule");
        LOAD_INSTANCE(destroyShaderModule, "vkDestroyShaderModule");
        LOAD_INSTANCE(createDescriptorSetLayout, "vkCreateDescriptorSetLayout");
        LOAD_INSTANCE(destroyDescriptorSetLayout, "vkDestroyDescriptorSetLayout");
        LOAD_INSTANCE(createPipelineLayout, "vkCreatePipelineLayout");
        LOAD_INSTANCE(destroyPipelineLayout, "vkDestroyPipelineLayout");
        LOAD_INSTANCE(createComputePipelines, "vkCreateComputePipelines");
        LOAD_INSTANCE(destroyPipeline, "vkDestroyPipeline");
        LOAD_INSTANCE(createDescriptorPool, "vkCreateDescriptorPool");
        LOAD_INSTANCE(destroyDescriptorPool, "vkDestroyDescriptorPool");
        LOAD_INSTANCE(allocateDescriptorSets, "vkAllocateDescriptorSets");
        LOAD_INSTANCE(updateDescriptorSets, "vkUpdateDescriptorSets");
        LOAD_INSTANCE(allocateCommandBuffers, "vkAllocateCommandBuffers");
        LOAD_INSTANCE(freeCommandBuffers, "vkFreeCommandBuffers");
        LOAD_INSTANCE(beginCommandBuffer, "vkBeginCommandBuffer");
        LOAD_INSTANCE(endCommandBuffer, "vkEndCommandBuffer");
        LOAD_INSTANCE(cmdBindPipeline, "vkCmdBindPipeline");
        LOAD_INSTANCE(cmdBindDescriptorSets, "vkCmdBindDescriptorSets");
        LOAD_INSTANCE(cmdDispatch, "vkCmdDispatch");
        LOAD_INSTANCE(cmdPipelineBarrier, "vkCmdPipelineBarrier");
        LOAD_INSTANCE(createFence, "vkCreateFence");
        LOAD_INSTANCE(destroyFence, "vkDestroyFence");
        LOAD_INSTANCE(queueSubmit, "vkQueueSubmit");
        LOAD_INSTANCE(waitForFences, "vkWaitForFences");
        LOAD_INSTANCE(deviceWaitIdle, "vkDeviceWaitIdle");
#undef LOAD_INSTANCE
        return true;
    }

    bool findMemoryType(std::uint32_t bits, VkMemoryPropertyFlags required, std::uint32_t &index) const
    {
        for (std::uint32_t i = 0; i < memoryTypeCount; ++i) {
            if ((bits & (1u << i)) && (memoryTypes[i].propertyFlags & required) == required) {
                index = i;
                return true;
            }
        }
        return false;
    }

    struct Buffer { VkBuffer handle = VK_NULL_HANDLE; VkDeviceMemory memory = VK_NULL_HANDLE; VkDeviceSize size = 0; };

    void destroyBufferObject(Buffer &b)
    {
        if (b.handle) destroyBuffer(device, b.handle, nullptr);
        if (b.memory) freeMemory(device, b.memory, nullptr);
        b = {};
    }

    bool makeBuffer(std::size_t size, Buffer &buffer, std::string &error)
    {
        buffer.size = std::max<std::size_t>(size, 4);
        VkBufferCreateInfo info{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, nullptr, 0, buffer.size,
                                VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, VK_SHARING_MODE_EXCLUSIVE, 0, nullptr};
        VkResult r = createBuffer(device, &info, nullptr, &buffer.handle);
        if (r != VK_SUCCESS) { error = resultMessage("vkCreateBuffer", r); return false; }
        VkMemoryRequirements requirements{};
        getBufferMemoryRequirements(device, buffer.handle, &requirements);
        std::uint32_t memoryIndex = 0;
        if (!findMemoryType(requirements.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT, memoryIndex)) {
            error = "No coherent host-visible Vulkan memory type for storage buffer";
            destroyBufferObject(buffer);
            return false;
        }
        VkMemoryAllocateInfo allocation{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, nullptr, requirements.size, memoryIndex};
        r = allocateMemory(device, &allocation, nullptr, &buffer.memory);
        if (r != VK_SUCCESS) { error = resultMessage("vkAllocateMemory", r); destroyBufferObject(buffer); return false; }
        r = bindBufferMemory(device, buffer.handle, buffer.memory, 0);
        if (r != VK_SUCCESS) { error = resultMessage("vkBindBufferMemory", r); destroyBufferObject(buffer); return false; }
        return true;
    }

    bool writeBuffer(const Buffer &buffer, const void *data, std::size_t size, std::string &error)
    {
        if (!size) return true;
        void *mapped = nullptr;
        VkResult r = mapMemory(device, buffer.memory, 0, buffer.size, 0, &mapped);
        if (r != VK_SUCCESS) { error = resultMessage("vkMapMemory", r); return false; }
        std::memcpy(mapped, data, size);
        unmapMemory(device, buffer.memory);
        return true;
    }

    bool readBuffer(const Buffer &buffer, void *data, std::size_t size, std::string &error)
    {
        if (!size) return true;
        void *mapped = nullptr;
        VkResult r = mapMemory(device, buffer.memory, 0, buffer.size, 0, &mapped);
        if (r != VK_SUCCESS) { error = resultMessage("vkMapMemory", r); return false; }
        std::memcpy(data, mapped, size);
        unmapMemory(device, buffer.memory);
        return true;
    }
};

FxManagerVulkan::FxManagerVulkan() : m_impl(std::make_unique<Impl>()) {}
FxManagerVulkan::~FxManagerVulkan() = default;

bool FxManagerVulkan::initialize(std::string *errorOut)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    auto fail = [&](const std::string &message) { if (errorOut) *errorOut = message; return false; };
    if (m_impl->device) return true;
    m_impl->shutdown();
    std::string error;
    if (!m_impl->loadGlobal(error)) { m_impl->shutdown(); return fail(error); }

    VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO, nullptr, "Krita FxManager", 1, "FxManager", 1, VK_API_VERSION_1_0};
    VkInstanceCreateInfo instanceInfo{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, nullptr, 0, &app, 0, nullptr, 0, nullptr};
    VkResult r = m_impl->createInstance(&instanceInfo, nullptr, &m_impl->instance);
    if (r != VK_SUCCESS) { m_impl->shutdown(); return fail(resultMessage("vkCreateInstance", r)); }
    if (!m_impl->loadInstanceFunctions(error)) { m_impl->shutdown(); return fail(error); }

    std::uint32_t count = 0;
    r = m_impl->enumeratePhysicalDevices(m_impl->instance, &count, nullptr);
    if (r != VK_SUCCESS || !count) { m_impl->shutdown(); return fail(r == VK_SUCCESS ? "No Vulkan physical devices found" : resultMessage("vkEnumeratePhysicalDevices", r)); }
    std::vector<VkPhysicalDevice> devices(count);
    r = m_impl->enumeratePhysicalDevices(m_impl->instance, &count, devices.data());
    if (r != VK_SUCCESS) { m_impl->shutdown(); return fail(resultMessage("vkEnumeratePhysicalDevices", r)); }

    int bestScore = std::numeric_limits<int>::min();
    for (VkPhysicalDevice candidate : devices) {
        VkPhysicalDeviceProperties properties{};
        m_impl->getPhysicalDeviceProperties(candidate, &properties);
        std::uint32_t familyCount = 0;
        m_impl->getQueueFamilies(candidate, &familyCount, nullptr);
        std::vector<VkQueueFamilyProperties> families(familyCount);
        if (familyCount) m_impl->getQueueFamilies(candidate, &familyCount, families.data());
        for (std::uint32_t i = 0; i < familyCount; ++i) {
            if (!(families[i].queueFlags & VK_QUEUE_COMPUTE_BIT) || !families[i].queueCount) continue;
            const int score = (properties.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU ? 1000000 : 0)
                              + static_cast<int>(std::min<VkDeviceSize>(properties.limits.maxStorageBufferRange, 100000));
            if (score > bestScore) {
                bestScore = score;
                m_impl->physicalDevice = candidate;
                m_impl->queueFamily = i;
                m_impl->gpuName = properties.deviceName;
            }
            break;
        }
    }
    if (!m_impl->physicalDevice) { m_impl->shutdown(); return fail("No Vulkan device with a compute queue found"); }

    const float priority = 1.0f;
    VkDeviceQueueCreateInfo queueInfo{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, nullptr, 0, m_impl->queueFamily, 1, &priority};
    VkDeviceCreateInfo deviceInfo{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, nullptr, 0, 1, &queueInfo, 0, nullptr, 0, nullptr, nullptr};
    r = m_impl->createDevice(m_impl->physicalDevice, &deviceInfo, nullptr, &m_impl->device);
    if (r != VK_SUCCESS) { m_impl->shutdown(); return fail(resultMessage("vkCreateDevice", r)); }
    m_impl->getDeviceQueue(m_impl->device, m_impl->queueFamily, 0, &m_impl->queue);

    VkPhysicalDeviceMemoryProperties memoryProperties{};
    m_impl->getMemoryProperties(m_impl->physicalDevice, &memoryProperties);
    m_impl->memoryTypeCount = std::min<std::uint32_t>(memoryProperties.memoryTypeCount, 32);
    std::copy(memoryProperties.memoryTypes, memoryProperties.memoryTypes + m_impl->memoryTypeCount, m_impl->memoryTypes);

    VkCommandPoolCreateInfo poolInfo{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, nullptr, VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT, m_impl->queueFamily};
    r = m_impl->createCommandPool(m_impl->device, &poolInfo, nullptr, &m_impl->commandPool);
    if (r != VK_SUCCESS) { m_impl->shutdown(); return fail(resultMessage("vkCreateCommandPool", r)); }
    if (errorOut) errorOut->clear();
    return true;
}

bool FxManagerVulkan::isInitialized() const
{
    std::lock_guard<std::mutex> lock(m_mutex);
    return m_impl->device != nullptr;
}

std::string FxManagerVulkan::deviceName() const
{
    std::lock_guard<std::mutex> lock(m_mutex);
    return m_impl->gpuName;
}

bool FxManagerVulkan::dispatch(const std::vector<std::uint32_t> &spirv,
                               const void *inputData, std::size_t inputSize,
                               const void *parametersData, std::size_t parametersSize,
                               std::size_t outputSize, const Dispatch &config,
                               std::vector<std::uint8_t> &outputData,
                               std::string *errorOut)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    auto fail = [&](const std::string &message) { if (errorOut) *errorOut = message; return false; };
    if (!m_impl->device) return fail("Vulkan service is not initialized");
    constexpr std::size_t budget = 128ULL * 1024 * 1024;
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
    if (config.inputBinding == config.outputBinding || config.inputBinding == config.parametersBinding || config.outputBinding == config.parametersBinding)
        return fail("Descriptor binding numbers must be distinct");

    using Buffer = Impl::Buffer;
    Buffer input, output, parameters;
    VkShaderModule shader = VK_NULL_HANDLE;
    VkDescriptorSetLayout setLayout = VK_NULL_HANDLE;
    VkPipelineLayout pipelineLayout = VK_NULL_HANDLE;
    VkPipeline pipeline = VK_NULL_HANDLE;
    VkDescriptorPool descriptorPool = VK_NULL_HANDLE;
    VkCommandBuffer command = nullptr;
    VkFence fence = VK_NULL_HANDLE;
    std::string error;
    auto cleanup = [&] {
        if (fence) m_impl->destroyFence(m_impl->device, fence, nullptr);
        if (command) m_impl->freeCommandBuffers(m_impl->device, m_impl->commandPool, 1, &command);
        if (descriptorPool) m_impl->destroyDescriptorPool(m_impl->device, descriptorPool, nullptr);
        if (pipeline) m_impl->destroyPipeline(m_impl->device, pipeline, nullptr);
        if (pipelineLayout) m_impl->destroyPipelineLayout(m_impl->device, pipelineLayout, nullptr);
        if (setLayout) m_impl->destroyDescriptorSetLayout(m_impl->device, setLayout, nullptr);
        if (shader) m_impl->destroyShaderModule(m_impl->device, shader, nullptr);
        m_impl->destroyBufferObject(parameters);
        m_impl->destroyBufferObject(output);
        m_impl->destroyBufferObject(input);
    };
    auto failCleanup = [&](const std::string &message) { cleanup(); return fail(message); };

    if (!m_impl->makeBuffer(inputSize, input, error) || !m_impl->makeBuffer(outputSize, output, error)
        || (parametersSize && !m_impl->makeBuffer(parametersSize, parameters, error))) return failCleanup(error);
    if (!m_impl->writeBuffer(input, inputData, inputSize, error)
        || (parametersSize && !m_impl->writeBuffer(parameters, parametersData, parametersSize, error))) return failCleanup(error);

    VkShaderModuleCreateInfo shaderInfo{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, nullptr, 0, spirv.size() * sizeof(std::uint32_t), spirv.data()};
    VkResult r = m_impl->createShaderModule(m_impl->device, &shaderInfo, nullptr, &shader);
    if (r != VK_SUCCESS) return failCleanup(resultMessage("vkCreateShaderModule", r));

    VkDescriptorSetLayoutBinding bindings[3]{};
    std::uint32_t bindingCount = 0;
    auto addBinding = [&](std::uint32_t binding) { bindings[bindingCount++] = {binding, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr}; };
    addBinding(config.inputBinding);
    addBinding(config.outputBinding);
    if (parametersSize) {
        if (config.parametersBinding == UINT32_MAX) return failCleanup("parametersBinding must be set when parametersData is provided");
        addBinding(config.parametersBinding);
    }
    std::sort(bindings, bindings + bindingCount, [](const auto &a, const auto &b) { return a.binding < b.binding; });
    VkDescriptorSetLayoutCreateInfo layoutInfo{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, nullptr, 0, bindingCount, bindings};
    r = m_impl->createDescriptorSetLayout(m_impl->device, &layoutInfo, nullptr, &setLayout);
    if (r != VK_SUCCESS) return failCleanup(resultMessage("vkCreateDescriptorSetLayout", r));

    VkPipelineLayoutCreateInfo pipelineLayoutInfo{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, nullptr, 0, 1, &setLayout, 0, nullptr};
    r = m_impl->createPipelineLayout(m_impl->device, &pipelineLayoutInfo, nullptr, &pipelineLayout);
    if (r != VK_SUCCESS) return failCleanup(resultMessage("vkCreatePipelineLayout", r));
    VkPipelineShaderStageCreateInfo stage{VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, nullptr, 0, VK_SHADER_STAGE_COMPUTE_BIT, shader, "main", nullptr};
    VkComputePipelineCreateInfo pipelineInfo{VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, nullptr, 0, stage, pipelineLayout, 0, -1};
    r = m_impl->createComputePipelines(m_impl->device, VK_NULL_HANDLE, 1, &pipelineInfo, nullptr, &pipeline);
    if (r != VK_SUCCESS) return failCleanup(resultMessage("vkCreateComputePipelines", r));

    VkDescriptorPoolSize poolSize{VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, bindingCount};
    VkDescriptorPoolCreateInfo poolInfo{VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, nullptr, 0, 1, 1, &poolSize};
    r = m_impl->createDescriptorPool(m_impl->device, &poolInfo, nullptr, &descriptorPool);
    if (r != VK_SUCCESS) return failCleanup(resultMessage("vkCreateDescriptorPool", r));
    VkDescriptorSetAllocateInfo setInfo{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, nullptr, descriptorPool, 1, &setLayout};
    VkDescriptorSet descriptorSet = VK_NULL_HANDLE;
    r = m_impl->allocateDescriptorSets(m_impl->device, &setInfo, &descriptorSet);
    if (r != VK_SUCCESS) return failCleanup(resultMessage("vkAllocateDescriptorSets", r));

    VkDescriptorBufferInfo bufferInfos[3]{};
    VkWriteDescriptorSet writes[3]{};
    std::uint32_t writeCount = 0;
    auto addWrite = [&](std::uint32_t binding, const Buffer &b) {
        bufferInfos[writeCount] = {b.handle, 0, b.size};
        writes[writeCount] = {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, nullptr, descriptorSet, binding, 0, 1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, nullptr, &bufferInfos[writeCount], nullptr};
        ++writeCount;
    };
    addWrite(config.inputBinding, input);
    addWrite(config.outputBinding, output);
    if (parametersSize) addWrite(config.parametersBinding, parameters);
    m_impl->updateDescriptorSets(m_impl->device, writeCount, writes, 0, nullptr);

    VkCommandBufferAllocateInfo commandInfo{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, nullptr, m_impl->commandPool, VK_COMMAND_BUFFER_LEVEL_PRIMARY, 1};
    r = m_impl->allocateCommandBuffers(m_impl->device, &commandInfo, &command);
    if (r != VK_SUCCESS) return failCleanup(resultMessage("vkAllocateCommandBuffers", r));
    VkCommandBufferBeginInfo beginInfo{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, nullptr, VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT, nullptr};
    r = m_impl->beginCommandBuffer(command, &beginInfo);
    if (r != VK_SUCCESS) return failCleanup(resultMessage("vkBeginCommandBuffer", r));
    m_impl->cmdBindPipeline(command, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline);
    m_impl->cmdBindDescriptorSets(command, VK_PIPELINE_BIND_POINT_COMPUTE, pipelineLayout, 0, 1, &descriptorSet, 0, nullptr);
    m_impl->cmdDispatch(command, config.groupsX, config.groupsY, config.groupsZ);
    VkBufferMemoryBarrier barrier{VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER, nullptr, VK_ACCESS_SHADER_WRITE_BIT, VK_ACCESS_HOST_READ_BIT, UINT32_MAX, UINT32_MAX, output.handle, 0, VK_WHOLE_SIZE};
    m_impl->cmdPipelineBarrier(command, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 0, nullptr, 1, &barrier, 0, nullptr);
    r = m_impl->endCommandBuffer(command);
    if (r != VK_SUCCESS) return failCleanup(resultMessage("vkEndCommandBuffer", r));

    VkFenceCreateInfo fenceInfo{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO, nullptr, 0};
    r = m_impl->createFence(m_impl->device, &fenceInfo, nullptr, &fence);
    if (r != VK_SUCCESS) return failCleanup(resultMessage("vkCreateFence", r));
    VkSubmitInfo submit{VK_STRUCTURE_TYPE_SUBMIT_INFO, nullptr, 0, nullptr, nullptr, 1, &command, 0, nullptr};
    r = m_impl->queueSubmit(m_impl->queue, 1, &submit, fence);
    if (r != VK_SUCCESS) return failCleanup(resultMessage("vkQueueSubmit", r));
    r = m_impl->waitForFences(m_impl->device, 1, &fence, 1, std::numeric_limits<std::uint64_t>::max());
    if (r != VK_SUCCESS) return failCleanup(resultMessage("vkWaitForFences", r));

    std::vector<std::uint8_t> result(outputSize);
    if (!m_impl->readBuffer(output, result.data(), outputSize, error)) return failCleanup(error);
    outputData.swap(result);
    cleanup();
    if (errorOut) errorOut->clear();
    return true;
}
