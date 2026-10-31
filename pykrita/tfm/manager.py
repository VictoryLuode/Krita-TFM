"""TFM management entry point."""

import json
import os

from .menus.qtcompat import QtCore, QtWidgets, exec_
from krita import Krita
from .menus.version import __version__


def color_range_enabled():
    return Krita.instance().readSetting('TFM', 'color_range_enabled', 'true').lower() == 'true'


def set_color_range_enabled(enabled):
    Krita.instance().writeSetting('TFM', 'color_range_enabled', 'true' if enabled else 'false')
    for action in Krita.instance().actions():
        if action.objectName() == 'tfm_color_range':
            action.setVisible(enabled)
            action.setEnabled(enabled)


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
        from .menus.dialog import ListMenuDialog
        from .filters.dialog import FxManagerDialog
        self.menu_page = ListMenuDialog(tabs)
        self.filter_page = FxManagerDialog(tabs)
        tabs.addTab(self.menu_page, "Menus")
        tabs.addTab(self.filter_page, "Filters")

        tools = QtWidgets.QWidget()
        tool_layout = QtWidgets.QHBoxLayout(tools)
        tool_layout.setContentsMargins(16, 12, 16, 12)
        tool_layout.setSpacing(8)
        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel("Tools"))
        self.tools_list = QtWidgets.QListWidget()
        item = QtWidgets.QListWidgetItem("Advance Selection")
        item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
        item.setCheckState(QtCore.Qt.Checked if color_range_enabled() else QtCore.Qt.Unchecked)
        self.tools_list.addItem(item)
        item.setData(QtCore.Qt.UserRole, 'selection')
        self.tools_list.itemChanged.connect(lambda entry: set_color_range_enabled(entry.checkState() == QtCore.Qt.Checked) if entry.data(QtCore.Qt.UserRole) == 'selection' else None)
        left.addWidget(self.tools_list)
        right = QtWidgets.QVBoxLayout()
        self.tool_pages = QtWidgets.QStackedWidget()
        selection_page = QtWidgets.QWidget()
        selection_right = QtWidgets.QVBoxLayout(selection_page)
        selection_right.addWidget(QtWidgets.QLabel("Tool Details"))
        detail = QtWidgets.QTextBrowser()
        detail.setPlainText("Advance Selection\n\nSelect image regions by luminance, color channel, or selected color.\n\nAccess: Select menu")
        selection_right.addWidget(detail, 1)
        selection_right.addWidget(QtWidgets.QLabel("Default Parameters"))
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
        form.addRow('Mode', self.tool_mode)
        form.addRow('Threshold / Tolerance', self.tool_threshold)
        form.addRow('Invert', self.tool_invert)
        selection_right.addLayout(form)
        save = QtWidgets.QPushButton('Save Tools')
        save.clicked.connect(self.save_tool_defaults)
        selection_right.addWidget(save)
        self.tool_pages.addWidget(selection_page)
        right.addWidget(self.tool_pages)
        self.tools_list.currentRowChanged.connect(self.tool_pages.setCurrentIndex)
        tool_layout.addLayout(left, 1)
        tool_layout.addLayout(right, 2)
        self.tools_list.setCurrentRow(0)
        tabs.addTab(tools, "Tools")
        self._saved_tool_defaults = self._tool_defaults()
        from .filters import settings as filter_settings
        self._filter_settings = filter_settings
        settings_page = QtWidgets.QWidget()
        settings_layout = QtWidgets.QVBoxLayout(settings_page)
        settings_layout.setContentsMargins(16, 12, 16, 12)
        settings_form = QtWidgets.QFormLayout()
        self.default_width = QtWidgets.QSpinBox()
        self.default_width.setRange(980, 8192)
        self.default_width.setValue(self._window_width)
        self.default_height = QtWidgets.QSpinBox()
        self.default_height.setRange(620, 8192)
        self.default_height.setValue(self._window_height)
        self.cpu_threads = QtWidgets.QComboBox()
        self.cpu_threads.addItem('Auto (safe default: 1)', 0)
        for count in (1, 2, 4, 6, 8, 12, 16, 24, 32):
            self.cpu_threads.addItem(str(count), count)
        filter_options = filter_settings.load()
        cpu = filter_options.get('cpu_threads', 0)
        self.cpu_threads.setCurrentIndex(max(0, self.cpu_threads.findData(cpu)))
        self.filter_backend = QtWidgets.QComboBox()
        for label, value in (('Auto (Vulkan when available)', 'auto'),
                             ('CPU', 'cpu'), ('GPU (Vulkan)', 'gpu')):
            self.filter_backend.addItem(label, value)
        self.filter_backend.setCurrentIndex(max(0, self.filter_backend.findData(filter_options.get('backend', 'auto'))))
        settings_form.addRow('Default window width', self.default_width)
        settings_form.addRow('Default window height', self.default_height)
        self.cpu_threads.setToolTip('Controls plugin filters using the shared CPU worker pool. Other processing paths may use their own threads.')
        settings_form.addRow('Plugin filters CPU threads', self.cpu_threads)
        settings_form.addRow('Filter backend', self.filter_backend)
        settings_layout.addLayout(settings_form)
        backend_note = QtWidgets.QLabel('Vulkan supports Circular and Zoom Motion Blur. Other filters use CPU; Background Removal has separate ggml settings. GPU requests fall back to CPU when unavailable.')
        backend_note.setWordWrap(True)
        settings_layout.addWidget(backend_note)
        self.backend_status = QtWidgets.QLabel()
        self.backend_status.setWordWrap(True)
        self.backend_status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        settings_layout.addWidget(self.backend_status)
        self._refresh_backend_status()
        tabs.currentChanged.connect(lambda index: self._refresh_backend_status() if tabs.widget(index) is settings_page else None)
        self.settings_status = QtWidgets.QLabel('Settings save automatically when this window closes. Window size applies when TFM is reopened; CPU threads after Krita restarts.')
        self.settings_status.setWordWrap(True)
        settings_layout.addWidget(self.settings_status)
        settings_layout.addStretch()
        version_label = QtWidgets.QLabel('v' + __version__)
        version_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        settings_layout.addWidget(version_label)
        full_name_label = QtWidgets.QLabel('Tool & Filter & Menu')
        full_name_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        settings_layout.addWidget(full_name_label)
        tabs.addTab(settings_page, 'Settings')
        self._saved_general = self._general_settings()

    def _refresh_backend_status(self):
        text = 'Last filter backend: Not used this session'
        path = self._filter_settings.config_path()
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
                    text = 'Last filter: {}\nRequested: {} | Actual: {}'.format(
                        status['filter'], status['requested'].upper(), status['actual'].upper())
                    if status['device'].strip():
                        text += '\nDevice: ' + status['device']
                    if status['reason'].strip():
                        text += '\nReason: ' + status['reason']
        except (OSError, ValueError, TypeError):
            pass
        self.backend_status.setText(text)

    def _general_settings(self):
        return (self.default_width.value(), self.default_height.value(), self.cpu_threads.currentData(), self.filter_backend.currentData())

    def save_general_settings(self):
        width, height, threads, backend = self._general_settings()
        if not self._filter_settings.save({'cpu_threads': threads, 'backend': backend, 'gpu_fallback': 'cpu'}):
            self.settings_status.setText('Could not save filter settings; window size was not changed.')
            return False
        app = Krita.instance()
        try:
            for key, value in (('window_width', width), ('window_height', height)):
                if app.writeSetting('TFM', key, str(value)) is False:
                    raise RuntimeError('Could not save window settings.')
        except Exception as error:
            self.settings_status.setText('Could not save window settings: ' + str(error))
            return False
        self._saved_general = self._general_settings()
        self.settings_status.setText('Settings saved. Reopen TFM for window size; restart Krita for CPU threads.')
        return True

    def save_tool_defaults(self):
        app = Krita.instance()
        app.writeSetting('TFM', 'color_range_default_mode', self.tool_mode.currentData())
        app.writeSetting('TFM', 'color_range_default_threshold', str(self.tool_threshold.value()))
        app.writeSetting('TFM', 'color_range_default_invert', 'true' if self.tool_invert.isChecked() else 'false')
        self._saved_tool_defaults = self._tool_defaults()

    def _tool_defaults(self):
        return (self.tool_mode.currentData(), self.tool_threshold.value(), self.tool_invert.isChecked())

    def _confirm_close(self):
        pending = []
        if self.menu_page.has_unsaved_changes():
            pending.append("menus")
        if self.filter_page.has_unsaved_changes():
            pending.append("filters")
        if self._tool_defaults() != self._saved_tool_defaults:
            pending.append("tools")
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
