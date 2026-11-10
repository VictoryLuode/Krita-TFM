"""Asset Library docker: folders on the left, reusable assets on the right."""

import json
import os
from contextlib import contextmanager

from krita import DockWidget, InfoObject, Krita

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
    QLabel,
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
from . import filter_asset, group_asset, mask_asset, pixels, store
from .widgets import *  # noqa: F403
from .thumbnails import ThumbnailService
from .metadata import asset_tooltip
from .directories import DirectoryCatalog
from ..i18n import tr
from ..ui_chrome import apply_muted_label, make_empty_state, position_empty_state, sync_empty_state


__all__ = [name for name in globals() if not name.startswith("__")]
