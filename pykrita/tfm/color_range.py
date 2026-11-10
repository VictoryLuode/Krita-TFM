"""Interactive sampled-color selection for Krita."""
from krita import Krita, Selection
from .menus.qtcompat import (
    Qt, QByteArray, QObject, QRunnable, QThreadPool, QTimer, pyqtSignal,
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSlider, QSpinBox, QVBoxLayout,
    QImage, QPixmap, QColor, QtWidgets,
)
from .i18n import tr
from .color_range_native import channel_mask as native_channel_mask
from .color_range_native import combine as native_combine
from .color_range_native import mask as native_mask
from .color_range_native import perceptual as native_perceptual
from .color_range_overlay import ColorRangeOverlay

TOOL_TITLE = lambda: tr('Advanced Selection', '高级选区')

_MODE_GROUPS = (
    ((('Sampled Color', '取样颜色'), 'color'),),
    (
        (('Reds', '红色'), 'hue_red'),
        (('Yellows', '黄色'), 'hue_yellow'),
        (('Greens', '绿色'), 'hue_green'),
        (('Cyans', '青色'), 'hue_cyan'),
        (('Blues', '蓝色'), 'hue_blue'),
        (('Magentas', '品红'), 'hue_magenta'),
        (('Skin Tones', '肤色'), 'skin'),
    ),
    (
        (('Highlights', '高光'), 'highlights'),
        (('Midtones', '中间调'), 'midtones'),
        (('Shadows', '阴影'), 'shadows'),
        (('Brightness', '亮度'), 'luminance'),
    ),
    (
        (('Red Channel', '红色通道'), 'red'),
        (('Green Channel', '绿色通道'), 'green'),
        (('Blue Channel', '蓝色通道'), 'blue'),
    ),
)


def _enum(group, name):
    direct = getattr(group, name, None)
    if direct is not None:
        return direct
    for scope in ('Format', 'Shape', 'StandardButton', 'Orientation',
                  'AspectRatioMode', 'TransformationMode', 'MouseButton',
                  'KeyboardModifier', 'CursorShape'):
        scoped = getattr(group, scope, None)
        if scoped is not None and hasattr(scoped, name):
            return getattr(scoped, name)
    raise AttributeError(name)


def _image_format(name):
    return _enum(QImage.Format, name)


def _luminance_bytes(source):
    """Pack grayscale8 pixels without row padding; safe on a worker thread."""
    gray = source.convertToFormat(QImage.Format.Format_Grayscale8)
    ptr = gray.constBits()
    ptr.setsize(gray.sizeInBytes())
    raw = bytes(ptr)
    width, height = source.width(), source.height()
    stride = gray.bytesPerLine()
    if stride == width:
        return bytearray(raw[: width * height])
    luminance = bytearray(width * height)
    for y in range(height):
        start = y * stride
        luminance[y * width:(y + 1) * width] = raw[start:start + width]
    return luminance


class _CaptureSignals(QObject):
    finished = pyqtSignal(object)


class _LuminanceJob(QRunnable):
    def __init__(self, generation, source, signals):
        super().__init__()
        self.generation = generation
        self.source = source
        self.signals = signals

    def run(self):
        try:
            result = (self.generation, self.source, _luminance_bytes(self.source), None)
        except Exception as error:  # noqa: BLE001 — surface any decode failure to the dialog
            result = (self.generation, None, None, error)
        self.signals.finished.emit(result)


_open_dialogs = []


class ColorRangeDialog(QDialog):
    def __init__(self, document, parent=None):
        super().__init__(parent)
        self.document = document
        self.setWindowTitle(TOOL_TITLE())
        self._source_generation = 0
        self._capture_signals = _CaptureSignals(self)
        self._capture_signals.finished.connect(self._on_capture_ready)
        self._capture_source()
        self._bind_document_changes()
        self.target_color = QColor(255, 255, 255)
        self.mask_mode = QComboBox()
        for group in _MODE_GROUPS:
            if self.mask_mode.count():
                self.mask_mode.insertSeparator(self.mask_mode.count())
            for (english, chinese), key in group:
                self.mask_mode.addItem(tr(english, chinese), key)
        self._mask_cache_key = None
        self._mask_cache = None
        self.color_button = QPushButton(tr('Choose Color…', '选择颜色…'))
        self.color_button.clicked.connect(self.choose_color)
        self.color_button.setVisible(False)
        self.preview = QLabel()
        self.preview.setFixedSize(300, 220)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(220)
        # Keep the historical threshold behavior as the default. The new
        # overrides remain off until explicitly enabled.
        self.threshold_enabled = QCheckBox(tr('Threshold', '阈值'))
        self.threshold_enabled.setChecked(True)
        self.threshold = QSpinBox(); self.threshold.setRange(0, 255); self.threshold.setValue(128)
        self.slider = QSlider(_enum(Qt, 'Horizontal')); self.slider.setRange(0, 255); self.slider.setValue(128)
        self.slider.valueChanged.connect(self.threshold.setValue)
        self.threshold.valueChanged.connect(self.slider.setValue)
        self.threshold_enabled.toggled.connect(self._set_threshold_controls)
        self.tolerance_enabled = QCheckBox(tr('Color Tolerance', '颜色容差'))
        self.tolerance_enabled.setToolTip(tr(
            'Override the color-match distance independently of Threshold.',
            '独立于阈值，单独覆盖颜色匹配距离。',
        ))
        self.tolerance_enabled.setChecked(False)
        self.tolerance = QSpinBox(); self.tolerance.setRange(0, 255); self.tolerance.setValue(32)
        self.tolerance_slider = QSlider(_enum(Qt, 'Horizontal')); self.tolerance_slider.setRange(0, 255); self.tolerance_slider.setValue(32)
        self.tolerance_slider.valueChanged.connect(self.tolerance.setValue)
        self.tolerance.valueChanged.connect(self.tolerance_slider.setValue)
        self.tolerance_slider.setEnabled(False)
        self.tolerance.setEnabled(False)
        self.tolerance_enabled.toggled.connect(self.tolerance_slider.setEnabled)
        self.tolerance_enabled.toggled.connect(self.tolerance.setEnabled)
        self.softness_enabled = QCheckBox(tr('Softness', '柔和度'))
        self.softness_enabled.setToolTip(tr(
            'Override edge feathering independently of Threshold and Color Tolerance.',
            '独立于阈值和颜色容差，单独覆盖边缘羽化。',
        ))
        self.softness_enabled.setChecked(False)
        self.softness = QSpinBox(); self.softness.setRange(0, 255); self.softness.setValue(12)
        self.softness_slider = QSlider(_enum(Qt, 'Horizontal')); self.softness_slider.setRange(0, 255); self.softness_slider.setValue(12)
        self.softness_slider.valueChanged.connect(self.softness.setValue)
        self.softness.valueChanged.connect(self.softness_slider.setValue)
        self.softness_slider.setEnabled(False)
        self.softness.setEnabled(False)
        self.softness_enabled.toggled.connect(self.softness_slider.setEnabled)
        self.softness_enabled.toggled.connect(self.softness.setEnabled)
        self.invert = QCheckBox(tr('Invert', '反相'))
        defaults = Krita.instance()
        saved_mode = defaults.readSetting('TFM', 'color_range_default_mode', 'luminance')
        self.mask_mode.setCurrentIndex(max(0, self.mask_mode.findData(saved_mode)))
        try:
            saved_threshold = max(0, min(255, int(defaults.readSetting('TFM', 'color_range_default_threshold', '128'))))
        except (TypeError, ValueError):
            saved_threshold = 128
        self.threshold.setValue(saved_threshold)
        self.invert.setChecked(defaults.readSetting('TFM', 'color_range_default_invert', 'false').lower() == 'true')
        from .ui_chrome import apply_warning_label
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(self.mask_mode)
        layout.addWidget(self.color_button)
        row = QHBoxLayout(); row.addWidget(self.threshold_enabled); row.addWidget(self.slider, 1); row.addWidget(self.threshold); layout.addLayout(row)
        row = QHBoxLayout(); row.addWidget(self.tolerance_enabled); row.addWidget(self.tolerance_slider, 1); row.addWidget(self.tolerance); layout.addLayout(row)
        row = QHBoxLayout(); row.addWidget(self.softness_enabled); row.addWidget(self.softness_slider, 1); row.addWidget(self.softness); layout.addLayout(row)
        preview_frame = QFrame()
        preview_frame.setFrameShape(_enum(QFrame, 'StyledPanel') or getattr(QFrame.Shape, 'StyledPanel', QFrame.StyledPanel))
        preview_frame.setFrameShadow(_enum(QFrame, 'Sunken') or getattr(QFrame.Shadow, 'Sunken', QFrame.Sunken))
        preview_inner = QHBoxLayout(preview_frame)
        preview_inner.setContentsMargins(8, 8, 8, 8)
        preview_inner.addStretch()
        preview_inner.addWidget(self.preview)
        preview_inner.addStretch()
        layout.addWidget(preview_frame, 1)
        layout.addWidget(self.invert)
        self.preview.setToolTip(tr('White: selected. Black: unselected.', '白色：已选。黑色：未选。'))
        buttons = QHBoxLayout()
        self.select_button = QPushButton(tr('Add', '添加'))
        self.deselect_button = QPushButton(tr('Subtract', '减去'))
        self.clean_button = QPushButton(tr('Clear', '清除'))
        self.reselect_button = QPushButton(tr('Replace', '替换'))
        self.refresh_source_button = QPushButton(tr('Refresh Source', '刷新来源'))
        self.refresh_source_button.setToolTip(tr(
            'Reread the canvas after it changes, so the selection is not based on a stale image.',
            '画布变化后重新读取，避免基于过期图像做选区。',
        ))
        self.source_status = QLabel('')
        apply_warning_label(self.source_status)
        self.clean_button.clicked.connect(self.clean_selection)
        self.reselect_button.clicked.connect(lambda: self.apply_mode('replace', close=False))
        self.select_button.clicked.connect(lambda: self.apply_mode('add', close=False))
        self.deselect_button.clicked.connect(lambda: self.apply_mode('subtract', close=False))
        self.refresh_source_button.clicked.connect(self.refresh_source_from_canvas)
        buttons.addWidget(self.reselect_button)
        buttons.addWidget(self.select_button)
        buttons.addWidget(self.deselect_button)
        buttons.addWidget(self.clean_button)
        buttons.addWidget(self.refresh_source_button)
        layout.addLayout(buttons)
        layout.addWidget(self.source_status)
        box = QDialogButtonBox(_enum(QDialogButtonBox, 'Ok') | _enum(QDialogButtonBox, 'Cancel'))
        ok_button = box.button(_enum(QDialogButtonBox, 'Ok'))
        if ok_button is not None:
            ok_button.setText(tr('Replace and Close', '替换并关闭'))
        box.accepted.connect(self.apply); box.rejected.connect(self.reject); layout.addWidget(box)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self.refresh)
        self._preview_image = QImage()
        for signal in (self.threshold.valueChanged, self.threshold_enabled.toggled,
                       self.tolerance.valueChanged, self.tolerance_enabled.toggled,
                       self.softness.valueChanged, self.softness_enabled.toggled,
                       self.invert.toggled):
            signal.connect(self.schedule_refresh)
        self.mask_mode.currentIndexChanged.connect(self.change_mode)
        self.preview_mode = QComboBox()
        self.preview_mode.addItem(tr('Selection Outline', '选区轮廓'), 'selection')
        self.preview_mode.addItem(tr('Black & White', '黑白预览'), 'black_white')
        self.preview_mode.addItem(tr('Quick Mask', '快速蒙版'), 'quick_mask')
        self.overlay = None
        self.preview_mode.currentIndexChanged.connect(self.update_canvas_preview)
        self.finished.connect(self._remove_canvas_preview)
        destroyed = getattr(self.document, 'destroyed', None)
        if destroyed is not None:
            destroyed.connect(self._remove_canvas_preview)
        layout.insertWidget(1, self.preview_mode)
        self.change_mode()
        self.refresh()

    def _bind_document_changes(self):
        self._source_stale = False
        modified = getattr(self.document, 'imageModified', None) or getattr(self.document, 'modified', None)
        if modified is not None and hasattr(modified, 'connect'):
            try:
                modified.connect(self._mark_source_stale)
            except Exception:
                pass
        sig = getattr(self.document, 'sigProgress', None)
        # Prefer periodic check while open: document may not expose a clean modified signal on all builds.
        self._stale_timer = QTimer(self)
        self._stale_timer.setInterval(1000)
        self._stale_timer.timeout.connect(self._check_source_freshness)
        self._stale_timer.start()
        self.finished.connect(self._stale_timer.stop)

    def _mark_source_stale(self, *_):
        self._source_stale = True
        self.source_status.setText(tr(
            'Canvas changed. Click Refresh Source before applying.',
            '画布已变化。应用前请先点「刷新来源」。',
        ))

    def _check_source_freshness(self):
        if Krita.instance().activeDocument() != self.document:
            self.source_status.setText(tr(
                'Active document changed. Close this window or switch back.',
                '当前文档已切换。请关闭此窗口或切回原文档。',
            ))
            return
        # Heuristic: if projection size changed, source is stale.
        try:
            if self.source is not None and (
                self.source.width() != self.document.width()
                or self.source.height() != self.document.height()
            ):
                self._mark_source_stale()
        except Exception:
            pass

    def _apply_captured(self, source, luminance):
        self.source = source
        self.luminance = luminance
        self._mask_cache_key = None
        self._mask_cache = None
        self._source_stale = False
        if hasattr(self, 'source_status'):
            self.source_status.setText('')

    def _read_projection(self):
        source = self.document.projection(0, 0, self.document.width(), self.document.height()).convertToFormat(
            _image_format('Format_ARGB32'))
        if source.isNull():
            raise ValueError(tr('Unable to read the image projection.', '无法读取图像投影。'))
        return source

    def _capture_source(self, source=None, async_=False):
        if source is None:
            source = self._read_projection()
        elif source.isNull():
            raise ValueError(tr('Unable to read the image projection.', '无法读取图像投影。'))
        if not async_:
            self._source_generation += 1
            self._apply_captured(source, _luminance_bytes(source))
            return
        # Projection stays on the UI thread; luminance packing moves off it.
        self._source_generation += 1
        generation = self._source_generation
        if hasattr(self, 'source_status'):
            self.source_status.setText(tr('Refreshing source…', '正在刷新来源…'))
        QThreadPool.globalInstance().start(_LuminanceJob(generation, source.copy(), self._capture_signals))

    def _on_capture_ready(self, result):
        generation, source, luminance, error = result
        if generation != self._source_generation:
            return
        if error is not None:
            if hasattr(self, 'source_status'):
                self.source_status.setText('')
            QMessageBox.warning(self, TOOL_TITLE(), str(error))
            return
        self._apply_captured(source, luminance)
        self.schedule_refresh()

    def _refresh_source(self, async_=False):
        self._capture_source(self._read_projection(), async_=async_)
        return True

    def refresh_source_from_canvas(self):
        """Re-read document projection while the non-modal dialog stays open."""
        if Krita.instance().activeDocument() != self.document:
            QMessageBox.warning(self, TOOL_TITLE(), tr(
                'The active document has changed.',
                '当前文档已切换。',
            ))
            return
        try:
            self._refresh_source(async_=True)
        except (RuntimeError, ValueError) as error:
            QMessageBox.warning(self, TOOL_TITLE(), str(error))

    def _set_threshold_controls(self, enabled):
        self.slider.setEnabled(enabled)
        self.threshold.setEnabled(enabled)
        self.schedule_refresh()

    def change_mode(self, *args):
        color_mode = self.mask_mode.currentData() == 'color'
        self.color_button.setVisible(color_mode)
        self.threshold_enabled.setText(tr('Threshold', '阈值'))
        self.schedule_refresh()

    def choose_color(self):
        color = QtWidgets.QColorDialog.getColor(
            self.target_color, self, tr('Mask Color', '蒙版颜色'))
        if color.isValid():
            self.target_color = color
            self.color_button.setText(tr('Color: ', '颜色：') + color.name())
            self.schedule_refresh()

    def schedule_refresh(self, *args):
        self.timer.start(150)

    def _canvas_for_view(self, window, view):
        if view is None:
            raise RuntimeError(tr('Unable to identify the active canvas.', '无法识别当前画布。'))
        names = ('KisOpenGLCanvas2', 'KisQPainterCanvas')

        def collect(root):
            if root is None:
                return []
            found = []
            try:
                widgets = root.findChildren(QtWidgets.QWidget)
            except (RuntimeError, AttributeError):
                return []
            for widget in widgets:
                try:
                    if widget.isVisible() and widget.metaObject().className() in names:
                        found.append(widget)
                except RuntimeError:
                    continue
            return found

        try:
            host = window.qwindow()
        except (RuntimeError, AttributeError):
            host = None
        if host is not None:
            try:
                areas = host.findChildren(QtWidgets.QMdiArea)
            except (RuntimeError, AttributeError):
                areas = []
            for area in areas:
                sub = area.activeSubWindow()
                found = collect(sub)
                if found:
                    return found[0]
            found = collect(host)
            if found:
                return found[0]
        raise RuntimeError(tr('Unable to identify the active canvas.', '无法识别当前画布。'))

    def update_canvas_preview(self, *args):
        self._remove_canvas_preview()
        mode = self.preview_mode.currentData()
        try:
            if self.source is None or self.source.isNull():
                self._refresh_source()
            window = Krita.instance().activeWindow()
            view = window.activeView() if window else None
            if view is None or view.document() != self.document:
                raise RuntimeError(tr('The original document is not active.', '原文档未处于活动状态。'))
            canvas = self._canvas_for_view(window, view)
            self.overlay = ColorRangeOverlay(canvas, view, self.document,
                                              lambda: window.activeView() == view)
            self.overlay.set_mask(self.mask(), self.source.width(), self.source.height(), mode)
            self.overlay.show()
            self.overlay.raise_()
        except (RuntimeError, ValueError, AttributeError) as error:
            self._remove_canvas_preview()
            self.preview_mode.blockSignals(True)
            self.preview_mode.setCurrentIndex(0)
            self.preview_mode.blockSignals(False)
            QMessageBox.warning(self, TOOL_TITLE(), str(error))

    def _remove_canvas_preview(self, *args):
        overlay, self.overlay = self.overlay, None
        if overlay is not None:
            try:
                overlay.close()
                overlay.deleteLater()
            except RuntimeError:
                pass

    def showEvent(self, event):
        super().showEvent(event)
        if self.overlay is None and Krita.instance().activeWindow() is not None:
            self.update_canvas_preview()

    def closeEvent(self, event):
        self.timer.stop()
        self._source_generation += 1
        self._remove_canvas_preview()
        super().closeEvent(event)

    def mask(self):
        key = (self.mask_mode.currentData(), self.threshold.value(), self.threshold_enabled.isChecked(),
               self.tolerance.value(), self.tolerance_enabled.isChecked(),
               self.softness.value(), self.softness_enabled.isChecked(),
               self.invert.isChecked(), self.target_color.rgba())
        if key != self._mask_cache_key:
            result = self._calculate_mask()
            self._mask_cache_key, self._mask_cache = key, result
        return self._mask_cache

    def _calculate_mask(self):
        threshold = self.threshold.value() if self.threshold_enabled.isChecked() else 128
        inverted = self.invert.isChecked()
        mode = self.mask_mode.currentData()
        if mode == 'color':
            target = self.target_color
            samples = [(target.red(), target.green(), target.blue(), .5, .5, True)]
            tolerance = self.tolerance.value() if self.tolerance_enabled.isChecked() else None
            softness = self.softness.value() if self.softness_enabled.isChecked() else None
            return native_mask(
                self.source, samples,
                max(1, round(self.threshold.value() * 200 / 255)),
                False, 1.0, inverted,
                threshold_enabled=self.threshold_enabled.isChecked(),
                tolerance=tolerance, softness=softness)
        if mode.startswith('hue_') or mode in ('skin', 'highlights', 'midtones', 'shadows'):
            return native_perceptual(
                self.source, self.luminance, mode, self.threshold.value(), inverted,
                threshold_enabled=self.threshold_enabled.isChecked(),
                tolerance=(self.tolerance.value() if self.tolerance_enabled.isChecked() else None),
                softness=(self.softness.value() if self.softness_enabled.isChecked() else None))
        if mode in ('red', 'green', 'blue', 'luminance'):
            return native_channel_mask(
                self.source, self.luminance, mode, self.threshold.value(), inverted,
                threshold_enabled=self.threshold_enabled.isChecked(),
                tolerance=(self.tolerance.value() if self.tolerance_enabled.isChecked() else None),
                softness=(self.softness.value() if self.softness_enabled.isChecked() else None))
        raise ValueError(tr('Unknown color range selection mode.', '未知的高级选区模式。'))

    def _show_preview(self, mask):
        width, height = self.source.width(), self.source.height()
        image = QImage(bytes(mask), width, height, width, _image_format('Format_Indexed8')).copy()
        image.setColorTable([0xff000000 | v << 16 | v << 8 | v for v in range(256)])
        box = self.preview.size()
        if width > box.width() or height > box.height():
            image = image.scaled(
                box,
                _enum(Qt, 'KeepAspectRatio'),
                _enum(Qt, 'FastTransformation'),
            )
        self._preview_image = image
        self.preview.setPixmap(QPixmap.fromImage(image))

    def preview_image(self):
        return self._preview_image

    def refresh(self):
        try:
            mask = self.combined_mask()
            self._show_preview(mask)
            if self.overlay is not None:
                self.overlay.set_mask(mask, self.source.width(), self.source.height(), self.preview_mode.currentData())
        except (RuntimeError, ValueError, TypeError) as error:
            self.timer.stop()
            self.preview.clear()
            self._preview_image = QImage()
            self.preview.setText(str(error))


    def combined_mask(self, mode=None):
        result = self.mask()
        mode = mode or 'replace'
        if mode == 'replace':
            return result
        existing = self.document.selection()
        if existing is None:
            old = bytes([255 if mode == 'subtract' else 0]) * len(result)
        else:
            old = bytes(existing.pixelData(0, 0, self.source.width(), self.source.height()))
            if len(old) != len(result):
                raise ValueError(tr('Unable to read the current selection.', '无法读取当前选区。'))
        return native_combine(result, old, mode)

    def clean_selection(self):
        if Krita.instance().activeDocument() != self.document:
            QMessageBox.warning(self, TOOL_TITLE(), tr(
                'The active document has changed.',
                '当前文档已切换。',
            ))
            return
        try:
            if self.document.selection() is not None:
                self.document.setSelection(None)
                self.document.waitForDone()
                self.document.refreshProjection()
        except Exception as error:
            QMessageBox.warning(self, TOOL_TITLE(), str(error))
            return
        self.schedule_refresh()

    def apply(self):
        self.apply_mode('replace', close=True)

    def apply_mode(self, mode, close=False):
        if Krita.instance().activeDocument() != self.document:
            QMessageBox.warning(self, TOOL_TITLE(), tr(
                'The active document has changed.',
                '当前文档已切换。',
            ))
            return
        QApplication.setOverrideCursor(_enum(Qt, 'WaitCursor'))
        holder = None
        try:
            self._refresh_source(async_=False)
            width, height = self.source.width(), self.source.height()
            combined = self.combined_mask(mode)
            selection = Selection()
            # Binding the detached mask supplies finite image bounds. Invert
            # twice then invalidates Krita 5.3's stale outline cache without
            # changing any coverage bytes or adding document undo commands.
            selection.setPixelData(QByteArray(combined), 0, 0, width, height)
            holder = self.document.createSelectionMask('Color Range cache')
            holder.setSelection(selection)
            selection.invert()
            selection.invert()
            self.document.setSelection(selection)
            self.document.waitForDone()
            show_selection = Krita.instance().action('toggle_display_selection')
            if show_selection is not None and not show_selection.isChecked():
                show_selection.trigger()
            self.document.refreshProjection()
        except Exception as error:
            QMessageBox.warning(self, TOOL_TITLE(), str(error))
            return
        finally:
            if holder is not None:
                try:
                    remove = getattr(holder, 'remove', None)
                    if remove is not None:
                        remove()
                        self.document.waitForDone()
                except (RuntimeError, AttributeError):
                    pass
            QApplication.restoreOverrideCursor()
        if close:
            self.accept()
        else:
            self.schedule_refresh()


def open_color_range():
    document = Krita.instance().activeDocument()
    if document is None:
        QMessageBox.information(
            QApplication.activeWindow(),
            TOOL_TITLE(),
            tr('Open a document first.', '请先打开文档。'),
        )
        return
    try:
        window = QApplication.activeWindow()
        dialog = ColorRangeDialog(document, window)
        dialog.setModal(False)
        # Keep the live panel reachable while Krita continues drawing the canvas.
        dialog.finished.connect(lambda *_: _open_dialogs.remove(dialog) if dialog in _open_dialogs else None)
        _open_dialogs.append(dialog)
        dialog.show()
    except (RuntimeError, ValueError) as error:
        QMessageBox.warning(QApplication.activeWindow(), TOOL_TITLE(), str(error))
