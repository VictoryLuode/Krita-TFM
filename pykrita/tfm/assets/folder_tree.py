"""Asset Library folder tree."""

from .widget_helpers import *  # noqa: F401,F403
try:
    from ..i18n import tr
except ImportError:
    def tr(english, chinese=None):
        return english

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
        raise store.AssetError(tr("That drop did not include an image.", "拖放内容不包含图片。"))
    if image.format() != QImage.Format.Format_ARGB32:
        image = image.convertToFormat(QImage.Format.Format_ARGB32)
    directory = os.path.dirname(path)
    fd, temporary = tempfile_png(directory)
    try:
        if not image.save(temporary, "PNG"):
            raise store.AssetError(tr("Could not save the image.", "无法保存图片。"))
        os.replace(temporary, path)
        temporary = ""
    except store.AssetError:
        raise
    except OSError as error:
        raise store.AssetError(tr("Could not save the image.", "无法保存图片。")) from error
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
        self.setRootIsDecorated(False)
        self.setItemsExpandable(False)
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
__all__ = [name for name in list(globals()) if not name.startswith("__")]
