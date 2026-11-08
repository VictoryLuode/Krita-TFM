"""Interactive sampled-color selection for Krita."""
from krita import Krita, Selection
from .menus.qtcompat import (
    Qt, QByteArray, QTimer, pyqtSignal, QApplication, QCheckBox, QComboBox,
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSlider, QSpinBox, QVBoxLayout, QImage, QPixmap, QColor, QtWidgets,
)
from .i18n import tr
from .color_range_native import channel_mask as native_channel_mask
from .color_range_native import combine as native_combine
from .color_range_native import mask as native_mask
from .color_range_native import perceptual as native_perceptual
from .color_range_overlay import ColorRangeOverlay

TOOL_TITLE = lambda: tr('Advanced Selection', '高级选区')


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


_open_dialogs = []


class ColorRangeDialog(QDialog):
    def __init__(self, document, parent=None):
        super().__init__(parent)
        self.document = document
        self.setWindowTitle(TOOL_TITLE())
        self._source_generation = None
        self._capture_source()
        self._bind_document_changes()
        self.target_color = QColor(255, 255, 255)
        self.mask_mode = QComboBox()
        for group in (
            [('Sampled Color', 'color')],
            [('Reds', 'hue_red'), ('Yellows', 'hue_yellow'),
             ('Greens', 'hue_green'), ('Cyans', 'hue_cyan'),
             ('Blues', 'hue_blue'), ('Magentas', 'hue_magenta'), ('Skin Tones', 'skin')],
            [('Highlights', 'highlights'), ('Midtones', 'midtones'),
             ('Shadows', 'shadows'), ('Brightness', 'luminance')],
            [('Red Channel', 'red'), ('Green Channel', 'green'), ('Blue Channel', 'blue')],
        ):
            if self.mask_mode.count():
                self.mask_mode.insertSeparator(self.mask_mode.count())
            for title, key in group:
                self.mask_mode.addItem(title, key)
        self._mask_cache_key = None
        self._mask_cache = None
        self.color_button = QPushButton('Choose Color…')
        self.color_button.clicked.connect(self.choose_color)
        self.color_button.setVisible(False)
        self.preview = QLabel()
        self.preview.setFixedSize(300, 220)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(220)
        # Keep the historical threshold behavior as the default. The new
        # overrides remain off until explicitly enabled.
        self.threshold_enabled = QCheckBox('Threshold')
        self.threshold_enabled.setChecked(True)
        self.threshold = QSpinBox(); self.threshold.setRange(0, 255); self.threshold.setValue(128)
        self.slider = QSlider(_enum(Qt, 'Horizontal')); self.slider.setRange(0, 255); self.slider.setValue(128)
        self.slider.valueChanged.connect(self.threshold.setValue)
        self.threshold.valueChanged.connect(self.slider.setValue)
        self.threshold_enabled.toggled.connect(self._set_threshold_controls)
        self.tolerance_enabled = QCheckBox('Color Tolerance')
        self.tolerance_enabled.setToolTip('Override the color-match distance independently of Threshold.')
        self.tolerance_enabled.setChecked(False)
        self.tolerance = QSpinBox(); self.tolerance.setRange(0, 255); self.tolerance.setValue(32)
        self.tolerance_slider = QSlider(_enum(Qt, 'Horizontal')); self.tolerance_slider.setRange(0, 255); self.tolerance_slider.setValue(32)
        self.tolerance_slider.valueChanged.connect(self.tolerance.setValue)
        self.tolerance.valueChanged.connect(self.tolerance_slider.setValue)
        self.tolerance_slider.setEnabled(False)
        self.tolerance.setEnabled(False)
        self.tolerance_enabled.toggled.connect(self.tolerance_slider.setEnabled)
        self.tolerance_enabled.toggled.connect(self.tolerance.setEnabled)
        self.softness_enabled = QCheckBox('Softness')
        self.softness_enabled.setToolTip('Override edge feathering independently of Threshold and Color Tolerance.')
        self.softness_enabled.setChecked(False)
        self.softness = QSpinBox(); self.softness.setRange(0, 255); self.softness.setValue(12)
        self.softness_slider = QSlider(_enum(Qt, 'Horizontal')); self.softness_slider.setRange(0, 255); self.softness_slider.setValue(12)
        self.softness_slider.valueChanged.connect(self.softness.setValue)
        self.softness.valueChanged.connect(self.softness_slider.setValue)
        self.softness_slider.setEnabled(False)
        self.softness.setEnabled(False)
        self.softness_enabled.toggled.connect(self.softness_slider.setEnabled)
        self.softness_enabled.toggled.connect(self.softness.setEnabled)
        self.invert = QCheckBox('Invert')
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
        self.preview.setToolTip('White: selected. Black: unselected.')
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
        self.preview_mode.addItem('Selection Outline', 'selection')
        self.preview_mode.addItem('Black & White', 'black_white')
        self.preview_mode.addItem('Quick Mask', 'quick_mask')
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

    def _capture_source(self, source=None):
        if source is None:
            source = self.document.projection(0, 0, self.document.width(), self.document.height()).convertToFormat(
                _image_format('Format_ARGB32'))
        if source.isNull():
            raise ValueError('Unable to read the image projection.')
        gray = source.convertToFormat(QImage.Format.Format_Grayscale8)
        ptr = gray.constBits()
        ptr.setsize(gray.sizeInBytes())
        raw = bytes(ptr)
        width, height = source.width(), source.height()
        luminance = bytearray(width * height)
        for y in range(height):
            luminance[y * width:(y + 1) * width] = raw[y * gray.bytesPerLine():y * gray.bytesPerLine() + width]
        self.source = source
        self.luminance = luminance
        self._mask_cache_key = None
        self._mask_cache = None
        self._source_stale = False
        if hasattr(self, 'source_status'):
            self.source_status.setText('')

    def _refresh_source(self):
        source = self.document.projection(0, 0, self.document.width(), self.document.height()).convertToFormat(
            _image_format('Format_ARGB32'))
        self._capture_source(source)
        return True

    def refresh_source_from_canvas(self):
        """Re-read document projection while the non-modal dialog stays open."""
        if Krita.instance().activeDocument() != self.document:
            QMessageBox.warning(self, TOOL_TITLE(), 'The active document has changed.')
            return
        try:
            self._refresh_source()
        except (RuntimeError, ValueError) as error:
            QMessageBox.warning(self, TOOL_TITLE(), str(error))
            return
        self.schedule_refresh()

    def _set_threshold_controls(self, enabled):
        self.slider.setEnabled(enabled)
        self.threshold.setEnabled(enabled)
        self.schedule_refresh()

    def change_mode(self, *args):
        color_mode = self.mask_mode.currentData() == 'color'
        self.color_button.setVisible(color_mode)
        self.threshold_enabled.setText('Threshold')
        self.schedule_refresh()

    def choose_color(self):
        color = QtWidgets.QColorDialog.getColor(self.target_color, self, 'Mask Color')
        if color.isValid():
            self.target_color = color
            self.color_button.setText('Color: ' + color.name())
            self.schedule_refresh()

    def schedule_refresh(self, *args):
        self.timer.start(150)

    def _canvas_for_view(self, window, view):
        if view is None:
            raise RuntimeError('Unable to identify the active canvas.')
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
        raise RuntimeError('Unable to identify the active canvas.')

    def update_canvas_preview(self, *args):
        self._remove_canvas_preview()
        mode = self.preview_mode.currentData()
        try:
            if self.source is None or self.source.isNull():
                self._refresh_source()
            window = Krita.instance().activeWindow()
            view = window.activeView() if window else None
            if view is None or view.document() != self.document:
                raise RuntimeError('The original document is not active.')
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
        raise ValueError('Unknown color range selection mode.')

    def _show_preview(self, mask):
        width, height = self.source.width(), self.source.height()
        box = self.preview.size()
        preview_width, preview_height = width, height
        pixels = mask
        if width > box.width() or height > box.height():
            preview_height = max(1, int(box.height()))
            preview_width = max(1, int(round(width * (preview_height / height))))
            if preview_width > box.width():
                preview_width = max(1, int(box.width()))
                preview_height = max(1, int(round(height * (preview_width / width))))
            pixels = bytearray(preview_width * preview_height)
            for y in range(preview_height):
                source_y = min(height - 1, y * height // preview_height)
                source_row = source_y * width
                dest_row = y * preview_width
                for x in range(preview_width):
                    source_x = min(width - 1, x * width // preview_width)
                    pixels[dest_row + x] = mask[source_row + source_x]
        image = QImage(bytes(pixels), preview_width, preview_height, preview_width,
                       _image_format('Format_Indexed8')).copy()
        image.setColorTable([0xff000000 | v << 16 | v << 8 | v for v in range(256)])
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
                raise ValueError('Unable to read the current selection.')
        return native_combine(result, old, mode)

    def clean_selection(self):
        if Krita.instance().activeDocument() != self.document:
            QMessageBox.warning(self, TOOL_TITLE(), 'The active document has changed.')
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
            QMessageBox.warning(self, TOOL_TITLE(), 'The active document has changed.')
            return
        QApplication.setOverrideCursor(_enum(Qt, 'WaitCursor'))
        holder = None
        try:
            self._refresh_source()
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
        QMessageBox.information(QApplication.activeWindow(), TOOL_TITLE(), 'Open a document first.')
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
