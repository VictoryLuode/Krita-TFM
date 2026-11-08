"""Self-contained Blender-style pie (radial) menu widget for TFM menus.

A frameless, stay-on-top disc that appears under the cursor. While the trigger
shortcut is held, the mouse direction picks one of the items around the disc;
releasing the trigger activates the highlighted item. A central deadzone avoids
accidental picks.

Items are placed evenly starting from North, going clockwise. Item order ==
display order, so reordering items in the editor reorders the pie directions.
"""

import math

from .qtcompat import (QColor, QCursor, QFont, QPainter, QPen, QPointF, QRect,
                       QRectF, Qt, QTimer, QWidget)


class PieWidget(QWidget):
    RADIUS = 120       # distance from centre to an item
    DEADZONE = 48      # closer than this -> no selection
    ITEM_R = 34        # radius of each item's circle
    MAX_ITEMS = 8

    def __init__(self, slices, parent=None):
        """slices: list of (label, icon|None, trigger_callable)."""
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._slices = slices[:self.MAX_ITEMS]
        self._n = len(self._slices)
        self._size = int(self.RADIUS * 2 + (self.ITEM_R + 14) * 2)
        self.resize(self._size, self._size)
        self._sel = -1
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.setInterval(16)
        self._timer.start()

    # ---------- geometry ----------
    def _center_global(self):
        return QPointF(self.x() + self._size / 2, self.y() + self._size / 2)

    def _dir_point(self, k):
        """Global point of item k (evenly spaced from North, clockwise)."""
        ang = -math.pi / 2 + k * (2 * math.pi / self._n) if self._n else 0
        cx, cy = self._center_global()
        return QPointF(cx + math.cos(ang) * self.RADIUS,
                       cy + math.sin(ang) * self.RADIUS)

    # ---------- show / poll ----------
    def show_pie(self, center_global):
        self.move(int(center_global.x() - self._size / 2),
                  int(center_global.y() - self._size / 2))
        self.show()
        self.raise_()
        self._poll()

    def _poll(self):
        pos = QCursor.pos()
        c = self._center_global()
        dx = pos.x() - c.x()
        dy = pos.y() - c.y()
        dist = math.hypot(dx, dy)
        new_sel = -1
        if dist >= self.DEADZONE and self._n:
            ang = math.atan2(dy, dx)
            best, best_diff = -1, 1e9
            for k in range(self._n):
                a = -math.pi / 2 + k * (2 * math.pi / self._n)
                diff = abs(self._norm(ang - a))
                if diff < best_diff:
                    best_diff, best = diff, k
            new_sel = best
        if new_sel != self._sel:
            self._sel = new_sel
            self.update()

    @staticmethod
    def _norm(a):
        while a > math.pi:
            a -= 2 * math.pi
        while a < -math.pi:
            a += 2 * math.pi
        return a

    # ---------- activation ----------
    def current_trigger(self):
        if 0 <= self._sel < self._n:
            return self._slices[self._sel][2]
        return None

    def close_pie(self):
        self._timer.stop()
        self.hide()
        self.deleteLater()

    # ---------- painting ----------
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self._size / 2, self._size / 2

        # Outer disc
        p.setBrush(QColor(28, 28, 30, 210))
        p.setPen(QPen(QColor(70, 70, 74, 220), 1.5))
        p.drawEllipse(QPointF(cx, cy), self.RADIUS + self.ITEM_R + 10,
                      self.RADIUS + self.ITEM_R + 10)

        # Centre deadzone
        p.setBrush(QColor(70, 70, 74, 210))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), self.DEADZONE * 0.45, self.DEADZONE * 0.45)
        p.setBrush(QColor(40, 40, 42, 230))
        p.drawEllipse(QPointF(cx, cy), self.DEADZONE * 0.22, self.DEADZONE * 0.22)

        # Items
        for k, (label, icon, _trig) in enumerate(self._slices):
            x, y = cx + math.cos(-math.pi / 2 + k * (2 * math.pi / self._n)) * self.RADIUS, \
                   cy + math.sin(-math.pi / 2 + k * (2 * math.pi / self._n)) * self.RADIUS
            active = (k == self._sel)
            if active:
                # Soft selection ring behind the slice.
                p.setBrush(QColor(90, 140, 200, 70))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPointF(x, y), self.ITEM_R + 7, self.ITEM_R + 7)
            p.setBrush(QColor(88, 120, 168, 245) if active else QColor(48, 48, 52, 235))
            p.setPen(QPen(QColor(235, 240, 255, 240) if active else QColor(140, 140, 145, 170),
                          2.2 if active else 1.5))
            p.drawEllipse(QPointF(x, y), self.ITEM_R, self.ITEM_R)
            if icon is not None and not icon.isNull():
                icon.paint(p, QRect(int(x - 16), int(y - 16), 32, 32))
            elif label:
                p.setPen(QColor(245, 245, 245) if active else QColor(210, 210, 210))
                font = QFont("sans-serif", 9)
                font.setBold(active)
                p.setFont(font)
                p.drawText(QRectF(x - self.ITEM_R, y - self.ITEM_R,
                                  self.ITEM_R * 2, self.ITEM_R * 2),
                           Qt.AlignmentFlag.AlignCenter, self._short(label))
        p.end()

    def _short(self, text, limit=10):
        text = text or ""
        if len(text) <= limit:
            return text
        return text[:limit - 1] + "…"
