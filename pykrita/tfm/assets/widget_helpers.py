"""Shared Asset Library widget helpers and constants."""


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
__all__ = [name for name in list(globals()) if not name.startswith("__")]
