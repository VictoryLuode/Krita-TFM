"""TFM multi-list menu editor dialog.

Supports nested menus, custom-named commands. Provides
a live Current Menu list, shortcut conflict detection, and config export/import.
"""

import copy
import json
import os
import sys

from krita import Krita, Palette

from .qtcompat import (
    PYQT6,
    QAbstractItemView,
    QApplication,
    QBrush,
    QCheckBox,
    QColor,
    QComboBox,
    QDesktopServices,
    QDialog,
    QEvent,
    QFileDialog,
    QFont,
    QGroupBox,
    QHBoxLayout,
    QIcon,
    QInputDialog,
    QKeySequence,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QByteArray,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QMimeData,
    QPalette,
    QPixmap,
    QPlainTextEdit,
    QPushButton,
    QRect,
    QSize,
    QStandardPaths,
    QStyle,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
    QUrl,
    QVBoxLayout,
    QWidget,
    Qt,
    exec_,
)

from ..i18n import tr
from ..ui_chrome import (
    apply_warning_label,
    icon_tool_button,
    make_empty_state,
    position_empty_state,
    sync_empty_state,
)
from .version import __version__
from .config import (
    BRUSH_BLEND_MODES,
    BRUSH_VALUES,
    LAYER_BLEND_MODES,
    SCRIPTS_DIR,
    SCRIPT_TEMPLATE,
    add_overrides,
    build_config_dict,
    catalog_actions,
    delete_script,
    ensure_scripts_dir,
    list_scripts,
    load_action_categories,
    load_config,
    load_overrides,
    notify_refresh,
    parse_config_dict,
    pop_overrides,
    read_script,
    script_path,
    SCRIPTS_DIR,
    rename_script,
    run_script,
    save_config,
    script_filename,
    write_script,
    _RESOURCE_ROOT,
)
from .shortcuts import find_shortcut_file, parse_entries, read_text, set_entries, UNBOUND
from .shortcuts import restore as restore_shortcuts
from .shortcuts import unbind
from .editor_widgets import *  # noqa: F403


__all__ = [name for name in globals() if not name.startswith("__")]
