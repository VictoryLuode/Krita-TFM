"""Asset Library docker: folders on the left, reusable assets on the right."""

import json
import os
from contextlib import contextmanager

from krita import DockWidget, DockWidgetFactory, DockWidgetFactoryBase, InfoObject, Krita

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
    QPixmap,
    QPoint,
    QPointF,
    QSize,
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
from . import filter_asset, group_asset, mask_asset, pixels, store

ASSET_MIME = "application/x-tfm-assets"
FOLDER_MIME = "application/x-tfm-assets-folder"
MAX_BAKE_PIXELS = 64000000
_MASK_GUARD = 8
ICON_MIN = 64
ICON_MAX = 320
ICON_DEFAULT = 88
LIST_ICON = 28
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
    try:
        payload = json.loads(bytes(mime.data(FOLDER_MIME)).decode("utf-8"))
    except (TypeError, ValueError, UnicodeError):
        return ""
    rel = payload.get("path") if isinstance(payload, dict) else ""
    return rel if isinstance(rel, str) else ""


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
        self.setHeaderHidden(True)
        self.setToolTip("Right-click to create a folder. Double-click a name to rename it.")
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setAcceptDrops(True)
        # Set after the drag-drop mode. Qt resets the viewport when that mode changes.
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
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
            if item is not None:
                self.editItem(item, 0)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def _rel_at(self, event):
        item = self.itemAt(_event_pos(event))
        if item is None:
            return ""
        return item.data(0, Qt.ItemDataRole.UserRole) or ""

    def _drop_status(self, event):
        rel = self._rel_at(event)
        if drop_kind(event.mimeData()) == "folder":
            if rel:
                return "Release to move this folder here."
            return "Release to move this folder to the top level."
        if rel:
            return "Release to store a copy in this folder."
        return "Release to store a copy at the top level."

    def dragEnterEvent(self, event):
        if drop_kind(event.mimeData()) is None:
            event.ignore()
            return
        self.panel._remember_status(self._drop_status(event))
        self._highlight(self.itemAt(_event_pos(event)))
        _accept_copy(event)

    def dragMoveEvent(self, event):
        if drop_kind(event.mimeData()) is None:
            event.ignore()
            return
        self.panel._remember_status(self._drop_status(event))
        self._highlight(self.itemAt(_event_pos(event)))
        _accept_copy(event)

    def dragLeaveEvent(self, event):
        self._clear_highlight()
        self.panel._restore_status()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if drop_kind(event.mimeData()) is None:
            event.ignore()
            return
        _accept_copy(event)
        self._clear_highlight()
        self.panel._restore_status()
        self.panel._drop_on_folder(self._rel_at(event), event.mimeData())

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
        if (
            self._view_mode == VIEW_THUMB
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self._zoom_remainder += event.angleDelta().y()
            steps = int(self._zoom_remainder / 120)
            self._zoom_remainder -= steps * 120
            if steps:
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
            self.setIconSize(QSize(LIST_ICON, LIST_ICON))
            self.setGridSize(QSize())
            self.setToolTip(
                "Double-click to place on the canvas. Ctrl+double-click to rename."
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

    def _apply_icon_edge(self, edge):
        cell = QSize(edge + 16, edge + 40)
        self.setIconSize(QSize(edge, edge))
        self.setGridSize(cell)
        for index in range(self.count()):
            self.item(index).setSizeHint(cell)
        self.doItemsLayout()

    def _item_size_hint(self):
        if self._view_mode == VIEW_LIST:
            return QSize(0, LIST_ICON + 10)
        edge = self._icon_edge
        return QSize(edge + 16, edge + 40)

    def _item_alignment(self):
        if self._view_mode == VIEW_LIST:
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        return Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop

    def _restyle_items(self):
        hint = self._item_size_hint()
        align = self._item_alignment()
        for index in range(self.count()):
            item = self.item(index)
            item.setSizeHint(hint)
            item.setTextAlignment(align)
        self.doItemsLayout()

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


class AssetLibraryDocker(DockWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Asset Library")
        from ..manager import assets_directory
        try:
            self._root = store.ensure_assets(assets_directory())
        except OSError:
            self._root = store.ensure_assets(store.default_assets_dir())
        self._thumbs = {}
        self._dragging = False
        self._pending = None
        self._loading = False

        widget = DropPane(self)
        widget.setMinimumSize(260, 180)
        widget.setToolTip(
            "Drop a layer here to store it. "
            "Double-click a thumbnail to place it as a paint layer. "
            "Ctrl+double-click to rename. Right-click for Place as Reference. "
            "Drag a thumbnail onto the canvas or the Layers docker to place it. "
            "Hold Ctrl and scroll over the images to resize them."
        )
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.tree = FolderTree(self)
        self.grid = ImageGrid(self)
        self.grid.set_icon_edge(self._saved_icon_edge())

        left = QtWidgets.QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        left_layout.addWidget(self.tree, 1)
        left_layout.addWidget(self._build_view_mode_bar())

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(left)
        splitter.addWidget(self.grid)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([150, 420])
        layout.addWidget(splitter, 1)
        self.setWidget(widget)
        self._apply_view_mode(self._saved_view_mode(), persist=False)
        self._reload("")
        _install_drop_filter(self)
        QTimer.singleShot(0, self._hide_when_disabled)

    def _build_view_mode_bar(self):
        bar = QtWidgets.QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        self._view_thumb = QtWidgets.QToolButton()
        self._view_thumb.setCheckable(True)
        self._view_thumb.setAutoRaise(True)
        self._view_thumb.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self._view_thumb.setText("Thumbs")
        self._view_thumb.setToolTip("Thumbnail view")
        self._view_list = QtWidgets.QToolButton()
        self._view_list.setCheckable(True)
        self._view_list.setAutoRaise(True)
        self._view_list.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self._view_list.setText("List")
        self._view_list.setToolTip("List view")
        group = QtWidgets.QButtonGroup(bar)
        group.setExclusive(True)
        group.addButton(self._view_thumb)
        group.addButton(self._view_list)
        self._view_thumb.clicked.connect(lambda: self._apply_view_mode(VIEW_THUMB))
        self._view_list.clicked.connect(lambda: self._apply_view_mode(VIEW_LIST))
        row.addWidget(self._view_thumb, 1)
        row.addWidget(self._view_list, 1)
        return bar

    def _apply_view_mode(self, mode, persist=True):
        mode = VIEW_LIST if mode == VIEW_LIST else VIEW_THUMB
        self._view_thumb.blockSignals(True)
        self._view_list.blockSignals(True)
        self._view_thumb.setChecked(mode == VIEW_THUMB)
        self._view_list.setChecked(mode == VIEW_LIST)
        self._view_thumb.blockSignals(False)
        self._view_list.blockSignals(False)
        self.grid.set_view_mode(mode)
        if persist:
            self._remember_view_mode(mode)

    def canvasChanged(self, canvas):
        del canvas
        QTimer.singleShot(0, self._hide_when_disabled)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._hide_when_disabled)

    def _hide_when_disabled(self):
        from ..manager import assets_enabled
        if assets_enabled():
            return
        toggle = self.toggleViewAction()
        if toggle is not None:
            toggle.setVisible(False)
            toggle.setEnabled(False)
        if self.isVisible():
            self.hide()

    def set_assets_root(self, root):
        self._root = store.ensure_assets(root)
        self._thumbs.clear()
        folder = self._current_folder()
        try:
            known = set(store.list_folders(self._root))
        except store.AssetError:
            known = set()
        if folder not in known:
            folder = ""
        self._reload(folder)

    def _set_status(self, text):
        del text

    def _remember_status(self, text):
        del text

    def _restore_status(self):
        return

    def _document(self):
        try:
            canvas = self.canvas()
        except Exception:
            canvas = None
        if canvas is not None:
            try:
                view = canvas.view()
                if view is not None and view.document() is not None:
                    return view.document()
            except Exception:
                pass
        try:
            return Krita.instance().activeDocument()
        except Exception:
            return None

    def _current_folder(self):
        item = self.tree.currentItem()
        if item is None:
            return ""
        return item.data(0, Qt.ItemDataRole.UserRole) or ""

    def _folder_changed(self):
        if self._loading:
            return
        self._fill_grid(None)

    def _reload(self, folder, select_image=None, status=None):
        del status
        self._fill_tree(folder)
        self._fill_grid(select_image)

    def _note_change(self, folder, select_image=None, status=None):
        if self._dragging:
            self._pending = (folder, select_image, status)
            return
        self._reload(folder, select_image, status)

    def _fill_tree(self, folder):
        was_empty = self.tree.topLevelItemCount() == 0
        expanded = set()
        if not was_empty:
            self._collect_expanded(None, expanded)
        keep_open = expanded | _ancestors(folder)
        self._loading = True
        self.tree.blockSignals(True)
        try:
            self.tree.forget_highlight()
            self.tree.clear()
            items = {}
            for rel in store.list_folders(self._root):
                parent_rel = rel.rsplit("/", 1)[0] if "/" in rel else ""
                parent = items.get(parent_rel)
                label = rel.rsplit("/", 1)[-1]
                item = QTreeWidgetItem(self.tree if parent is None else parent, [label])
                item.setData(0, Qt.ItemDataRole.UserRole, rel)
                item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsDragEnabled
                    | Qt.ItemFlag.ItemIsDropEnabled
                    | Qt.ItemFlag.ItemIsEditable
                )
                item.setToolTip(0, "Double-click the name to rename it. Right-click to create a folder. Drop a layer or image here.")
                item.setExpanded(was_empty or rel in keep_open)
                items[rel] = item
            current = items.get(folder) if folder else None
            if current is not None:
                self.tree.setCurrentItem(current)
                self.tree.scrollToItem(current)
            else:
                self.tree.clearSelection()
                self.tree.setCurrentItem(None)
        finally:
            self.tree.blockSignals(False)
            self._loading = False

    def _collect_expanded(self, item, found):
        if item is None:
            for index in range(self.tree.topLevelItemCount()):
                self._collect_expanded(self.tree.topLevelItem(index), found)
            return
        if item.isExpanded():
            found.add(item.data(0, Qt.ItemDataRole.UserRole) or "")
        for index in range(item.childCount()):
            self._collect_expanded(item.child(index), found)

    def _fill_grid(self, select_image):
        folder = self._current_folder()
        self._loading = True
        self.grid.blockSignals(True)
        try:
            self._fill_grid_items(folder, select_image)
        finally:
            self.grid.blockSignals(False)
            self._loading = False

    def _fill_grid_items(self, folder, select_image):
        self.grid.clear()
        chosen = None
        try:
            names = store.list_images(self._root, folder)
        except store.AssetError:
            names = []
        for name in names:
            rel = "{}/{}".format(folder, name) if folder else name
            try:
                path = store.image_path(self._root, rel)
            except store.AssetError:
                continue
            item = QListWidgetItem(os.path.splitext(name)[0])
            item.setData(Qt.ItemDataRole.UserRole, rel)
            item.setIcon(self._icon(path))
            item.setToolTip(self._tip(path, name))
            item.setTextAlignment(self.grid._item_alignment())
            item.setSizeHint(self.grid._item_size_hint())
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDragEnabled
                | Qt.ItemFlag.ItemIsEditable
            )
            self.grid.addItem(item)
            if rel == select_image:
                chosen = item
        if chosen is not None:
            self.grid.setCurrentItem(chosen)
            chosen.setSelected(True)
            self.grid.scrollToItem(chosen)

    def _saved_icon_edge(self):
        try:
            app = Krita.instance()
            raw = app.readSetting("TFM", "assets_icon_size", "")
            if raw == "":
                raw = app.readSetting("TFM", "library_icon_size", str(ICON_DEFAULT))
            value = int(raw)
        except (TypeError, ValueError, AttributeError):
            return ICON_DEFAULT
        return max(ICON_MIN, min(ICON_MAX, value))

    def _remember_icon_edge(self, edge):
        self._pending_icon_edge = int(edge)
        timer = getattr(self, "_icon_edge_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._write_icon_edge)
            self._icon_edge_timer = timer
        timer.start(300)

    def _write_icon_edge(self):
        edge = getattr(self, "_pending_icon_edge", None)
        if edge is None:
            return
        try:
            Krita.instance().writeSetting("TFM", "assets_icon_size", str(int(edge)))
        except Exception:
            pass

    def _saved_view_mode(self):
        try:
            raw = Krita.instance().readSetting("TFM", "assets_view_mode", VIEW_THUMB)
        except Exception:
            return VIEW_THUMB
        return VIEW_LIST if raw == VIEW_LIST else VIEW_THUMB

    def _remember_view_mode(self, mode):
        try:
            Krita.instance().writeSetting("TFM", "assets_view_mode", mode)
        except Exception:
            pass

    def _icon(self, path):
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            stamp = None
        key = (path, stamp)
        cached = self._thumbs.get(key)
        if cached is not None:
            return cached
        icon = _thumbnail(path, THUMB_EDGE)
        if len(self._thumbs) > 400:
            self._thumbs.clear()
        self._thumbs[key] = icon
        return icon

    def _tip(self, path, name):
        lines = [os.path.splitext(name)[0]]
        sidecar = store.read_sidecar(path) or {}
        kind = sidecar.get("kind")
        if kind == filter_asset.KIND:
            filter_id = sidecar.get("filter") or "?"
            lines.append("Filter layer · {}".format(filter_id))
            lines.append("Saved as a filter preset (parameters included).")
        elif kind == group_asset.KIND:
            children = sidecar.get("children") or []
            lines.append("Layer group · {} item(s)".format(len(children)))
            skipped = sidecar.get("skipped") or []
            if skipped:
                lines.append("Skipped unsupported: {}".format(", ".join(skipped[:6])))
        elif kind == group_asset.PAINT_KIND:
            lines.append("Paint layer")
        else:
            size = _dimensions(path)
            if size is not None:
                lines.append("{} × {}".format(size[0], size[1]))
        masks = sidecar.get("masks") or []
        if masks:
            lines.append("Transparency mask × {}".format(len(masks)))
        meta = store.read_meta(path)
        if meta is not None:
            lines.append("Position {}, {}".format(meta[0], meta[1]))
        return "\n".join(lines)

    def _selected_rels(self):
        rels = []
        for index in range(self.grid.count()):
            item = self.grid.item(index)
            if item.isSelected():
                rel = item.data(Qt.ItemDataRole.UserRole)
                if rel:
                    rels.append(rel)
        return rels

    def _new_folder(self):
        parent = self._current_folder()
        try:
            rel = store.create_folder(self._root, parent, "New Folder")
        except store.AssetError as error:
            self._tell(str(error))
            return
        self._reload(rel)

    def _delete_folder(self):
        rel = self._current_folder()
        if not rel:
            self._set_status("Select a folder first.")
            return
        label = rel.rsplit("/", 1)[-1]
        if not self._confirm('Delete the folder "{}" and the images inside it?'.format(label)):
            return
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        try:
            store.delete_folder(self._root, rel)
        except store.AssetError as error:
            self._set_status(str(error))
            return
        self._reload(parent, status='Deleted "{}".'.format(label))

    def _delete_images(self):
        rels = self._selected_rels()
        if not rels:
            return
        if len(rels) == 1:
            label = os.path.splitext(os.path.basename(rels[0]))[0]
            message = 'Delete "{}" from the asset library?'.format(label)
        else:
            message = "Delete {} images from the asset library?".format(len(rels))
        if not self._confirm(message):
            return
        removed = 0
        for rel in rels:
            try:
                store.delete_image(self._root, rel)
                removed += 1
            except store.AssetError:
                continue
        if removed == 1:
            text = "Deleted 1 image."
        else:
            text = "Deleted {} images.".format(removed)
        self._reload(self._current_folder(), status=text)

    def _confirm(self, message):
        answer = QMessageBox.question(
            self,
            "Asset Library",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _folder_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is not None:
            self.tree.setCurrentItem(item)
        else:
            self.tree.clearSelection()
            self.tree.setCurrentItem(None)
        rel = self._current_folder()
        menu = QMenu(self)
        menu.addAction("New Folder", self._new_folder)
        rename = menu.addAction("Rename", self._begin_rename)
        delete = menu.addAction("Delete", self._delete_folder)
        rename.setEnabled(bool(rel))
        delete.setEnabled(bool(rel))
        exec_(menu, self.tree.mapToGlobal(pos))

    def _begin_rename(self):
        item = self.tree.currentItem()
        if item is None:
            return
        self.tree.editItem(item, 0)

    def _folder_renamed(self, item, column):
        if self._loading or column != 0:
            return
        rel = item.data(0, Qt.ItemDataRole.UserRole) or ""
        current = rel.rsplit("/", 1)[-1] if rel else ""
        text = item.text(0).strip()
        if not rel or not text or text == current:
            if current and item.text(0) != current:
                self._loading = True
                item.setText(0, current)
                self._loading = False
            return
        try:
            renamed = store.rename_folder(self._root, rel, text)
        except store.AssetError as error:
            self._loading = True
            item.setText(0, current)
            self._loading = False
            self._set_status(str(error))
            return
        label = renamed.rsplit("/", 1)[-1]
        if renamed == rel:
            if item.text(0) != label:
                self._loading = True
                item.setText(0, label)
                self._loading = False
            return
        QTimer.singleShot(0, lambda renamed=renamed, label=label: self._reload(
            renamed, status='Renamed to "{}".'.format(label)))

    def _need_folder(self):
        folder = self._current_folder()
        if folder:
            return folder
        QMessageBox.information(
            self,
            "Asset Library",
            "Select a folder first. Assets are stored in folders, not in the library root.",
        )
        return ""

    def _tell(self, text):
        if text:
            QMessageBox.warning(self, "Asset Library", text)

    def _active_view(self):
        try:
            window = Krita.instance().activeWindow()
            if window is None:
                return None
            return window.activeView()
        except Exception:
            return None

    def _host(self):
        try:
            window = Krita.instance().activeWindow()
            if window is None:
                return None
            return window.qwindow()
        except Exception:
            return None

    def _image_menu(self, pos):
        item = self.grid.itemAt(pos)
        if item is not None and not item.isSelected():
            self.grid.clearSelection()
            item.setSelected(True)
            self.grid.setCurrentItem(item)
        rels = self._selected_rels()
        menu = QMenu(self)
        save = menu.addAction("Save Asset", self._save_active_asset)
        insert = menu.addAction("Insert", self._insert_selected)
        reference = menu.addAction("Place as Reference", self._insert_selected_as_reference)
        rename = menu.addAction("Rename", self._begin_image_rename)
        delete = menu.addAction("Delete", self._delete_images)
        insert.setEnabled(bool(rels))
        reference.setEnabled(bool(rels))
        rename.setEnabled(len(rels) == 1)
        delete.setEnabled(bool(rels))
        del save
        exec_(menu, self.grid.mapToGlobal(pos))

    def _begin_image_rename(self):
        item = self.grid.currentItem()
        if item is None:
            return
        self.grid.editItem(item)

    def _image_renamed(self, item):
        if self._loading or item is None:
            return
        rel = item.data(Qt.ItemDataRole.UserRole) or ""
        current = os.path.splitext(os.path.basename(rel))[0] if rel else ""
        text = item.text().strip()
        if not rel or not text or text == current:
            if current and item.text() != current:
                self._loading = True
                item.setText(current)
                self._loading = False
            return
        try:
            renamed = store.rename_image(self._root, rel, text)
        except store.AssetError as error:
            self._loading = True
            item.setText(current)
            self._loading = False
            self._tell(str(error))
            return
        label = os.path.splitext(os.path.basename(renamed))[0]
        if renamed == rel:
            if item.text() != label:
                self._loading = True
                item.setText(label)
                self._loading = False
            return
        QTimer.singleShot(0, lambda renamed=renamed: self._reload(
            self._current_folder(), renamed))

    def _invert_transform(self, transform):
        inverted = transform.inverted()
        if isinstance(inverted, tuple):
            matrix, ok = inverted
            if not ok:
                raise ValueError("transform")
            return matrix
        return inverted

    def _widget_to_image(self, view, point):
        local = QPointF(point.x(), point.y())
        flake = self._invert_transform(view.flakeToCanvasTransform()).map(local)
        image = view.flakeToImageTransform().map(flake)
        return image.x(), image.y()

    def _drop_on_canvas(self, widget, local, mime):
        rels = asset_paths(mime)
        if not rels:
            return
        point = _canvas_local_point(widget, local)
        view = self._active_view()
        if view is None:
            self._tell("Open a document first.")
            return
        try:
            center = self._widget_to_image(view, point)
        except Exception:
            try:
                middle = view.canvas().preferredCenter()
                center = (middle.x(), middle.y())
            except Exception:
                self._tell("Could not place that image on the canvas.")
                return
        self._insert_rels(rels, center)

    def _insert_selected(self):
        self._insert_rels(self._selected_rels(), None, "paint")

    def _insert_selected_as_reference(self):
        self._insert_rels(self._selected_rels(), None, "reference")

    def _insert_image_item(self, item):
        rel = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if rel:
            self._insert_rels([rel], None, "paint")

    def _insert_rels(self, rels, center, mode="paint"):
        if not rels:
            self._tell("Select an image first.")
            return
        doc = self._document()
        if doc is None:
            self._tell("Open a document first.")
            return
        view = self._active_view()
        try:
            with _wait_cursor():
                for index, rel in enumerate(rels):
                    point = None if center is None else (center[0] + index * 16, center[1] + index * 16)
                    self._insert_one(doc, view, rel, mode, point)
        except store.AssetError as error:
            self._tell(str(error))
            return
        except Exception:
            self._tell("Could not insert that image.")
            return
        try:
            doc.refreshProjection()
            doc.waitForDone()
            doc.setModified(True)
        except Exception:
            pass

    def _insert_one(self, doc, view, rel, mode, center):
        path = store.image_path(self._root, rel)
        name = os.path.splitext(os.path.basename(path))[0]
        size = _dimensions(path)
        image = QImage(path)
        if size is None and not image.isNull():
            size = (image.width(), image.height())
        width = size[0] if size else 0
        height = size[1] if size else 0
        x, y = self._top_left(doc, view, width, height, center)
        if mode == "reference":
            self._insert_reference(path, x, y)
            return
        parent, above = _insertion_point(doc)
        if parent is None:
            raise store.AssetError("Open a document first.")
        sidecar = store.read_sidecar(path) or {}
        kind = sidecar.get("kind")
        if kind == filter_asset.KIND:
            node = filter_asset.create_layer(doc, name, sidecar, parent, above)
            try:
                doc.setActiveNode(node)
            except Exception:
                pass
            return
        if kind == group_asset.KIND:
            node = group_asset.create_layer(doc, name, sidecar, parent, above)
            try:
                doc.setActiveNode(node)
            except Exception:
                pass
            return
        if kind == group_asset.PAINT_KIND:
            node = group_asset.create_paint_layer(doc, name, sidecar, parent, above)
            try:
                doc.setActiveNode(node)
            except Exception:
                pass
            return
        if not self._can_bake(doc, path):
            raise store.AssetError("That image can only be placed in an RGBA 8-bit or 16-bit document.")
        if image.isNull():
            image = QImage(path)
        if image.isNull():
            raise store.AssetError("Could not read that image.")
        if width * height > MAX_BAKE_PIXELS:
            raise store.AssetError("That image is too large to place as a paint layer.")
        payload = pixels.paint_bytes(image, doc.colorDepth())
        if not payload or payload[1] < 1:
            raise store.AssetError("Could not write the image into a layer.")
        raw, width, height = payload
        x, y = self._top_left(doc, view, width, height, center)
        node = doc.createNode(name, "paintlayer")
        if node is None:
            raise store.AssetError("Could not create a paint layer.")
        if not node.setPixelData(pixels.qbytearray_from(raw), x, y, width, height):
            raise store.AssetError("Could not write the image into a layer.")
        if not parent.addChildNode(node, above):
            raise store.AssetError("Could not add the layer.")
        try:
            doc.setActiveNode(node)
        except Exception:
            pass

    def _top_left(self, doc, view, width, height, center):
        if center is not None:
            return int(round(center[0] - width / 2.0)), int(round(center[1] - height / 2.0))
        try:
            if view is not None:
                middle = view.canvas().preferredCenter()
                return int(round(middle.x() - width / 2.0)), int(round(middle.y() - height / 2.0))
        except Exception:
            pass
        return (doc.width() - width) // 2, (doc.height() - height) // 2

    def _insert_reference(self, path, x, y):
        image = QImage(path)
        if image.isNull():
            raise store.AssetError("Could not read that image.")
        QApplication.clipboard().setImage(image)
        host = self._host()
        tool = self._reference_tool(host)
        if tool is None:
            raise store.AssetError("Could not create a reference image.")
        QtCore.QMetaObject.invokeMethod(tool, "pasteReferenceImage")
        self._move_reference(host, x, y)
        QTimer.singleShot(0, lambda host=host, x=x, y=y: self._move_reference(host, x, y))

    def _reference_tool(self, host):
        tool = self._find_reference_tool(host)
        if tool is not None:
            return tool
        app = Krita.instance()
        for name in ("ToolReferenceImages", "KritaShape/ToolReferenceImages"):
            try:
                action = app.action(name)
            except Exception:
                action = None
            if action is not None:
                action.trigger()
                break
        return self._find_reference_tool(host)

    def _find_reference_tool(self, host):
        if host is None:
            return None
        try:
            found = host.findChildren(QObject, "ToolReferenceImages")
        except Exception:
            return None
        return found[0] if found else None

    def _move_reference(self, host, x, y):
        view = self._active_view()
        if host is None or view is None:
            return
        try:
            image = QPointF(x, y)
            flake = self._invert_transform(view.flakeToImageTransform()).map(image)
            document = view.flakeToDocumentTransform().map(flake)
        except Exception:
            return
        xbox = host.findChild(QtWidgets.QWidget, "positionXSpinBox")
        ybox = host.findChild(QtWidgets.QWidget, "positionYSpinBox")
        if xbox is None or ybox is None:
            return
        for box, value in ((xbox, document.x()), (ybox, document.y())):
            changer = getattr(box, "changeValue", None)
            if changer is not None:
                changer(float(value))
            else:
                box.setValue(float(value))

    def _can_bake(self, doc, path):
        try:
            model = doc.colorModel()
            depth = doc.colorDepth()
        except Exception:
            return False
        if model != "RGBA" or depth not in ("U8", "U16"):
            return False
        size = _dimensions(path)
        if size is None:
            return True
        return size[0] * size[1] <= MAX_BAKE_PIXELS

    def _drop_on_folder(self, folder, mime):
        kind = drop_kind(mime)
        if kind == "folder":
            self._move_dropped_folder(folder, mime)
            return
        if not folder:
            self._need_folder()
            return
        if kind == "asset":
            self._move_asset_items(folder, mime)
        elif kind == "files":
            self._import_paths(folder, _local_images(mime))
        elif kind == "image":
            self._save_dropped_image(folder, mime)

    def _save_active_asset(self):
        folder = self._need_folder()
        if not folder:
            return
        doc = self._document()
        if doc is None:
            self._tell("Open a document first.")
            return
        try:
            node = doc.activeNode()
        except Exception:
            node = None
        if node is None:
            self._tell("Select a layer first.")
            return
        if filter_asset.is_filter_layer(node):
            self._persist_structured_asset(
                folder, node, doc, filter_asset.capture, filter_asset.preview_image, "Filter")
            return
        if group_asset.is_group_layer(node):
            self._persist_structured_asset(
                folder,
                node,
                doc,
                lambda current, document=doc: group_asset.capture(
                    current, document, pixel_budget=MAX_BAKE_PIXELS),
                group_asset.preview_image,
                "Group",
            )
            return
        if mask_asset.has_transparency_mask(node):
            self._persist_structured_asset(
                folder,
                node,
                doc,
                lambda current, document=doc: group_asset.capture_paint(
                    current, document, pixel_budget=MAX_BAKE_PIXELS),
                lambda current, edge=THUMB_EDGE: filter_asset.preview_image(current, edge),
                "Layer",
            )
            return
        try:
            bounds = node.bounds()
        except Exception:
            self._tell("This layer cannot be saved.")
            return
        if bounds.isEmpty() or bounds.width() < 1 or bounds.height() < 1:
            self._tell("The active layer has no pixels to save.")
            return
        try:
            path = store.new_image_path(self._root, folder, node.name() or "Layer")
        except store.AssetError as error:
            self._tell(str(error))
            return
        try:
            with _wait_cursor():
                image = _projection_image(node, doc, bounds)
                if image is not None:
                    write_png(image, path)
                else:
                    saved = node.save(path, doc.xRes() or 1.0, doc.yRes() or 1.0, InfoObject(), bounds)
                    if not saved:
                        raise store.AssetError("Krita could not export this layer.")
        except store.AssetError as error:
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            self._tell(str(error))
            return
        except Exception:
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            self._tell("Krita could not export this layer.")
            return
        try:
            store.write_meta(path, bounds.x(), bounds.y())
        except (OSError, ValueError, store.AssetError):
            pass
        rel = store.relative_path(self._root, path)
        self._reload(folder, rel)

    def _persist_structured_asset(self, folder, node, doc, capture, preview, fallback_name):
        try:
            payload = capture(node)
        except store.AssetError as error:
            self._tell(str(error))
            return
        try:
            path = store.new_image_path(self._root, folder, node.name() or fallback_name)
        except store.AssetError as error:
            self._tell(str(error))
            return
        try:
            with _wait_cursor():
                image = preview(node, THUMB_EDGE)
                try:
                    bounds = node.bounds()
                except Exception:
                    bounds = None
                if (
                    bounds is not None
                    and not bounds.isEmpty()
                    and bounds.width() >= 1
                    and bounds.height() >= 1
                    and bounds.width() * bounds.height() <= MAX_BAKE_PIXELS
                ):
                    projection = _projection_image(node, doc, bounds)
                    if projection is not None and not projection.isNull():
                        image = projection
                write_png(image, path)
                store.write_sidecar(path, payload)
        except store.AssetError as error:
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            self._tell(str(error))
            return
        except Exception:
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            sidecar = path + ".json"
            if os.path.isfile(sidecar):
                try:
                    os.remove(sidecar)
                except OSError:
                    pass
            self._tell("Could not save that layer.")
            return
        rel = store.relative_path(self._root, path)
        self._reload(folder, rel)

    def _move_dropped_folder(self, dest, mime):
        rel = folder_rel_from_mime(mime)
        if not rel:
            self._set_status("That folder is not in the asset library.")
            return
        try:
            moved = store.move_folder(self._root, rel, dest)
        except store.AssetError as error:
            self._set_status(str(error))
            return
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        if moved == rel and parent == (dest or ""):
            self._set_status("Nothing was moved.")
            return
        self._note_change(moved, status='Moved "{}".'.format(moved.rsplit("/", 1)[-1]))

    def _move_asset_items(self, folder, mime):
        moved = 0
        last = None
        for rel in asset_paths(mime):
            current = rel.rsplit("/", 1)[0] if "/" in rel else ""
            if current == (folder or ""):
                continue
            try:
                last = store.move_image(self._root, rel, folder)
                moved += 1
            except store.AssetError:
                continue
        if not moved:
            self._set_status("Nothing was moved.")
            return
        text = "Moved 1 image." if moved == 1 else "Moved {} images.".format(moved)
        self._note_change(folder, last, text)

    def _import_paths(self, folder, paths):
        saved = []
        with _wait_cursor():
            for path in paths:
                try:
                    saved.append(store.import_file(self._root, folder, path))
                except store.AssetError:
                    continue
        if not saved:
            self._set_status("No images were imported.")
            return
        text = "Imported 1 image." if len(saved) == 1 else "Imported {} images.".format(len(saved))
        self._note_change(folder, saved[-1], text)

    def _save_dropped_image(self, folder, mime):
        doc = self._document()
        if (
            mime is not None
            and mime.hasFormat("application/x-krita-node-internal-pointer")
            and doc is not None
        ):
            try:
                node = doc.activeNode()
            except Exception:
                node = None
            if filter_asset.is_filter_layer(node):
                self._persist_structured_asset(
                    folder, node, doc, filter_asset.capture, filter_asset.preview_image, "Filter")
                return
            if group_asset.is_group_layer(node):
                self._persist_structured_asset(
                    folder,
                    node,
                    doc,
                    lambda current, document=doc: group_asset.capture(
                        current, document, pixel_budget=MAX_BAKE_PIXELS),
                    group_asset.preview_image,
                    "Group",
                )
                return
            if mask_asset.has_transparency_mask(node):
                self._persist_structured_asset(
                    folder,
                    node,
                    doc,
                    lambda current, document=doc: group_asset.capture_paint(
                        current, document, pixel_budget=MAX_BAKE_PIXELS),
                    lambda current, edge=THUMB_EDGE: filter_asset.preview_image(current, edge),
                    "Layer",
                )
                return
        try:
            with _wait_cursor():
                image = image_from_mime(mime)
                path = store.new_image_path(self._root, folder, "Layer")
                write_png(image, path)
        except store.AssetError as error:
            self._set_status(str(error))
            return
        except Exception:
            self._set_status("Could not save that image.")
            return
        rel = store.relative_path(self._root, path)
        label = os.path.splitext(os.path.basename(path))[0]
        self._note_change(
            folder,
            rel,
            'Saved "{}". Inserting it will center the image.'.format(label),
        )

    def _start_drag(self):
        rels = self._selected_rels()
        if not rels:
            return
        paths = []
        for rel in rels:
            try:
                paths.append(store.image_path(self._root, rel))
            except store.AssetError:
                continue
        if not paths:
            return
        mime = QMimeData()
        mime.setData(ASSET_MIME, QByteArray(json.dumps({"paths": rels}).encode("utf-8")))
        mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
        image = QImage(paths[0])
        if not image.isNull():
            mime.setImageData(image)
        drag = QDrag(self.grid)
        drag.setMimeData(mime)
        icon = self.grid.currentItem().icon() if self.grid.currentItem() is not None else QIcon()
        pixmap = icon.pixmap(72, 72)
        if not pixmap.isNull():
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(12, 12))
        self._dragging = True
        try:
            _run_drag(drag)
        finally:
            self._dragging = False
            pending = self._pending
            self._pending = None
            if pending is not None:
                self._reload(*pending)

    def _start_folder_drag(self):
        rel = self._current_folder()
        if not rel:
            return
        mime = QMimeData()
        mime.setData(FOLDER_MIME, QByteArray(json.dumps({"path": rel}).encode("utf-8")))
        drag = QDrag(self.tree)
        drag.setMimeData(mime)
        label = rel.rsplit("/", 1)[-1]
        pixmap = QPixmap(168, 28)
        pixmap.fill(QColor(48, 48, 48))
        painter = QPainter(pixmap)
        try:
            painter.setPen(QColor(235, 235, 235))
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, label)
        finally:
            painter.end()
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(12, 14))
        self._dragging = True
        try:
            _run_drag(drag)
        finally:
            self._dragging = False
            self.tree.forget_highlight()
            pending = self._pending
            self._pending = None
            if pending is not None:
                self._reload(*pending)


def register_assets(app):
    app.addDockWidgetFactory(
        DockWidgetFactory("tfm_assets", DockWidgetFactoryBase.DockRight, AssetLibraryDocker)
    )
