"""Settings tab widgets for the TFM manager dialog."""

from __future__ import annotations

import json
import os

from .menus.qtcompat import QtCore, QtWidgets
from .i18n import tr
from .menus.version import __version__


def build_settings_page(dialog, filter_settings, window_width, window_height, on_tab_changed):
    """Create the Settings tab and attach controls onto *dialog*."""
    settings_page = QtWidgets.QWidget()
    settings_layout = QtWidgets.QVBoxLayout(settings_page)
    settings_layout.setContentsMargins(16, 12, 16, 12)
    settings_form = QtWidgets.QFormLayout()

    dialog.default_width = QtWidgets.QSpinBox()
    dialog.default_width.setRange(980, 8192)
    dialog.default_width.setValue(window_width)
    dialog.default_height = QtWidgets.QSpinBox()
    dialog.default_height.setRange(620, 8192)
    dialog.default_height.setValue(window_height)

    dialog.cpu_threads = QtWidgets.QComboBox()
    dialog.cpu_threads.addItem(tr('Auto (safe default: 1)', '自动（安全默认：1）'), 0)
    for count in (1, 2, 4, 6, 8, 12, 16, 24, 32):
        dialog.cpu_threads.addItem(str(count), count)
    filter_options = filter_settings.load()
    cpu = filter_options.get('cpu_threads', 0)
    dialog.cpu_threads.setCurrentIndex(max(0, dialog.cpu_threads.findData(cpu)))
    dialog.cpu_threads.setToolTip(tr(
        'Controls plugin filters using the shared CPU worker pool. Other processing paths may use their own threads.',
        '控制使用共享 CPU 线程池的插件滤镜。其他处理路径可能使用各自的线程。',
    ))

    dialog.gpu_memory_mb = QtWidgets.QSpinBox()
    dialog.gpu_memory_mb.setRange(128, 8192)
    dialog.gpu_memory_mb.setSingleStep(128)
    dialog.gpu_memory_mb.setSuffix(' MB')
    dialog.gpu_memory_mb.setValue(int(filter_options.get('gpu_memory_mb', 1024) or 1024))
    dialog.gpu_memory_mb.setToolTip(tr(
        'Per-buffer Vulkan memory ceiling for GPU filters. Larger values allow bigger images on GPU; '
        'oversized jobs still fall back to CPU. Applies on the next GPU filter run (worker restarts if needed).',
        'GPU 滤镜的单缓冲 Vulkan 显存上限。调大可让更大图走 GPU；超限仍回退 CPU。'
        '下次 GPU 滤镜运行时生效（必要时会重启 worker）。',
    ))

    dialog.filter_backend = QtWidgets.QComboBox()
    for label, value in (
        (tr('Auto (Vulkan when available)', '自动（可用时用 Vulkan）'), 'auto'),
        (tr('CPU', 'CPU'), 'cpu'),
        (tr('GPU (Vulkan)', 'GPU（Vulkan）'), 'gpu'),
    ):
        dialog.filter_backend.addItem(label, value)
    dialog.filter_backend.setCurrentIndex(
        max(0, dialog.filter_backend.findData(filter_options.get('backend', 'auto'))))

    settings_form.addRow(tr('Default window width', '默认窗口宽度'), dialog.default_width)
    settings_form.addRow(tr('Default window height', '默认窗口高度'), dialog.default_height)
    settings_form.addRow(tr('Plugin filters CPU threads', '插件滤镜 CPU 线程'), dialog.cpu_threads)
    settings_form.addRow(tr('GPU memory budget', 'GPU 显存上限'), dialog.gpu_memory_mb)
    settings_form.addRow(tr('Default filter backend', '默认滤镜后端'), dialog.filter_backend)
    settings_layout.addLayout(settings_form)

    backend_note = QtWidgets.QLabel(tr(
        'Default for filters that support Vulkan. Override one filter under Filters → Compute backend. '
        'Auto and GPU both try Vulkan first and fall back to CPU when the worker cannot run the job '
        '(missing device, unsupported depth/size, memory limit, etc.). '
        'Background Removal keeps its own backend.',
        '适用于支持 Vulkan 的滤镜默认值。可在 滤镜 → 计算后端 单独覆盖。'
        '自动与 GPU 都先尝试 Vulkan；worker 跑不了时（无设备、深度/尺寸不支持、显存上限等）回退 CPU。'
        '背景移除使用自己的后端。',
    ))
    backend_note.setWordWrap(True)
    settings_layout.addWidget(backend_note)

    dialog.backend_status = QtWidgets.QLabel()
    dialog.backend_status.setWordWrap(True)
    dialog.backend_status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    settings_layout.addWidget(dialog.backend_status)

    dialog.settings_status = QtWidgets.QLabel(tr(
        'Settings save automatically when this window closes. Window size applies when TFM is reopened; '
        'CPU threads and GPU memory budget apply on the next filter run.',
        '关闭窗口时自动保存设置。窗口大小在下次打开 TFM 时生效；'
        'CPU 线程数与 GPU 显存上限在下次滤镜运行时生效。',
    ))
    dialog.settings_status.setWordWrap(True)
    settings_layout.addWidget(dialog.settings_status)
    settings_layout.addStretch()

    version_label = QtWidgets.QLabel('v' + __version__)
    version_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    settings_layout.addWidget(version_label)
    full_name_label = QtWidgets.QLabel('Tool & Filter & Menu')
    full_name_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    settings_layout.addWidget(full_name_label)

    on_tab_changed(settings_page)
    return settings_page


def refresh_backend_status(dialog):
    text = tr('Last filter backend: Not used this session', '上次滤镜后端：本会话尚未使用')
    path = dialog._filter_settings.config_path()
    try:
        if path:
            with open(os.path.join(os.path.dirname(path), 'backend-status.json'), encoding='utf-8') as handle:
                status = json.load(handle)
            if (isinstance(status, dict) and type(status.get('pid')) is int
                    and status['pid'] == os.getpid()
                    and status.get('requested') in ('auto', 'cpu', 'gpu')
                    and status.get('actual') in ('cpu', 'gpu', 'vulkan')
                    and all(isinstance(status.get(key), str) for key in ('device', 'reason', 'filter'))
                    and status['filter'].strip()):
                text = tr('Last filter: {}', '上次滤镜：{}').format(status['filter'])
                text += '\n' + tr('Requested: {} | Actual: {}', '请求：{} | 实际：{}').format(
                    status['requested'].upper(), status['actual'].upper())
                if status['device'].strip():
                    text += '\n' + tr('Device: {}', '设备：{}').format(status['device'])
                reason = status['reason'].strip()
                if reason:
                    text += '\n' + tr('Reason: {}', '原因：{}').format(reason)
                    tip = dialog._backend_action_tip(reason)
                    if tip:
                        text += '\n\n' + tip
    except (OSError, ValueError, TypeError):
        pass
    dialog.backend_status.setText(text)
