from .qtcompat import (Qt, QSize, pyqtSignal, QTabBar, QStylePainter, QStyleOptionTab, QStyle, QApplication, QSizePolicy, QAbstractButton, QPainter, QPen)


class TabCloseButton(QAbstractButton):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self.setToolTip('取消收藏（不切换搜索）')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self.palette().color(self.palette().ColorRole.ButtonText)
        painter.setPen(QPen(color, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(6, 6, 12, 12)
        painter.drawLine(12, 6, 6, 12)


class FavoriteTabs(QTabBar):
    """Native compact tabs; only a completed click activates, not a reorder drag."""
    record_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active_id = None
        self._pressed_id = None
        self._press_pos = None
        self._dragged = False
        self.setExpanding(False)
        self.setMovable(True)
        self.setTabsClosable(True)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setDocumentMode(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.setAccessibleName('收藏搜索标签；可拖动排序，关闭即取消收藏')

    def minimumSizeHint(self):
        return QSize(0, self.sizeHint().height())

    def install_close_button(self, index, identity):
        for side in (QTabBar.ButtonPosition.LeftSide, QTabBar.ButtonPosition.RightSide):
            old = self.tabButton(index, side)
            self.setTabButton(index, side, None)
            if old is not None:
                old.deleteLater()
        button = TabCloseButton(self)
        def close_record():
            index = next((i for i in range(self.count()) if self.tabData(i) == identity), -1)
            if index >= 0:
                self.tabCloseRequested.emit(index)
        button.clicked.connect(close_record)
        self.setTabButton(index, QTabBar.ButtonPosition.RightSide, button)

    def tabSizeHint(self, index):
        size = super().tabSizeHint(index)
        size.setWidth(max(70, min(180, size.width())))
        return size

    def paintEvent(self, event):
        painter = QStylePainter(self)
        for index in range(self.count()):
            option = QStyleOptionTab()
            self.initStyleOption(option, index)
            option.state &= ~QStyle.StateFlag.State_Selected
            if self.tabData(index) == self.active_id:
                option.state |= QStyle.StateFlag.State_Selected
            painter.drawControl(QStyle.ControlElement.CE_TabBarTab, option)

    def mousePressEvent(self, event):
        index = self.tabAt(event.pos())
        self._pressed_id = self.tabData(index) if event.button() == Qt.MouseButton.LeftButton and index >= 0 else None
        self._press_pos = event.pos()
        self._dragged = False
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pressed_id is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if (event.pos() - self._press_pos).manhattanLength() >= QApplication.startDragDistance():
                self._dragged = True
                current = next((i for i in range(self.count()) if self.tabData(i) == self._pressed_id), -1)
                target = self.tabAt(event.pos())
                if current >= 0 and target >= 0 and current != target:
                    center = self.tabRect(target).center().x()
                    origin = self.tabRect(current).center().x()
                    if (center > origin and event.pos().x() >= center) or (center < origin and event.pos().x() <= center):
                        self.moveTab(current, target)
            # Do not enter Qt5's animated drag handler while tabMoved callbacks
            # persist and refresh tab widgets. moveTab provides the same order API.
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        index = self.tabAt(event.pos())
        identity = self.tabData(index) if index >= 0 else None
        activate = event.button() == Qt.MouseButton.LeftButton and not self._dragged and identity and identity == self._pressed_id
        self._pressed_id = None
        self._press_pos = None
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
        else:
            super().mouseReleaseEvent(event)
        if activate:
            self.setCurrentIndex(index)
            self.record_requested.emit(identity)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if self.currentIndex() >= 0:
                self.record_requested.emit(self.tabData(self.currentIndex()))
            event.accept()
            return
        super().keyPressEvent(event)
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right) and self.currentIndex() >= 0:
            self.record_requested.emit(self.tabData(self.currentIndex()))
