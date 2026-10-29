"""Interactive sampled-color selection for Krita."""
from krita import Krita, Selection
from .menus.qtcompat import (
    Qt, QByteArray, QTimer, pyqtSignal, QApplication, QCheckBox, QComboBox,
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSlider, QSpinBox, QVBoxLayout, QImage, QPixmap, QColor, QtWidgets,
)
from .color_range_native import combine as native_combine
from .color_range_native import mask as native_mask
from .color_range_native import perceptual as native_perceptual
from .color_range_overlay import ColorRangeOverlay
import colorsys
import hashlib


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
        self.source = document.projection(0, 0, document.width(), document.height()).convertToFormat(_image_format('Format_ARGB32'))
        if self.source.isNull():
            raise ValueError('Unable to read the image projection.')
        gray = self.source.convertToFormat(QImage.Format.Format_Grayscale8)
        ptr = gray.constBits()
        ptr.setsize(gray.sizeInBytes())
        raw = bytes(ptr)
        width, height = self.source.width(), self.source.height()
        self.luminance = b''.join(raw[y * gray.bytesPerLine():y * gray.bytesPerLine() + width] for y in range(height))
        ptr = self.source.constBits()
        ptr.setsize(self.source.sizeInBytes())
        raw = bytes(ptr)
        self.alpha = raw[3::4]
        self.channels = {'luminance': self.luminance, 'red': raw[2::4],
                         'green': raw[1::4], 'blue': raw[0::4]}
        self.rgb = tuple(bytes(channel) for channel in (raw[2::4], raw[1::4], raw[0::4]))
        self.source_signature = hashlib.sha256(bytes(raw)).digest()
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
        self.parameter_label = QLabel('Threshold')
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
        self.clean_button.clicked.connect(self.clean_selection)
        self.reselect_button.clicked.connect(lambda: self.apply_mode('replace', close=False))
        self.select_button.clicked.connect(lambda: self.apply_mode('add', close=False))
        self.deselect_button.clicked.connect(lambda: self.apply_mode('subtract', close=False))
        buttons.addWidget(self.select_button)
        buttons.addWidget(self.deselect_button)
        buttons.addWidget(self.clean_button)
        buttons.addWidget(self.reselect_button)
        layout.addLayout(buttons)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
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
            threshold_active = self.threshold_enabled.isChecked()
            tolerance_active = self.tolerance_enabled.isChecked()
            softness_active = self.softness_enabled.isChecked()
            if threshold_active or tolerance_active or softness_active:
                cutoff = self.threshold.value() if threshold_active else 128
                if tolerance_active:
                    cutoff = max(0, cutoff - self.tolerance.value())
                feather = self.softness.value() if softness_active else 0
                result = bytearray(len(self.channels[mode]))
                for index, (value, alpha) in enumerate(zip(self.channels[mode], self.alpha)):
                    if feather:
                        t = max(0.0, min(1.0, (value - (cutoff - feather)) / (2.0 * feather)))
                        weight = round(255 * t * t * (3.0 - 2.0 * t))
                    else:
                        weight = 255 if value >= cutoff else 0
                    if inverted:
                        weight = 255 - weight
                    result[index] = round(weight * alpha / 255)
                return bytes(result)
            channel = self.channels[mode]
            return bytes(round((255 - value if inverted else value) * alpha / 255)
                         for value, alpha in zip(channel, self.alpha))
        if self.threshold_enabled.isChecked():
            table = bytes(255 if ((value >= threshold) != inverted) else 0 for value in range(256))
            binary = self.channels[mode].translate(table)
            return bytes(value & alpha for value, alpha in zip(binary, self.alpha))
        channel = self.channels[mode]
        return bytes(round((255 - value if inverted else value) * alpha / 255)
                     for value, alpha in zip(channel, self.alpha))

    @staticmethod
    def _smooth_weight(distance, tolerance, softness):
        if softness <= 0:
            return 255 if distance <= tolerance else 0
        edge = max(1e-6, softness)
        t = max(0.0, min(1.0, (tolerance + edge - distance) / (2.0 * edge)))
        return round(255 * t * t * (3.0 - 2.0 * t))

    def _perceptual_mask(self, mode, threshold, inverted):
        width, height = self.source.width(), self.source.height()
        result = bytearray(width * height)
        r, g, b = self.rgb
        if mode.startswith('hue_'):
            centers = {'hue_red': 0.0, 'hue_yellow': 60.0, 'hue_green': 120.0,
                       'hue_cyan': 180.0, 'hue_blue': 240.0, 'hue_magenta': 300.0}
            center = centers[mode]
            tolerance = max(2.0, threshold * 0.65)
            softness = max(1.0, tolerance * 0.35)
            for index, (red, green, blue, alpha) in enumerate(zip(r, g, b, self.alpha)):
                color = QColor(red, green, blue)
                saturation = color.saturationF()
                hue = color.hueF() * 360.0 if color.hueF() >= 0 else -1.0
                if hue < 0 or saturation <= 0.04:
                    weight = 0
                else:
                    distance = abs(hue - center)
                    distance = min(distance, 360.0 - distance)
                    distance *= max(0.05, saturation)
                    weight = self._smooth_weight(distance, tolerance, softness)
                if inverted:
                    weight = 255 - weight
                result[index] = round(weight * alpha / 255)
            return bytes(result)
        if mode == 'skin':
            hue_tolerance = 19.0 + threshold * 0.12
            for index, (red, green, blue, alpha) in enumerate(zip(r, g, b, self.alpha)):
                color = QColor(red, green, blue)
                hue = color.hueF() * 360.0 if color.hueF() >= 0 else -1.0
                saturation = color.saturationF()
                value = color.valueF()
                if hue < 0 or saturation < 0.08:
                    weight = 0
                else:
                    hue_distance = abs(hue - 27.0)
                    hue_distance = min(hue_distance, 360.0 - hue_distance)
                    hue_weight = self._smooth_weight(hue_distance, hue_tolerance, 8.0)
                    sat_weight = self._smooth_weight(abs(saturation - 0.42), 0.36, 0.22)
                    value_weight = self._smooth_weight(abs(value - 0.72), 0.58, 0.34)
                    weight = round(hue_weight * sat_weight * value_weight / (255 * 255))
                if inverted:
                    weight = 255 - weight
                result[index] = round(weight * alpha / 255)
            return bytes(result)
        softness = max(3.0, threshold * 0.24)
        for index, alpha in enumerate(self.alpha):
            lum = self.luminance[index]
            if mode == 'highlights':
                weight = self._smooth_weight(255 - lum, 60.0, softness)
            elif mode == 'shadows':
                weight = self._smooth_weight(lum, 60.0, softness)
            else:
                weight = self._smooth_weight(abs(lum - 128.0), 56.0, softness)
            if inverted:
                weight = 255 - weight
            result[index] = round(weight * alpha / 255)
        return bytes(result)

    def preview_image(self):
        mask = self.combined_mask()
        image = QImage(bytes(mask), self.source.width(), self.source.height(),
                       self.source.width(), _image_format('Format_Indexed8')).copy()
        image.setColorTable([0xff000000 | v << 16 | v << 8 | v for v in range(256)])
        return image

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

    def _refresh_quick_mask(self, mask):
        node = self.quick_mask_node
        if node is None:
            return
        signature = (self.mask_mode.currentData(), self.threshold.value(), self.threshold_enabled.isChecked(),
                     self.tolerance.value(), self.tolerance_enabled.isChecked(),
                     self.softness.value(), self.softness_enabled.isChecked(),
                     self.invert.isChecked(), self.target_color.name(), hashlib.sha256(mask).digest())
        if signature == self.quick_mask_signature:
            return
        rgba = bytearray(len(mask) * 4)
        for index, coverage in enumerate(mask):
            alpha = coverage
            offset = index * 4
            rgba[offset:offset + 4] = bytes((255, 0, 0, alpha))
        node.setPixelData(QByteArray(bytes(rgba)), 0, 0, self.source.width(), self.source.height())
        self.document.waitForDone()
        self.quick_mask_signature = signature

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
        width, height = self.source.width(), self.source.height()
        QApplication.setOverrideCursor(_enum(Qt, 'WaitCursor'))
        try:
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
