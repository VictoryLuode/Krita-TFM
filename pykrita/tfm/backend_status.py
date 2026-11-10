"""Backend diagnostics shared by the manager and runtime status surfaces."""
from i18n import tr


def backend_action_tip(reason):
    lowered = reason.lower()
    if 'worker is not installed' in lowered or 'tfm_vulkan_worker' in lowered:
        return tr(
            'Action: copy tfm_vulkan_worker.exe next to kritatfm.dll in Krita’s kritaplugins folder, then retry or switch the filter to CPU.',
            '操作：把 tfm_vulkan_worker.exe 拷到 kritatfm.dll 同目录（Krita 的 kritaplugins），然后重试或将该滤镜改为 CPU。',
        )
    if 'timeout' in lowered or 'closed before' in lowered or 'failed to create a device' in lowered:
        return tr(
            'Action: switch this filter’s Compute backend to CPU, or set Default filter backend to CPU in Settings, then retry.',
            '操作：将该滤镜的计算后端改为 CPU，或在设置里把默认滤镜后端设为 CPU，然后重试。',
        )
    if 'birefnet model not found' in lowered or 'model not found' in lowered:
        return tr(
            'Action: place a BiRefNet .gguf under ResourceDirectory/TFM/background-removal/models/, then reopen the filter.',
            '操作：把 BiRefNet 的 .gguf 模型放到 ResourceDirectory/TFM/background-removal/models/，然后重新打开滤镜。',
        )
    if 'vulkan disabled' in lowered:
        return tr(
            'Action: unset TFM_VULKAN_DISABLE, or keep using CPU for this filter.',
            '操作：取消环境变量 TFM_VULKAN_DISABLE，或继续对该滤镜使用 CPU。',
        )
    return ''
