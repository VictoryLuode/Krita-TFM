"""Interactive sampled-color selection for Krita."""
from krita import Krita, Selection
from .menus.qtcompat import (
    Qt, QByteArray, QTimer, pyqtSignal, QApplication, QCheckBox, QComboBox,
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSlider, QSpinBox, QVBoxLayout, QImage, QPixmap, QColor, QtWidgets,
)
from .color_range_native import channel_mask as native_channel_mask
from .color_range_native import combine as native_combine
from .color_range_native import mask as native_mask
from .color_range_native import perceptual as native_perceptual
from .color_range_overlay import ColorRangeOverlay


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
        self.setWindowTitle('Advance Selection')
        self._capture_source()
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
        self.preview.setFrameShape(QLabel.Shape.Box)
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(self.mask_mode)
        layout.addWidget(self.color_button)
        row = QHBoxLayout(); row.addWidget(self.threshold_enabled); row.addWidget(self.slider, 1); row.addWidget(self.threshold); layout.addLayout(row)
        row = QHBoxLayout(); row.addWidget(self.tolerance_enabled); row.addWidget(self.tolerance_slider, 1); row.addWidget(self.tolerance); layout.addLayout(row)
        row = QHBoxLayout(); row.addWidget(self.softness_enabled); row.addWidget(self.softness_slider, 1); row.addWidget(self.softness); layout.addLayout(row)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(self.preview); row.addStretch(); layout.addLayout(row)
        layout.addWidget(self.invert)
        self.preview.setToolTip('White: selected. Black: unselected.')
        buttons = QHBoxLayout()
        self.select_button = QPushButton('Select')
        self.deselect_button = QPushButton('Deselect')
        self.clean_button = QPushButton('Clean')
        self.reselect_button = QPushButton('Reselect')
        self.refresh_source_button = QPushButton('刷新源图')
        self.refresh_source_button.setToolTip('画布改动后点此重新读取投影，避免选区基于过期图像。')
        self.clean_button.clicked.connect(self.clean_selection)
        self.reselect_button.clicked.connect(lambda: self.apply_mode('replace', close=False))
        self.select_button.clicked.connect(lambda: self.apply_mode('add', close=False))
        self.deselect_button.clicked.connect(lambda: self.apply_mode('subtract', close=False))
        self.refresh_source_button.clicked.connect(self.refresh_source_from_canvas)
        buttons.addWidget(self.select_button)
        buttons.addWidget(self.deselect_button)
        buttons.addWidget(self.clean_button)
        buttons.addWidget(self.reselect_button)
        buttons.addWidget(self.refresh_source_button)
        layout.addLayout(buttons)
        box = QDialogButtonBox(_enum(QDialogButtonBox, 'Ok') | _enum(QDialogButtonBox, 'Cancel'))
        box.accepted.connect(self.apply); box.rejected.connect(self.reject); layout.addWidget(box)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self.refresh)
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

    def _refresh_source(self):
        source = self.document.projection(0, 0, self.document.width(), self.document.height()).convertToFormat(
            _image_format('Format_ARGB32'))
        self._capture_source(source)
        return True

    def refresh_source_from_canvas(self):
        """Re-read document projection while the non-modal dialog stays open."""
        if Krita.instance().activeDocument() != self.document:
            QMessageBox.warning(self, 'Advance Selection', 'The active document has changed.')
            return
        try:
            self._refresh_source()
        except (RuntimeError, ValueError) as error:
            QMessageBox.warning(self, 'Advance Selection', str(error))
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
        self.timer.start(60)

    def update_canvas_preview(self, *args):
        self._remove_canvas_preview()
        mode = self.preview_mode.currentData()
        try:
            self._refresh_source()
            window = Krita.instance().activeWindow()
            view = window.activeView() if window else None
            if view is None or view.document() != self.document:
                raise RuntimeError('The original document is not active.')
            canvases = [w for w in window.qwindow().findChildren(QtWidgets.QWidget)
                        if w.isVisible() and w.metaObject().className() in ('KisOpenGLCanvas2', 'KisQPainterCanvas')]
            if len(canvases) != 1:
                raise RuntimeError('Unable to identify a unique active canvas.')
            self.overlay = ColorRangeOverlay(canvases[0], view, self.document,
                                              lambda: window.activeView() == view)
            self.overlay.set_mask(self.mask(), self.source.width(), self.source.height(), mode)
            self.overlay.show()
            self.overlay.raise_()
        except (RuntimeError, ValueError, AttributeError) as error:
            self._remove_canvas_preview()
            self.preview_mode.blockSignals(True)
            self.preview_mode.setCurrentIndex(0)
            self.preview_mode.blockSignals(False)
            QMessageBox.warning(self, 'Advance Selection Preview', str(error))

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

    def refresh(self):
        try:
            mask = self.combined_mask()
            image = QImage(bytes(mask), self.source.width(), self.source.height(),
                           self.source.width(), _image_format('Format_Indexed8')).copy()
            image.setColorTable([0xff000000 | v << 16 | v << 8 | v for v in range(256)])
            self.preview.setPixmap(QPixmap.fromImage(image).scaled(
                self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))
            if self.overlay is not None:
                self.overlay.set_mask(mask, self.source.width(), self.source.height(), self.preview_mode.currentData())
        except (RuntimeError, ValueError, TypeError) as error:
            self.timer.stop()
            self.preview.clear()
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
            QMessageBox.warning(self, 'Advance Selection', 'The active document has changed.')
            return
        try:
            if self.document.selection() is not None:
                self.document.setSelection(None)
                self.document.waitForDone()
                self.document.refreshProjection()
        except Exception as error:
            QMessageBox.warning(self, 'Advance Selection', str(error))
            return
        self.schedule_refresh()

    def apply(self):
        self.apply_mode('replace', close=True)

    def apply_mode(self, mode, close=False):
        if Krita.instance().activeDocument() != self.document:
            QMessageBox.warning(self, 'Advance Selection', 'The active document has changed.')
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
            QMessageBox.warning(self, 'Advance Selection', str(error))
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
        QMessageBox.information(QApplication.activeWindow(), 'Advance Selection', 'Open a document first.')
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
        QMessageBox.warning(QApplication.activeWindow(), 'Advance Selection', str(error))
