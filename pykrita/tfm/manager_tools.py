"""Tools tab construction for the TFM manager dialog."""

from __future__ import annotations

from .menus.qtcompat import QtWidgets
from .i18n import tr


def build_tools_tab(dialog):
    """Create the Tools tab and attach list/stack controls onto *dialog*."""
    # Late import avoids a circular load with manager.py.
    from . import manager as manager_api

    tools = QtWidgets.QWidget()
    tool_layout = QtWidgets.QHBoxLayout(tools)
    tool_layout.setContentsMargins(16, 12, 16, 12)
    tool_layout.setSpacing(8)
    dialog.tools_list = QtWidgets.QListWidget()
    dialog.tool_pages = QtWidgets.QStackedWidget()
    dialog._tool_enable = {}
    dialog._add_tool(
        'selection',
        tr('Advanced Selection', '高级选区'),
        manager_api.color_range_enabled(),
        manager_api.set_color_range_enabled,
        dialog._advance_selection_page(),
    )
    dialog._add_tool(
        'assets',
        tr('Asset Library', '资产库'),
        manager_api.assets_enabled(),
        manager_api.set_assets_enabled,
        dialog._asset_library_page(),
    )
    dialog._add_tool(
        'search',
        tr('Quick Image Search', '快速搜图'),
        manager_api.search_enabled(),
        manager_api.set_search_enabled,
        dialog._image_search_page(),
    )
    dialog._add_tool(
        'color_space',
        tr('Layer Color Space', '图层色彩空间'),
        manager_api.convert_color_space_enabled(),
        manager_api.set_convert_color_space_enabled,
        dialog._color_space_page(),
    )
    dialog.tools_list.currentRowChanged.connect(dialog._show_tool_page)
    dialog.tools_list.itemChanged.connect(dialog._tool_enabled_changed)
    dialog.tools_list.setCurrentRow(0)
    tool_layout.addWidget(dialog.tools_list, 1)
    tool_layout.addWidget(dialog.tool_pages, 2)

    from .ui_chrome import apply_muted_label
    tools_note = QtWidgets.QLabel(tr(
        'Tool checkboxes apply immediately. Filter enable/disable needs Save Filters; the native plugin re-syncs afterward.',
        '工具开关立即生效。滤镜启用/禁用需「保存滤镜」；原生插件随后会重新同步。',
    ))
    apply_muted_label(tools_note)
    tools_wrap = QtWidgets.QWidget()
    tools_wrap_layout = QtWidgets.QVBoxLayout(tools_wrap)
    tools_wrap_layout.setContentsMargins(0, 0, 0, 0)
    tools_wrap_layout.setSpacing(4)
    tools_wrap_layout.addWidget(tools_note)
    tools_wrap_layout.addWidget(tools, 1)
    return tools_wrap
