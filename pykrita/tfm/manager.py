"""TFM management entry point."""

import os

from .menus.qtcompat import QtCore, QtWidgets, exec_
from krita import Krita
from .i18n import tr


def color_range_enabled():
    return Krita.instance().readSetting('TFM', 'color_range_enabled', 'true').lower() == 'true'


def set_color_range_enabled(enabled):
    Krita.instance().writeSetting('TFM', 'color_range_enabled', 'true' if enabled else 'false')
    for action in Krita.instance().actions():
        if action.objectName() == 'tfm_color_range':
            action.setVisible(enabled)
            action.setEnabled(enabled)


def _setting_enabled(key):
    try:
        return Krita.instance().readSetting('TFM', key, 'true').lower() == 'true'
    except Exception:
        return True


def _setting_enabled_migrated(new_key, old_key):
    try:
        app = Krita.instance()
        value = app.readSetting('TFM', new_key, '')
        if value == '':
            value = app.readSetting('TFM', old_key, 'true')
        return str(value).lower() == 'true'
    except Exception:
        return True


def assets_enabled():
    return _setting_enabled_migrated('assets_enabled', 'library_enabled')


def search_enabled():
    return _setting_enabled('image_search_enabled')


def set_assets_enabled(enabled):
    app = Krita.instance()
    flag = 'true' if enabled else 'false'
    app.writeSetting('TFM', 'assets_enabled', flag)
    app.writeSetting('TFM', 'library_enabled', flag)
    apply_docker_tool('tfm_assets', 'tfm_assets', enabled, show=enabled)
    for action in app.actions():
        if action.objectName() == 'tfm_save_asset':
            action.setVisible(enabled)
            action.setEnabled(enabled)


def assets_directory():
    custom = ''
    try:
        app = Krita.instance()
        custom = app.readSetting('TFM', 'assets_dir', '') or ''
        if not str(custom).strip():
            custom = app.readSetting('TFM', 'library_dir', '') or ''
    except Exception:
        custom = ''
    custom = str(custom).strip()
    if custom:
        return os.path.abspath(os.path.expanduser(custom))
    from .assets.store import default_assets_dir
    return default_assets_dir()


def set_assets_directory(path):
    from .assets import store
    text = (path or '').strip()
    app = Krita.instance()
    if not text:
        root = store.default_assets_dir()
        saved = ''
    else:
        root = os.path.abspath(os.path.expanduser(text))
        if os.path.isfile(root):
            raise store.AssetError('Choose a folder, not a file.')
        saved = root
    try:
        os.makedirs(root, exist_ok=True)
    except OSError as error:
        raise store.AssetError('Could not use that folder.') from error
    if not os.path.isdir(root):
        raise store.AssetError('Could not use that folder.')
    if app.writeSetting('TFM', 'assets_dir', saved) is False:
        raise store.AssetError('Could not save the asset library folder.')
    try:
        app.writeSetting('TFM', 'library_dir', saved)
    except Exception:
        pass
    root = store.ensure_assets(root)
    for dock in _assets_docks():
        setter = getattr(dock, 'set_assets_root', None)
        if setter is not None:
            setter(root)
    return root


def _assets_docks():
    app = Krita.instance()
    try:
        windows = app.windows()
    except Exception:
        return
    for window in windows:
        try:
            host = window.qwindow()
        except Exception:
            continue
        dock = host.findChild(QtWidgets.QDockWidget, 'tfm_assets')
        if dock is not None:
            yield dock


def set_search_enabled(enabled):
    Krita.instance().writeSetting('TFM', 'image_search_enabled', 'true' if enabled else 'false')
    apply_docker_tool('tfm_image_search', 'tfm_quick_image_search', enabled, show=enabled)


def convert_color_space_enabled():
    return _setting_enabled('convert_color_space_enabled')


def set_convert_color_space_enabled(enabled):
    Krita.instance().writeSetting('TFM', 'convert_color_space_enabled', 'true' if enabled else 'false')
    try:
        actions = Krita.instance().actions()
    except Exception:
        actions = []
    for action in actions:
        try:
            if action.objectName() == 'tfm_convert_color_space':
                action.setVisible(enabled)
                action.setEnabled(enabled)
        except Exception:
            continue


def apply_docker_tool(action_name, dock_name, enabled, show=False):
    app = Krita.instance()
    try:
        actions = app.actions()
    except Exception:
        actions = []
    for action in actions:
        try:
            if action.objectName() == action_name:
                action.setVisible(enabled)
                action.setEnabled(enabled)
        except Exception:
            continue
    try:
        windows = app.windows()
    except Exception:
        windows = []
    for window in windows:
        try:
            host = window.qwindow()
        except Exception:
            continue
        dock = host.findChild(QtWidgets.QDockWidget, dock_name)
        if dock is None:
            continue
        toggle = dock.toggleViewAction()
        if toggle is not None:
            toggle.setVisible(enabled)
            toggle.setEnabled(enabled)
        if enabled and show:
            dock.setVisible(True)
            dock.raise_()
        elif not enabled:
            dock.hide()


class ManagerDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TFM")
        app = Krita.instance()
        def dimension(key, default, minimum):
            try:
                return max(minimum, min(8192, int(app.readSetting('TFM', key, str(default)))))
            except (ValueError, TypeError):
                return default
        self._window_width = dimension('window_width', 1400, 980)
        self._window_height = dimension('window_height', 950, 620)
        self.resize(self._window_width, self._window_height)
        self._close_confirmed = False
        layout = QtWidgets.QVBoxLayout(self)
        tabs = QtWidgets.QTabWidget(self)
        layout.addWidget(tabs)
        self._tabs = tabs
        self.menu_page = None
        self.filter_page = None
        # Keep permanent tab hosts. Swapping via removeTab/insertTab can leave a blank
        # Filters page (page constructed but not shown) under Krita's Qt binding.
        self._menu_placeholder = QtWidgets.QWidget()
        self._filter_placeholder = QtWidgets.QWidget()
        self._menu_placeholder.setObjectName("tfm_tab_menus")
        self._filter_placeholder.setObjectName("tfm_tab_filters")
        self._menu_host = QtWidgets.QVBoxLayout(self._menu_placeholder)
        self._menu_host.setContentsMargins(0, 0, 0, 0)
        self._filter_host = QtWidgets.QVBoxLayout(self._filter_placeholder)
        self._filter_host.setContentsMargins(0, 0, 0, 0)
        tabs.addTab(self._menu_placeholder, tr("Menus", "菜单"))
        tabs.addTab(self._filter_placeholder, tr("Filters", "滤镜"))
        tabs.currentChanged.connect(self._ensure_tab_page)

        from . import manager_tools
        tools_wrap = manager_tools.build_tools_tab(self)
        tabs.addTab(tools_wrap, tr("Tools", "工具"))
        self._saved_tool_defaults = self._tool_defaults()
        QTimer = QtCore.QTimer
        QTimer.singleShot(0, lambda: self._ensure_tab_page(0))
        QTimer.singleShot(0, self._maybe_show_first_run_guide)
        from .filters import settings as filter_settings
        from . import manager_settings
        self._filter_settings = filter_settings
        settings_page = manager_settings.build_settings_page(
            self,
            filter_settings,
            self._window_width,
            self._window_height,
            on_tab_changed=lambda page: tabs.currentChanged.connect(
                lambda index: self._refresh_backend_status() if tabs.widget(index) is page else None),
        )
        self._refresh_backend_status()
        tabs.addTab(settings_page, tr('Settings', '设置'))
        self._saved_general = self._general_settings()

    def _ensure_tab_page(self, index):
        # Match by placeholder widget, not translated tab title (locale/accelerator mismatch
        # was leaving Filters as an empty host forever).
        if index < 0 or index >= self._tabs.count():
            return
        page = self._tabs.widget(index)
        if page is self._menu_placeholder and self.menu_page is None:
            try:
                from .menus.dialog import ListMenuDialog
                self.menu_page = ListMenuDialog(self._menu_placeholder)
                self._mount_tab_page(self._menu_host, self.menu_page)
            except Exception as error:
                self.menu_page = self._tab_error_page(self._menu_placeholder, error)
                self._mount_tab_page(self._menu_host, self.menu_page)
        elif page is self._filter_placeholder and self.filter_page is None:
            try:
                from .filters.dialog import FilterSettingsDialog
                self.filter_page = FilterSettingsDialog(self._filter_placeholder)
                self.filter_page.setMinimumSize(0, 0)
                self._mount_tab_page(self._filter_host, self.filter_page)
            except Exception as error:
                self.filter_page = self._tab_error_page(self._filter_placeholder, error)
                self._mount_tab_page(self._filter_host, self.filter_page)

    def _mount_tab_page(self, host, page):
        expanding = getattr(getattr(QtWidgets.QSizePolicy, "Policy", QtWidgets.QSizePolicy), "Expanding")
        page.setSizePolicy(expanding, expanding)
        host.addWidget(page, 1)

    def _tab_error_page(self, parent, error):
        import traceback
        page = QtWidgets.QWidget(parent)
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(16, 12, 16, 12)
        detail = "".join(traceback.format_exception_only(type(error), error)).strip()
        label = QtWidgets.QLabel(
            tr("Could not open this tab:\n{}", "无法打开此页：\n{}").format(detail or str(error))
        )
        label.setWordWrap(True)
        label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
            if hasattr(QtCore.Qt, "TextInteractionFlag")
            else QtCore.Qt.TextSelectableByMouse
        )
        layout.addWidget(label)
        layout.addStretch(1)
        return page

    def _maybe_show_first_run_guide(self):
        app = Krita.instance()
        try:
            if app.readSetting('TFM', 'seen_configure_guide', 'false').lower() == 'true':
                return
            app.writeSetting('TFM', 'seen_configure_guide', 'true')
        except Exception:
            return
        QtWidgets.QMessageBox.information(
            self,
            tr('Welcome to TFM', '欢迎使用 TFM'),
            tr(
                'TFM adds cursor menus, native filters, Advanced Selection, an asset library, and optional tools.\n\n'
                '• Menus — a Quick Tool sample list is ready (shortcut Q on first install).\n'
                '• Tools — checkboxes turn panels on immediately.\n'
                '• Filters — Save Filters; the native plugin re-syncs the registry (restart only if a menu label stays stale).\n\n'
                'Open Tools → TFM anytime, or press Q for Quick Tool after a fresh install.',
                'TFM 提供光标菜单、原生滤镜、高级选区、资产库与可选工具。\n\n'
                '• 菜单 — 首次安装带有 Quick Tool 样例（快捷键 Q）。\n'
                '• 工具 — 勾选后立即生效。\n'
                '• 滤镜 — 保存滤镜后原生插件会同步注册表（仅当菜单标签残留时才需重启）。\n\n'
                '随时从「工具 → TFM」打开；全新安装后可按 Q 弹出 Quick Tool。',
            ),
        )

    def _refresh_backend_status(self):
        from . import manager_settings
        manager_settings.refresh_backend_status(self)

    @staticmethod
    def _backend_action_tip(reason):
        from .backend_status import backend_action_tip
        return backend_action_tip(reason)

    def _general_settings(self):
        return (
            self.default_width.value(),
            self.default_height.value(),
            self.cpu_threads.currentData(),
            self.gpu_memory_mb.value(),
            self.filter_backend.currentData(),
        )

    def save_general_settings(self):
        width, height, threads, gpu_memory_mb, backend = self._general_settings()
        if not self._filter_settings.save({
            'cpu_threads': threads,
            'gpu_memory_mb': gpu_memory_mb,
            'backend': backend,
            'gpu_fallback': 'cpu',
        }):
            self.settings_status.setText(tr(
                'Could not save filter settings; window size was not changed.',
                '无法保存滤镜设置；窗口大小未更改。',
            ))
            return False
        app = Krita.instance()
        try:
            for key, value in (('window_width', width), ('window_height', height)):
                if app.writeSetting('TFM', key, str(value)) is False:
                    raise RuntimeError('Could not save window settings.')
        except Exception as error:
            self.settings_status.setText(tr(
                'Could not save window settings: {}',
                '无法保存窗口设置：{}',
            ).format(error))
            return False
        self._saved_general = self._general_settings()
        self.settings_status.setText(tr(
            'Settings saved. Reopen TFM for window size; CPU threads and GPU memory budget apply on the next filter run.',
            '设置已保存。窗口大小在下次打开 TFM 时生效；CPU 线程数与 GPU 显存上限在下次滤镜运行时生效。',
        ))
        return True

    def _add_tool(self, ident, label, enabled, on_enabled, page):
        item = QtWidgets.QListWidgetItem(label)
        item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
        item.setData(QtCore.Qt.ItemDataRole.UserRole, ident)
        item.setCheckState(QtCore.Qt.CheckState.Checked if enabled else QtCore.Qt.CheckState.Unchecked)
        self.tools_list.addItem(item)
        self._tool_enable[ident] = on_enabled
        self.tool_pages.addWidget(page)

    def _tool_enabled_changed(self, item):
        handler = self._tool_enable.get(item.data(QtCore.Qt.ItemDataRole.UserRole))
        if handler is not None:
            handler(item.checkState() == QtCore.Qt.CheckState.Checked)

    def _advance_selection_page(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.addWidget(QtWidgets.QLabel(tr(
            'Select image regions by luminance, color channel, or a sampled color. Open it from the Select menu.',
            '按亮度、颜色通道或采样颜色选择图像区域。可从「选择」菜单打开。',
        )))
        form = QtWidgets.QFormLayout()
        self.tool_mode = QtWidgets.QComboBox()
        for group in (
            [('Sampled Color', 'color')],
            [('Reds', 'hue_red'), ('Yellows', 'hue_yellow'),
             ('Greens', 'hue_green'), ('Cyans', 'hue_cyan'),
             ('Blues', 'hue_blue'), ('Magentas', 'hue_magenta'), ('Skin Tones', 'skin')],
            [('Highlights', 'highlights'), ('Midtones', 'midtones'),
             ('Shadows', 'shadows'), ('Brightness', 'luminance')],
            [('Red Channel', 'red'), ('Green Channel', 'green'), ('Blue Channel', 'blue')],
        ):
            if self.tool_mode.count():
                self.tool_mode.insertSeparator(self.tool_mode.count())
            for label, key in group:
                self.tool_mode.addItem(label, key)
        self.tool_threshold = QtWidgets.QSpinBox()
        self.tool_threshold.setRange(0, 255)
        self.tool_invert = QtWidgets.QCheckBox()
        app = Krita.instance()
        self.tool_mode.setCurrentIndex(max(0, self.tool_mode.findData(app.readSetting('TFM', 'color_range_default_mode', 'luminance'))))
        try:
            self.tool_threshold.setValue(int(app.readSetting('TFM', 'color_range_default_threshold', '128')))
        except ValueError:
            self.tool_threshold.setValue(128)
        self.tool_invert.setChecked(app.readSetting('TFM', 'color_range_default_invert', 'false').lower() == 'true')
        form.addRow(tr('Mode', '模式'), self.tool_mode)
        form.addRow(tr('Threshold / Tolerance', '阈值 / 容差'), self.tool_threshold)
        form.addRow(tr('Invert', '反相'), self.tool_invert)
        layout.addLayout(form)
        save = QtWidgets.QPushButton(tr('Save Selection Defaults', '保存选区默认值'))
        save.setToolTip(tr(
            'Saves only the Advanced Selection defaults below. Tool on/off checkboxes apply immediately.',
            '仅保存下方高级选区默认值。左侧工具开关会立即生效。',
        ))
        save.clicked.connect(self.save_tool_defaults)
        layout.addWidget(save, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        self.tool_defaults_status = QtWidgets.QLabel('')
        self.tool_defaults_status.setWordWrap(True)
        layout.addWidget(self.tool_defaults_status)
        layout.addStretch(1)
        return page

    def _asset_library_page(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        note = QtWidgets.QLabel(tr(
            'Save paint layers, filter layers (with parameters), layer groups, and transparency masks, then reuse them. '
            'Drag a layer into the panel, or drag a thumbnail back onto the canvas or the Layers docker. '
            'Hold Ctrl and scroll over the assets to resize them. Open the panel from Tools → TFM → Asset Library.',
            '保存绘制图层、滤镜图层（含参数）、图层组和透明蒙版以便复用。'
            '把图层拖进面板，或把缩略图拖回画布/图层面板。'
            '在资产上按住 Ctrl 滚轮可调整大小。从「工具 → TFM → 资产库」打开。',
        ))
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QtWidgets.QHBoxLayout()
        self.assets_path = QtWidgets.QLineEdit()
        self.assets_path.setText(assets_directory())
        self.assets_path.setPlaceholderText(tr('Asset library folder', '资产库文件夹'))
        self.assets_path.editingFinished.connect(self._apply_assets_path)
        browse = QtWidgets.QPushButton(tr('Browse…', '浏览…'))
        browse.clicked.connect(self._browse_assets_path)
        reset = QtWidgets.QPushButton(tr('Reset', '重置'))
        reset.clicked.connect(self._reset_assets_path)
        row.addWidget(self.assets_path, 1)
        row.addWidget(browse)
        row.addWidget(reset)
        form = QtWidgets.QFormLayout()
        form.addRow(tr('Asset library folder', '资产库文件夹'), row)
        layout.addLayout(form)
        self.assets_path_status = QtWidgets.QLabel(tr(
            'Assets already saved stay in the previous folder.',
            '已保存的资产仍留在原先文件夹中。',
        ))
        self.assets_path_status.setWordWrap(True)
        layout.addWidget(self.assets_path_status)
        layout.addStretch(1)
        return page

    def _browse_assets_path(self):
        start = self.assets_path.text().strip() or assets_directory()
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self, tr('Asset library folder', '资产库文件夹'), start)
        if not chosen:
            return
        self.assets_path.setText(chosen)
        self._apply_assets_path()

    def _reset_assets_path(self):
        self.assets_path.clear()
        self._apply_assets_path()

    def _apply_assets_path(self):
        try:
            root = set_assets_directory(self.assets_path.text())
        except Exception as error:
            self.assets_path_status.setText(str(error))
            return
        self.assets_path.setText(root)
        self.assets_path_status.setText(tr(
            'Asset library folder updated. Assets already saved stay in the previous folder.',
            '资产库文件夹已更新。已保存的资产仍留在原先文件夹中。',
        ))

    def _image_search_page(self):
        return self._tool_note(tr(
            'Search Google Images and Pinterest, then drag a result onto the canvas. '
            'Open the panel from Tools → TFM → Quick Image Search.',
            '搜索 Google 图片或 Pinterest，再把结果拖到画布。'
            '从「工具 → TFM → 快速搜图」打开面板。',
        ))

    def _show_tool_page(self, index):
        self.tool_pages.setCurrentIndex(index)
        item = self.tools_list.item(index)
        if item is not None and item.data(QtCore.Qt.ItemDataRole.UserRole) == 'color_space':
            self._refresh_color_space_default()

    def _refresh_color_space_default(self):
        from .color_space import default_color_space, format_color_space
        try:
            text = tr('Default: {}', '默认：{}').format(
                format_color_space(*default_color_space()))
        except Exception:
            text = tr('Default color space: unavailable.', '默认色彩空间：不可用。')
        self.color_space_default.setText(text)

    def _color_space_page(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        note = QtWidgets.QLabel(tr(
            'Convert every layer in the current document to the color space Krita uses for new images. '
            'Nested layers are included. Masks stay on their layers, and clone layers follow the layer they copy. '
            'The image color space is left unchanged. '
            'Open it from Tools → TFM → Convert All Layers to Default Color Space.',
            '将当前文档中每个图层转换为 Krita 新建图像使用的色彩空间。'
            '包含嵌套图层；蒙版留在所属图层上；克隆图层跟随其源图层。'
            '文档本身的色彩空间不变。'
            '从「工具 → TFM → 将所有图层转换为默认色彩空间」打开。',
        ))
        note.setWordWrap(True)
        layout.addWidget(note)
        self.color_space_default = QtWidgets.QLabel()
        self.color_space_default.setWordWrap(True)
        self.color_space_default.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.color_space_default)
        self._refresh_color_space_default()
        button = QtWidgets.QPushButton(tr('Convert All Layers', '转换所有图层'))
        button.clicked.connect(self._convert_document_color_space)
        layout.addWidget(button, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return page

    def _convert_document_color_space(self):
        from .color_space import run_convert
        self._refresh_color_space_default()
        run_convert(self)

    def _tool_note(self, text):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        label = QtWidgets.QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch(1)
        return page

    def save_tool_defaults(self):
        app = Krita.instance()
        app.writeSetting('TFM', 'color_range_default_mode', self.tool_mode.currentData())
        app.writeSetting('TFM', 'color_range_default_threshold', str(self.tool_threshold.value()))
        app.writeSetting('TFM', 'color_range_default_invert', 'true' if self.tool_invert.isChecked() else 'false')
        self._saved_tool_defaults = self._tool_defaults()
        if hasattr(self, 'tool_defaults_status'):
            self.tool_defaults_status.setText(tr(
                'Selection defaults saved.',
                '选区默认值已保存。',
            ))

    def _tool_defaults(self):
        return (self.tool_mode.currentData(), self.tool_threshold.value(), self.tool_invert.isChecked())

    def _confirm_close(self):
        pending = []
        if self.menu_page is not None and self.menu_page.has_unsaved_changes():
            pending.append(tr("menus", "菜单"))
        if self.filter_page is not None and self.filter_page.has_unsaved_changes():
            pending.append(tr("filters", "滤镜"))
        if self._tool_defaults() != self._saved_tool_defaults:
            pending.append(tr("selection defaults", "选区默认值"))
        if self._general_settings() != self._saved_general:
            if not self.save_general_settings():
                tabs = self.findChild(QtWidgets.QTabWidget)
                tabs.setCurrentIndex(tabs.count() - 1)
                QtWidgets.QMessageBox.warning(self, 'Settings not saved', self.settings_status.text())
                return False
        if not pending:
            return True
        buttons = QtWidgets.QMessageBox.StandardButton
        return QtWidgets.QMessageBox.question(
            self, "Unsaved changes",
            "Discard unsaved {} changes? Previously saved changes remain.".format(" and ".join(pending)),
            buttons.Yes | buttons.No, buttons.No) == buttons.Yes

    def reject(self):
        if self._close_confirmed or self._confirm_close():
            self._close_confirmed = True
            super().reject()

    def closeEvent(self, event):
        if self._close_confirmed or self._confirm_close():
            self._close_confirmed = True
            event.accept()
        else:
            event.ignore()


def show_manager(parent=None):
    return exec_(ManagerDialog(parent))
