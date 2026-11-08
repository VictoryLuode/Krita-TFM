from .qtcompat import (QPoint, QRect, Qt, pyqtSignal, QPainter, QPolygon, QMenu, QStyle, QStyleOptionMenuItem)
import math


class HistoryMenu(QMenu):
    """Native QMenu with a separate trailing favorite toggle target."""

    unfavorite_requested = pyqtSignal(str)
    record_requested = pyqtSignal(str)

    _STAR_SLOT = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay, True)
        self._pressed_record = None

    def sizeHint(self):
        size = super().sizeHint()
        if any(self._is_favorite(action) for action in self.actions()):
            size.setWidth(size.width() + self._STAR_SLOT)
        return size

    @staticmethod
    def _is_record(action):
        return action is not None and isinstance(action.data(), str) and bool(action.data())

    @classmethod
    def _is_favorite(cls, action):
        return cls._is_record(action) and bool(action.property('favorite'))

    def actionGeometry(self, action):
        rect = super().actionGeometry(action)
        if not rect.isEmpty():
            rect.setRight(self.rect().right())
        return rect

    def text_rect(self, action):
        return self.actionGeometry(action).adjusted(44, 0, -36, 0)

    def _action_at(self, position):
        if not self.rect().contains(position):
            return None
        return next((action for action in self.actions() if self.actionGeometry(action).contains(position)), None)

    def star_rect(self, action):
        if not self._is_favorite(action):
            return QRect()
        row = self.actionGeometry(action)
        if row.isEmpty():
            return QRect()
        extent = min(18, row.height() - 4)
        if extent <= 0:
            return QRect()
        return QRect(row.right() - 8 - extent + 1,
                     row.center().y() - extent // 2, extent, extent)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for action in self.actions():
            if not self._is_record(action):
                continue
            option = QStyleOptionMenuItem()
            self.initStyleOption(option, action)
            option.rect = self.actionGeometry(action)
            option.text = self.fontMetrics().elidedText(action.text(), Qt.TextElideMode.ElideRight, max(0, self.text_rect(action).width()))
            selected = action is self.activeAction()
            painter.fillRect(option.rect, self.palette().highlight() if selected else self.palette().window())
            self.style().drawControl(QStyle.ControlElement.CE_MenuItem, option, painter, self)
            rect = self.star_rect(action)
            if rect.isEmpty():
                continue
            color = self.palette().highlightedText().color() if selected else self.palette().text().color()
            if not action.isEnabled():
                color = self.palette().color(self.backgroundRole())
            painter.setPen(color)
            painter.setBrush(color)
            # A filled star marks an existing favorite; its hit target is independent of the row.
            cx, cy = rect.center().x(), rect.center().y()
            outer, inner = rect.width() * 0.48, rect.width() * 0.21
            points = []
            for index in range(10):
                radius = outer if index % 2 == 0 else inner
                angle = -math.pi / 2 + index * math.pi / 5
                points.append(QPoint(round(cx + radius * math.cos(angle)), round(cy + radius * math.sin(angle))))
            painter.drawPolygon(QPolygon(points))
        painter.end()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        action = self._action_at(event.pos())
        if self._is_record(action) and action.isEnabled():
            self.setActiveAction(action)

    def mousePressEvent(self, event):
        self._pressed_record = None
        action = self._action_at(event.pos())
        if event.button() == Qt.MouseButton.LeftButton and self._is_record(action) and action.isEnabled():
            self._pressed_record = action.data()
            self.setActiveAction(action)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(event)
        action = self._action_at(event.pos())
        if action is None or not action.isEnabled():
            event.accept()
            return
        if self._is_record(action):
            if self._pressed_record != action.data():
                event.accept()
                return
            self._pressed_record = None
            if self._is_favorite(action) and self.star_rect(action).contains(event.pos()):
                self.unfavorite_requested.emit(action.data())
            else:
                self.record_requested.emit(action.data())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            action = self.activeAction()
            if self._is_record(action) and action.isEnabled():
                self.record_requested.emit(action.data())
                event.accept()
                return
        super().keyPressEvent(event)
