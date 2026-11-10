"""Asset Library tree/grid widgets and shared helpers."""

import json
import os
from contextlib import contextmanager

from ..menus.qtcompat import (
    QAbstractItemView,
    QApplication,
    QBrush,
    QByteArray,
    QColor,
    QEvent,
    QHBoxLayout,
    QIcon,
    QImage,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QObject,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QPoint,
    QPointF,
    QSize,
    QStyle,
    QStyledItemDelegate,
    QTimer,
    QTreeWidget,
    QTreeWidgetItem,
    QUrl,
    QVBoxLayout,
    Qt,
    QtCore,
    QtGui,
    QtWidgets,
    exec_,
)
from . import store

ASSET_MIME = "application/x-tfm-assets"
FOLDER_MIME = "application/x-tfm-assets-folder"
MAX_BAKE_PIXELS = 64000000
_MASK_GUARD = 8
ICON_MIN = 64
ICON_MAX = 320
ICON_DEFAULT = 88
LIST_MIN = 16
LIST_MAX = 128
LIST_DEFAULT = 28
LIST_STEP = 8
LIST_PAD = 10
VIEW_THUMB = "thumb"
VIEW_LIST = "list"
THUMB_EDGE = 256

QDrag = QtGui.QDrag
QImageReader = QtGui.QImageReader
QMimeData = QtCore.QMimeData
QSplitter = QtWidgets.QSplitter


@contextmanager
def _wait_cursor():
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()


def _accept_copy(event):
    # Copy, not Move. The layer docker deletes a layer when a drop accepts Move.
    event.setDropAction(Qt.DropAction.CopyAction)
    event.accept()


def _event_pos(event):
    position = getattr(event, "position", None)
    if position is not None:
        try:
            return position().toPoint()
        except (AttributeError, TypeError):
            pass
    return event.pos()


def _run_drag(drag):
    runner = getattr(drag, "exec", None)
    if runner is None:
        runner = drag.exec_
    runner(Qt.DropAction.CopyAction)


def _local_images(mime):
    paths = []
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if os.path.splitext(path)[1].lower() in store.IMAGE_SUFFIXES:
            paths.append(path)
    return paths


def drop_kind(mime):
    if mime is None:
        return None
    if mime.hasFormat(FOLDER_MIME):
        return "folder"
    if mime.hasFormat(ASSET_MIME):
        return "asset"
    if _local_images(mime):
        return "files"
    if (mime.hasImage()
            or mime.hasFormat("application/x-qt-image")
            or mime.hasFormat("application/x-krita-node-internal-pointer")):
        return "image"
    return None


def asset_paths(mime):
    try:
        payload = json.loads(bytes(mime.data(ASSET_MIME)).decode("utf-8"))
    except (TypeError, ValueError, UnicodeError):
        return []
    paths = payload.get("paths") if isinstance(payload, dict) else None
    if not isinstance(paths, list):
        return []
    return [path for path in paths if isinstance(path, str)]


def folder_rel_from_mime(mime):
    rel = tree_payload(mime).get("path")
    return rel if isinstance(rel, str) else ""


def tree_payload(mime):
    try:
        payload = json.loads(bytes(mime.data(FOLDER_MIME)).decode("utf-8"))
    except (TypeError, ValueError, UnicodeError, AttributeError):
        return {}
    return payload if isinstance(payload, dict) else {}


_KIND_ROLE = int(Qt.ItemDataRole.UserRole) + 1
_ID_ROLE = int(Qt.ItemDataRole.UserRole) + 2
_LABEL_ROLE = int(Qt.ItemDataRole.UserRole) + 3


def _item_kind(item):
    if item is None:
        return ""
    return item.data(0, _KIND_ROLE) or ""


def _parent_rel(item):
    parent = item.parent() if item is not None else None
    if parent is None:
        return ""
    return parent.data(0, Qt.ItemDataRole.UserRole) or ""


def _node_ref(item):
    if item is None:
        return None
    kind = _item_kind(item)
    if kind == "folder":
        rel = item.data(0, Qt.ItemDataRole.UserRole) or ""
        leaf = rel.rsplit("/", 1)[-1]
        return {"type": "folder", "name": leaf} if leaf else None
    marker_id = item.data(0, _ID_ROLE) or ""
    if not marker_id:
        return None
    return {"type": kind, "id": marker_id}


def _next_sibling(tree, item):
    parent = item.parent()
    if parent is None:
        index = tree.indexOfTopLevelItem(item)
        if index < 0 or index + 1 >= tree.topLevelItemCount():
            return None
        return tree.topLevelItem(index + 1)
    index = parent.indexOfChild(item)
    if index < 0 or index + 1 >= parent.childCount():
        return None
    return parent.child(index + 1)


_SEPARATOR_INSET = 10


def _marker_gray(palette, selected=False):
    """Quiet gray that stays visible on both light and dark themes."""
    text = palette.color(QPalette.ColorRole.Text)
    base = palette.color(QPalette.ColorRole.Base)
    toward_base = 0.42 if selected else 0.7
    def mix(text_channel, base_channel):
        return int(text_channel * (1 - toward_base) + base_channel * toward_base)
    return QColor(
        mix(text.red(), base.red()),
        mix(text.green(), base.green()),
        mix(text.blue(), base.blue()),
    )


class FolderDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        kind = index.data(_KIND_ROLE)
        if kind == "separator":
            self._paint_separator(painter, option)
            return
        if kind == "title":
            self._paint_title(painter, option, index)
            return
        super().paint(painter, option, index)

    def _column_edges(self, option):
        widget = option.widget
        viewport = widget.viewport() if widget is not None else None
        width = viewport.width() if viewport is not None else option.rect.right()
        left = _SEPARATOR_INSET
        right = max(left, width - _SEPARATOR_INSET)
        return left, right

    def _paint_separator(self, painter, option):
        painter.save()
        left, right = self._column_edges(option)
        band = option.rect
        band.setLeft(0)
        band.setRight(max(right, band.right()))
        painter.setClipRect(band, Qt.ClipOperation.ReplaceClip)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        pen = QPen(_marker_gray(option.palette, selected))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLine(left, band.center().y(), right, band.center().y())
        painter.restore()

    def _paint_title(self, painter, option, index):
        styled = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        selected = bool(styled.state & QStyle.StateFlag.State_Selected)
        gray = _marker_gray(styled.palette, selected)
        styled.palette.setColor(QPalette.ColorRole.Text, gray)
        styled.palette.setColor(QPalette.ColorRole.HighlightedText, gray)
        widget = styled.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, widget)

    def sizeHint(self, option, index):
        if index.data(_KIND_ROLE) == "separator":
            return QSize(max(1, option.rect.width()), 14)
        return super().sizeHint(option, index)


def image_from_mime(mime):
    data = mime.imageData()
    if isinstance(data, QImage):
        return data
    if isinstance(data, QPixmap):
        return data.toImage()
    return QImage()


_CANVAS_WIDGETS = {"KisOpenGLCanvas2", "KisQPainterCanvas"}
_DROP_FILTER = None


def _widget_name(widget):
    try:
        return widget.metaObject().className()
    except Exception:
        return ""


def _inside_assets(widget):
    seen = widget
    while seen is not None:
        try:
            if seen.objectName() == "tfm_assets":
                return True
        except Exception:
            return False
        seen = seen.parent() if hasattr(seen, "parent") else None
    return False


def _canvas_local_point(widget, local):
    if _widget_name(widget) in _CANVAS_WIDGETS:
        return local
    try:
        children = widget.findChildren(QtWidgets.QWidget)
    except Exception:
        return local
    for child in children:
        if _widget_name(child) in _CANVAS_WIDGETS:
            try:
                return child.mapFromGlobal(widget.mapToGlobal(local))
            except Exception:
                return local
    return local


class LibraryDropFilter(QObject):
    """Places an asset drag on the canvas without Krita's drop dialog."""

    def __init__(self):
        super().__init__()
        self.panel = None

    def eventFilter(self, watched, event):
        etype = event.type()
        if etype not in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            return False
        panel = self.panel
        if panel is None:
            return False
        try:
            mime = event.mimeData()
        except Exception:
            return False
        if mime is None or not mime.hasFormat(ASSET_MIME):
            return False
        if _inside_assets(watched):
            return False
        name = _widget_name(watched)
        if name not in _CANVAS_WIDGETS and "Canvas" not in name and name != "KisView":
            return False
        if etype == QEvent.Type.Drop:
            panel._drop_on_canvas(watched, _event_pos(event), mime)
        try:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        except Exception:
            return False
        return True


def _install_drop_filter(panel):
    global _DROP_FILTER
    app = QApplication.instance()
    if app is None:
        return
    if _DROP_FILTER is None:
        _DROP_FILTER = LibraryDropFilter()
        app.installEventFilter(_DROP_FILTER)
    _DROP_FILTER.panel = panel


def write_png(image, path):
    if image is None or image.isNull():
        raise store.AssetError("That drop did not include an image.")
    if image.format() != QImage.Format.Format_ARGB32:
        image = image.convertToFormat(QImage.Format.Format_ARGB32)
    directory = os.path.dirname(path)
    fd, temporary = tempfile_png(directory)
    try:
        if not image.save(temporary, "PNG"):
            raise store.AssetError("Could not save the image.")
        os.replace(temporary, path)
        temporary = ""
    except store.AssetError:
        raise
    except OSError as error:
        raise store.AssetError("Could not save the image.") from error
    finally:
        if temporary and os.path.exists(temporary):
            os.remove(temporary)


def _projection_image(node, doc, bounds):
    """PNG pixels from the layer projection."""
    width = bounds.width()
    height = bounds.height()
    raw = node.projectionPixelData(bounds.x(), bounds.y(), width, height)
    data = bytes(raw)
    try:
        model = doc.colorModel()
        depth = doc.colorDepth()
    except Exception:
        return None
    if model == "RGBA" and depth == "U16" and len(data) >= width * height * 8:
        data = pixels.downsample_u16_bgra(data[:width * height * 8])
    elif not (model == "RGBA" and depth == "U8" and len(data) >= width * height * 4):
        return None
    else:
        data = data[:width * height * 4]
    return pixels.qimage_from_bgra8(data, width, height)


def tempfile_png(directory):
    import tempfile
    fd, temporary = tempfile.mkstemp(dir=directory, suffix=".png")
    os.close(fd)
    return fd, temporary


def _dimensions(path):
    reader = QImageReader(path)
    size = reader.size()
    if size.isValid() and size.width() > 0 and size.height() > 0:
        return size.width(), size.height()
    return None


def _thumbnail(path, edge):
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and size.width() > 0 and size.height() > 0:
        longest = max(size.width(), size.height())
        if longest > edge:
            scale = edge / float(longest)
            reader.setScaledSize(QSize(
                max(1, int(round(size.width() * scale))),
                max(1, int(round(size.height() * scale))),
            ))
    image = reader.read()
    if image.isNull():
        return QIcon()
    if image.width() > edge or image.height() > edge:
        image = image.scaled(
            edge, edge,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return QIcon(QPixmap.fromImage(image))


def _insertion_point(doc):
    root = doc.rootNode()
    if root is None:
        return None, None
    node = doc.activeNode()
    for _ in range(_MASK_GUARD):
        if node is None:
            break
        if not (node.type() or "").endswith("mask"):
            break
        node = node.parentNode()
    if node is None or node.parentNode() is None:
        return root, None
    return node.parentNode(), node


def _ancestors(rel):
    found = {""}
    parts = [part for part in (rel or "").split("/") if part]
    built = []
    for part in parts:
        built.append(part)
        found.add("/".join(built))
    return found


class FolderTree(QTreeWidget):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self._drop_target = None
        self._drop_line = None
        self.setHeaderHidden(True)
        self.setItemDelegate(FolderDelegate(self))
        self.setToolTip(
            "Drag a category to change its order. "
            "Right-click to add a folder, separator, or title. "
            "Double-click a name or title to edit it."
        )
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setAcceptDrops(True)
        # Set after the drag-drop mode. Qt resets the viewport when that mode changes.
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setExpandsOnDoubleClick(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(panel._folder_menu)
        self.currentItemChanged.connect(lambda *_: panel._folder_changed())
        self.itemChanged.connect(panel._folder_renamed)

    def startDrag(self, supportedActions):
        del supportedActions
        self.panel._start_folder_drag()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(_event_pos(event))
            if item is not None and _item_kind(item) != "separator":
                self.editItem(item, 0)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def _slot_at(self, event):
        item = self.itemAt(_event_pos(event))
        if item is None:
            return {"parent": "", "before": None, "into": ""}
        rect = self.visualItemRect(item)
        local = _event_pos(event).y() - rect.top()
        height = max(1, rect.height())
        kind = _item_kind(item)
        if kind == "folder" and height * 0.25 < local < height * 0.75:
            return {
                "parent": item.data(0, Qt.ItemDataRole.UserRole) or "",
                "before": None,
                "into": item.data(0, Qt.ItemDataRole.UserRole) or "",
            }
        parent = _parent_rel(item)
        if local < height / 2:
            return {"parent": parent, "before": _node_ref(item), "into": ""}
        nxt = _next_sibling(self, item)
        return {
            "parent": parent,
            "before": _node_ref(nxt) if nxt is not None else None,
            "into": "",
        }

    def _drop_status(self, event):
        slot = self._slot_at(event)
        if drop_kind(event.mimeData()) == "folder":
            if slot["into"]:
                return "Release to move this into the folder."
            return "Release to change the order."
        folder = slot["into"] or slot["parent"]
        if folder:
            return "Release to store a copy in this folder."
        return "Release to store a copy at the top level."

    def _show_slot(self, event):
        slot = self._slot_at(event)
        if slot["into"]:
            self._drop_line = None
            self._highlight(self.itemAt(_event_pos(event)))
        else:
            self._clear_highlight()
            item = self.itemAt(_event_pos(event))
            if item is None:
                self._drop_line = None
            else:
                rect = self.visualItemRect(item)
                local = _event_pos(event).y() - rect.top()
                y = rect.top() if local < max(1, rect.height()) / 2 else rect.bottom()
                self._drop_line = (rect.left() + 8, rect.right() - 4, y)
        self.viewport().update()

    def dragEnterEvent(self, event):
        if drop_kind(event.mimeData()) is None:
            event.ignore()
            return
        self.panel._remember_status(self._drop_status(event))
        self._show_slot(event)
        _accept_copy(event)

    def dragMoveEvent(self, event):
        if drop_kind(event.mimeData()) is None:
            event.ignore()
            return
        self.panel._remember_status(self._drop_status(event))
        self._show_slot(event)
        _accept_copy(event)

    def dragLeaveEvent(self, event):
        self._clear_highlight()
        self._drop_line = None
        self.viewport().update()
        self.panel._restore_status()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if drop_kind(event.mimeData()) is None:
            event.ignore()
            return
        slot = self._slot_at(event)
        _accept_copy(event)
        self._clear_highlight()
        self._drop_line = None
        self.viewport().update()
        self.panel._restore_status()
        if drop_kind(event.mimeData()) == "folder":
            self.panel._reorder_dropped(tree_payload(event.mimeData()), slot)
            return
        self.panel._drop_on_folder(slot["into"] or slot["parent"], event.mimeData())

    def viewportEvent(self, event):
        result = super().viewportEvent(event)
        if event.type() == QEvent.Type.Paint and self._drop_line:
            painter = QPainter(self.viewport())
            try:
                pen = QPen(self.palette().color(QPalette.ColorRole.Highlight))
                pen.setWidth(2)
                painter.setPen(pen)
                x1, x2, y = self._drop_line
                painter.drawLine(x1, y, x2, y)
            finally:
                painter.end()
        return result

    def _highlight(self, item):
        if item is self._drop_target:
            return
        previous = self._drop_target
        self._drop_target = item
        if previous is not None:
            previous.setBackground(0, QBrush())
        if item is None:
            return
        color = self.palette().color(QPalette.ColorRole.Highlight)
        color.setAlpha(120)
        item.setBackground(0, QBrush(color))

    def _clear_highlight(self):
        item = self._drop_target
        self._drop_target = None
        if item is not None:
            item.setBackground(0, QBrush())

    def forget_highlight(self):
        self._drop_target = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            self.panel._delete_folder()
            return
        super().keyPressEvent(event)


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


class DropPane(QtWidgets.QWidget):
    """Catches a layer drop that lands beside the folder tree and the thumbnails."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.setAcceptDrops(True)

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

__all__ = [name for name in list(globals()) if not name.startswith("__")]
