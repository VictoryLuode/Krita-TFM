from .qtcompat import (QPoint, QTimer, Qt, pyqtSignal, QColor, QPainter, QPen, QLabel, QSizePolicy, QPalette)


class StatusIndicator(QLabel):
    """Fixed-size status icon with accessible message details."""

    details_requested = pyqtSignal(QPoint)
    _BUSY_PREFIXES = ('正在', '准备', '排队', '处理中', 'searching', 'loading', 'queued', 'preparing', 'busy')
    _ERROR_WORDS = (
        '失败', '未保存', '无法', 'error', 'fail', 'failed', 'unable', 'could not',
        'invalid', 'timeout', 'denied',
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = 'info'
        self._message = ''
        self._angle = 0
        self.setWordWrap(False)
        self.setFixedSize(22, 22)
        policy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        policy.setRetainSizeWhenHidden(True)
        self.setSizePolicy(policy)
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._rotate)
        self._sync_timer()
        self.hide()

    def text(self):
        return self._message

    def setText(self, message):
        self._message = str(message or '')
        self.setToolTip(self._message)
        self.setAccessibleName(self._message)
        lowered = self._message.lower()
        if '排队' in lowered or any(lowered.startswith(prefix.lower()) for prefix in self._BUSY_PREFIXES):
            self.state = 'busy'
        elif any(word.lower() in lowered for word in self._ERROR_WORDS):
            self.state = 'error'
        else:
            self.state = 'info'
        self.setVisible(bool(self._message))
        self._sync_timer()
        self.update()

    def clear(self):
        self.setText('')
        self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _sync_timer(self):
        if self.state == 'busy' and self.isVisible():
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def _rotate(self):
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self.rect().center()
        palette = self.palette()
        if self.state == 'error':
            color = QColor('#b85c5c')
            painter.setPen(QPen(color, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, 8, 8)
            painter.drawLine(center.x(), center.y() - 4, center.x(), center.y() + 2)
            painter.drawPoint(center.x(), center.y() + 5)
        elif self.state == 'busy':
            painter.setPen(QPen(palette.color(QPalette.ColorRole.Highlight), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(4, 4, 14, 14, self._angle * 16, 250 * 16)
        else:
            color = palette.color(QPalette.ColorRole.Text)
            painter.setPen(QPen(color, 1.7))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, 8, 8)
            painter.setBrush(color)
            painter.drawEllipse(center.x() - 1, center.y() - 5, 2, 2)
            painter.drawLine(center.x(), center.y() - 1, center.x(), center.y() + 5)
        painter.end()

    def mouseReleaseEvent(self, event):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self.details_requested.emit((event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()))
            event.accept()
            return
        super().mouseReleaseEvent(event)
