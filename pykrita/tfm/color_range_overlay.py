"""Temporary QWidget overlay for a single Krita canvas; never edits a document."""
from .menus.qtcompat import QEvent, Qt, QImage, QTimer, QWidget, QPainter, QRectF
from .color_range_native import outline as native_outline


class ColorRangeOverlay(QWidget):
    def __init__(self, canvas, view, document, is_active=None):
        super().__init__(canvas)
        self.canvas = canvas
        self.view = view
        self.document = document
        self.is_active = is_active or (lambda: True)
        self.image = QImage()
        self.mode = 'black_white'
        self._view_state = None
        self._mask_state = None
        self._phase = 0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setGeometry(canvas.rect())
        self.view.installEventFilter(self)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.sync_geometry)

    def set_mask(self, mask, width, height, mode):
        if mode not in ('selection', 'black_white', 'quick_mask') or len(mask) != width * height:
            raise ValueError('Invalid canvas preview mask.')
        state = (bytes(mask), width, height, mode)
        if state == self._mask_state:
            self.sync_geometry()
            return
        self._mask_state = state
        pixels = native_outline(mask, width, height) if mode == 'selection' else bytes(mask)
        image = QImage(pixels, width, height, width, QImage.Format.Format_Indexed8).copy()
        if mode == 'selection':
            image.setColorTable([0] + [0xff000000 if i < 4 else 0xffffffff for i in range(8)])
        elif mode == 'black_white':
            image.setColorTable([0xff000000 | (i << 16) | (i << 8) | i for i in range(256)])
        else:
            # Red indicates unselected pixels, with partial coverage represented by opacity.
            image.setColorTable([((255 - i) * 128 // 255 << 24) | 0x00ff0000 for i in range(256)])
        self.image = image
        self.mode = mode
        self.sync_geometry()

    def sync_geometry(self):
        try:
            if self.canvas is None or self.view.document() != self.document or not self.canvas.isVisible() or not self.is_active():
                self.timer.stop()
                self.hide()
                return
            transform = self.view.flakeToCanvasTransform()
            image_transform = self.view.flakeToImageTransform()
            state = (self.canvas.size(), transform, image_transform)
            changed = state != self._view_state
            self._view_state = state
            if self.geometry() != self.canvas.rect():
                self.setGeometry(self.canvas.rect())
            if not self.isVisible():
                self.show()
                self.raise_()
                changed = True
            if self.mode == 'selection' and self.isVisible():
                self._phase = (self._phase + 1) % 8
                self.image.setColorTable([0] + [0xff000000 if (i + self._phase) % 8 < 4 else 0xffffffff for i in range(8)])
                changed = True
            if changed:
                self.update()
            if self.mode == 'selection' and self.isVisible():
                self.timer.start(100)
        except RuntimeError:
            self.timer.stop()
            self.hide()

    def eventFilter(self, watched, event):
        if watched is self.canvas or watched is self.view:
            event_type = event.type()
            resize = getattr(QEvent, 'Resize', None) or getattr(QEvent.Type, 'Resize', None)
            move = getattr(QEvent, 'Move', None) or getattr(QEvent.Type, 'Move', None)
            show = getattr(QEvent, 'Show', None) or getattr(QEvent.Type, 'Show', None)
            hide = getattr(QEvent, 'Hide', None) or getattr(QEvent.Type, 'Hide', None)
            if event_type in (resize, move, show, hide):
                self.sync_geometry()
        return super().eventFilter(watched, event)

    def paintEvent(self, event):
        if self.image.isNull():
            return
        try:
            image_to_flake, ok = self.view.flakeToImageTransform().inverted()
            if not ok:
                return
            transform = image_to_flake * self.view.flakeToCanvasTransform()
            painter = QPainter(self)
            painter.setTransform(transform)
            painter.drawImage(QRectF(0, 0, self.image.width(), self.image.height()), self.image)
            painter.end()
        except RuntimeError:
            self.timer.stop()
            self.hide()

    def closeEvent(self, event):
        try:
            self.canvas.removeEventFilter(self)
            self.view.removeEventFilter(self)
        except RuntimeError:
            pass
        super().closeEvent(event)
