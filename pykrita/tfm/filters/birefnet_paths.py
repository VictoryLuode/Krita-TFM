"""BiRefNet model/runtime folder helpers for the Filters settings UI."""

from __future__ import annotations

import os

from ..i18n import tr


def birefnet_root_dir():
    from . import settings as filter_settings

    root = filter_settings.resource_directory()
    if not root:
        return ""
    return os.path.join(root, "TFM", "background-removal")


def birefnet_models_dir():
    root = birefnet_root_dir()
    return os.path.join(root, "models") if root else ""


def birefnet_runtime_dir():
    root = birefnet_root_dir()
    return os.path.join(root, "runtime") if root else ""


def ensure_birefnet_models_readme(models):
    readme = os.path.join(models, "README.txt")
    if os.path.isfile(readme):
        return
    body = (
        "TFM Background Removal — BiRefNet models\n"
        "========================================\n"
        "\n"
        "Place BiRefNet .gguf weights in this folder, then reopen the filter:\n"
        "  - BiRefNet-lite-F16.gguf\n"
        "  - BiRefNet-dynamic-F16.gguf\n"
        "\n"
        "Models are optional and are not shipped inside the TFM zip.\n"
        "Obtain compatible GGUF builds from the project release notes / docs,\n"
        "then keep filenames exactly as above (or pick them in the filter UI).\n"
        "\n"
        "Optional Vulkan/GGML runtime DLLs go in the sibling runtime/ folder.\n"
    )
    try:
        with open(readme, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
    except OSError:
        pass


def ensure_birefnet_runtime_readme(runtime):
    readme = os.path.join(runtime, "README.txt")
    if os.path.isfile(readme):
        return
    body = (
        "TFM Background Removal — optional inference runtime\n"
        "===================================================\n"
        "\n"
        "Place optional Vulkan/GGML runtime DLLs here when the built-in\n"
        "CPU path is not enough. Models still live in the sibling models/\n"
        "folder. Runtime files are not shipped in the default TFM zip;\n"
        "see docs/gegl-isolated-runtime.md before redistributing them.\n"
    )
    try:
        with open(readme, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
    except OSError:
        pass


def open_birefnet_dir(directory, ensure_readme, set_status):
    if not directory:
        set_status(tr(
            "Could not locate Krita’s resource directory.",
            "无法定位 Krita 资源目录。",
        ))
        return
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as error:
        set_status(str(error))
        return
    ensure_readme(directory)
    from qtcompat import QDesktopServices, QUrl
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(directory)):
        set_status(tr("Could not open {}.", "无法打开 {}。").format(directory))


def models_status_tip(models_dir):
    if not models_dir:
        return tr(
            "Could not locate Krita’s resource directory. "
            "Models belong in ResourceDirectory/TFM/background-removal/models/.",
            "无法定位 Krita 资源目录。模型应放在 ResourceDirectory/TFM/background-removal/models/。",
        )
    try:
        names = [name for name in os.listdir(models_dir) if name.lower().endswith(".gguf")]
    except OSError:
        names = []
    if names:
        return tr(
            "Models found in {} ({}).",
            "已在 {} 找到模型（{}）。",
        ).format(models_dir, ", ".join(sorted(names)[:4]))
    return tr(
        "No .gguf models in {}. Download BiRefNet into that folder (buttons below open models/runtime), then reopen this filter.",
        "{} 中没有 .gguf 模型。请把 BiRefNet 下载到该文件夹（下方按钮可打开 models/runtime），然后重新打开此滤镜。",
    ).format(models_dir)
