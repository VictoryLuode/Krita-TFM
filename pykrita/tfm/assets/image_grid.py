"""Asset Library thumbnail / list grid."""

from .widget_helpers import *  # noqa: F401,F403

class ImageGrid(QListWidget):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self._view_mode = VIEW_THUMB
        self._icon_edge = ICON_DEFAULT
        self._list_icon = LIST_DEFAULT
        self._zoom_remainder = 0
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setUniformItemSizes(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        # The list's viewport is what actually receives the drop. Without this,
        # a drag from the Layers docker is refused and nothing is stored.
        self.viewport().setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(panel._image_menu)
        self.itemChanged.connect(panel._image_renamed)
        self.set_view_mode(VIEW_THUMB)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(_event_pos(event))
            if item is not None:
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self.editItem(item)
                else:
                    self.panel._insert_image_item(item)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._zoom_remainder += event.angleDelta().y()
            steps = int(self._zoom_remainder / 120)
            self._zoom_remainder -= steps * 120
            if steps:
                if self._view_mode == VIEW_LIST:
                    self.set_list_icon(self._list_icon + steps * LIST_STEP)
                    self.panel._remember_list_icon(self._list_icon)
                else:
                    self.set_icon_edge(self._icon_edge + steps * 16)
                    self.panel._remember_icon_edge(self._icon_edge)
            event.accept()
            return
        super().wheelEvent(event)

    def set_view_mode(self, mode):
        mode = VIEW_LIST if mode == VIEW_LIST else VIEW_THUMB
        self._view_mode = mode
        if mode == VIEW_LIST:
            self.setViewMode(QListWidget.ViewMode.ListMode)
            self.setFlow(QListWidget.Flow.TopToBottom)
            self.setWrapping(False)
            self.setSpacing(2)
            self.setIconSize(QSize(self._list_icon, self._list_icon))
            self.setGridSize(QSize())
            self.setToolTip(
                "Double-click to place on the canvas. Ctrl+double-click to rename. "
                "Hold Ctrl and scroll to resize the rows."
            )
        else:
            self.setViewMode(QListWidget.ViewMode.IconMode)
            self.setFlow(QListWidget.Flow.LeftToRight)
            self.setWrapping(True)
            self.setSpacing(8)
            self._apply_icon_edge(self._icon_edge)
            self.setToolTip(
                "Double-click to place on the canvas. Ctrl+double-click to rename. "
                "Hold Ctrl and scroll to resize the thumbnails."
            )
        self._restyle_items()

    def set_icon_edge(self, edge):
        edge = max(ICON_MIN, min(ICON_MAX, int(edge)))
        if edge == self._icon_edge:
            return
        anchor = self.itemAt(QPoint(8, 8))
        self._icon_edge = edge
        if self._view_mode == VIEW_THUMB:
            self._apply_icon_edge(edge)
        if anchor is not None:
            self.scrollToItem(anchor, QAbstractItemView.ScrollHint.PositionAtTop)

    def set_list_icon(self, edge):
        edge = max(LIST_MIN, min(LIST_MAX, int(edge)))
        if edge == self._list_icon:
            return
        anchor = self.itemAt(QPoint(8, 8))
        self._list_icon = edge
        if self._view_mode == VIEW_LIST:
            self.setIconSize(QSize(edge, edge))
            self._restyle_items()
        if anchor is not None:
            self.scrollToItem(anchor, QAbstractItemView.ScrollHint.PositionAtTop)

    def _apply_icon_edge(self, edge):
        cell = QSize(edge + 16, edge + 40)
        self.setIconSize(QSize(edge, edge))
        self.setGridSize(cell)
        for index in range(self.count()):
            self.item(index).setSizeHint(cell)
        self.doItemsLayout()
        if hasattr(self.panel, "_thumb_timer"):
            self.panel._thumb_timer.start()

    def _item_size_hint(self):
        if self._view_mode == VIEW_LIST:
            return QSize(0, self._list_icon + LIST_PAD)
        edge = self._icon_edge
        return QSize(edge + 16, edge + 40)

    def _item_alignment(self):
        if self._view_mode == VIEW_LIST:
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        return Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop

    def _restyle_items(self):
        hint = self._item_size_hint()
        align = self._item_alignment()
        if self._view_mode == VIEW_LIST:
            self.setUniformItemSizes(False)
        for index in range(self.count()):
            item = self.item(index)
            item.setSizeHint(hint)
            item.setTextAlignment(align)
        if self._view_mode == VIEW_LIST:
            self.setUniformItemSizes(True)
        self.doItemsLayout()
        if hasattr(self.panel, "_thumb_timer"):
            self.panel._thumb_timer.start()

    def startDrag(self, supportedActions):
        del supportedActions
        self.panel._start_drag()

    def dragEnterEvent(self, event):
        if drop_kind(event.mimeData()) in (None, "folder"):
            event.ignore()
            return
        self.panel._remember_status("Release to store a copy.")
        _accept_copy(event)

    def dragMoveEvent(self, event):
        if drop_kind(event.mimeData()) in (None, "folder"):
            event.ignore()
            return
        _accept_copy(event)

    def dragLeaveEvent(self, event):
        self.panel._restore_status()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if drop_kind(event.mimeData()) in (None, "folder"):
            event.ignore()
            return
        _accept_copy(event)
        self.panel._restore_status()
        self.panel._drop_on_folder(self.panel._current_folder(), event.mimeData())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            self.panel._delete_images()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.panel._insert_selected()
            return
        super().keyPressEvent(event)
__all__ = [name for name in list(globals()) if not name.startswith("__")]
