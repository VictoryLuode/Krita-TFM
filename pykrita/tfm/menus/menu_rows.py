"""Self-painted popup menu rows (icons survive Krita's global QSS)."""

from .qtcompat import (
    QColor,
    QPainter,
    QSize,
    Qt,
    QWidget,
)


class MenuRow(QWidget):
    """Self-painted menu row (icon + text + optional shortcut).

    Krita applies a global stylesheet, which turns every QMenu into a
    QStyleSheetStyle — and that style drops QMenu action icons. A plain QAction
    therefore can never show an icon in a Krita QMenu. Using a QWidgetAction and
    painting the row ourselves (icon + text) bypasses the stylesheet and
    guarantees the icon renders. Hover highlight is painted from the palette.
    """

    def __init__(self, text, parent=None, icon=None, shortcut="",
                 checkable=False, checked=False):
        super().__init__(parent)
        self._text = text
        self._icon = icon
        self._shortcut = shortcut
        self._checkable = checkable
        self._checked = checked
        self._hover = False
        self.setMouseTracking(True)

    def sizeHint(self):
        fm = self.fontMetrics()
        # 40 = left pad 10 + icon column 20 + gap 10, ALWAYS reserved so no-icon
        # rows align their text with icon rows. Checkable rows draw inside it.
        w = 40 + fm.horizontalAdvance(self._text) + 12   # + right pad
        if self._shortcut:
            w += fm.horizontalAdvance(self._shortcut) + 28
        return QSize(w, 30)

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        pal = self.palette()
        if self._hover and self.isEnabled():
            p.fillRect(self.rect(), pal.highlight())
        if not self.isEnabled():
            p.setPen(QColor(154, 154, 154))
        elif self._hover:
            p.setPen(pal.highlightedText().color())
        else:
            p.setPen(pal.text().color())
        fm = self.fontMetrics()
        x_icon = 10           # icon column left edge
        x_text = 40           # text always starts here (icon column reserved)
        y = (self.height() - fm.height()) // 2
        if self._checkable:
            # draw a check box at far-left (inside the reserved icon column)
            box = 16
            bx = 8
            by = (self.height() - box) // 2
            p.setPen(QColor(120, 120, 120))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(bx, by, box, box)
            if self._checked:
                p.setPen(QColor(230, 230, 230))
                p.drawLine(bx + 3, by + box // 2, bx + box // 2, by + box - 3)
                p.drawLine(bx + box // 2, by + box - 3, bx + box - 3, by + 3)
        elif self._icon is not None and not self._icon.isNull():
            size = 20
            p.drawPixmap(x_icon, (self.height() - size) // 2,
                         self._icon.pixmap(QSize(size, size)))
        p.drawText(x_text, y + fm.ascent(), self._text)
        if self._shortcut:
            p.setPen(QColor("#808080"))
            sw = fm.horizontalAdvance(self._shortcut)
            p.drawText(self.width() - sw - 12, y + fm.ascent(), self._shortcut)
        p.end()


class SeparatorRow(QWidget):
    """A thin, non-interactive separator line painted in #2f2f2f.

    Rendering it ourselves (instead of QMenu.addSeparator) lets us control the
    exact colour without any QSS (which would suppress item icons).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)

    def sizeHint(self):
        # Non-zero width so the row lays out (width 0 produced an invisible line).
        return QSize(150, 6)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setPen(QColor("#4a4a4a"))
        p.drawLine(8, self.height() // 2, self.width() - 8, self.height() // 2)
        p.end()
