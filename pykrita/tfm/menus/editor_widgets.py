"""Menu editor helpers and widgets used by ListMenuDialog."""


import json
import os
import sqlite3
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

MIME_MENU_ITEM = "application/x-tfm-menu-item"


def _event_pos(event):
    position = getattr(event, "position", None)
    if position is not None:
        try:
            return position().toPoint()
        except (AttributeError, TypeError):
            pass
    return event.pos()

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

ROLE_INDEX = Qt.ItemDataRole.UserRole
ROLE_TOKEN = Qt.ItemDataRole.UserRole + 1
ROLE_TYPE = Qt.ItemDataRole.UserRole + 2
ROLE_CHECKED = Qt.ItemDataRole.UserRole + 3
TYPE_CMD = "cmd"
TYPE_MENU = "menu"
TYPE_BLEND = "blend"
TYPE_CAT = "category"
TYPE_BRUSH = "brush"
TYPE_BBLEND = "bblend"
TYPE_BVAL = "bval"
TYPE_COLOR = "color"
TYPE_SEP = "sep"
TYPE_HEADER = "header"
TYPE_TOGGLE = "toggle"
TYPE_SCRIPT = "script"


def _load_preset_tags():
    """Return (sorted_tag_names, {preset_name: frozenset(tag_names)}) for Krita
    brush presets, read from Krita's resourcecache.sqlite.

    The libkis library API exposes no Resource.tags(), so we read Krita's own
    resource DB (the cache the app maintains) to map preset names to tags.
    resource_type_id 5 == 'paintoppresets'. Returns ([], {}) on any error.
    """
    try:
        db = os.path.join(_RESOURCE_ROOT, "resourcecache.sqlite")
        if not os.path.exists(db):
            return [], {}
        con = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
        try:
            tags = set()
            mapping = {}
            cur = con.execute(
                "select r.name, t.name from resources r "
                "join resource_tags rt on rt.resource_id = r.id and rt.active = 1 "
                "join tags t on t.id = rt.tag_id and t.active = 1 "
                "where r.resource_type_id = 5")
            for name, tag in cur:
                if not name:
                    continue
                tags.add(tag)
                mapping.setdefault(name, set()).add(tag)
        finally:
            con.close()
        return sorted(tags, key=lambda s: s.lower()), \
               {k: frozenset(v) for k, v in mapping.items()}
    except Exception:
        return [], {}


class AddSource:
    """A pluggable source of items for the 'Add items' pane.

    To add a future source (colour swatches, submenu templates, placeholders, ...),
    append an AddSource(...) to ADD_SOURCES with its own item_type, enum_fn, add_fn.
    Nothing else in the dialog needs to change.
    """

    def __init__(self, key, label, item_type, enum_fn, add_fn):
        self.key = key
        self.label = label
        self.item_type = item_type
        self.enum_fn = enum_fn     # (dlg, needle) -> iterable of (payload, display_text)
        self.add_fn = add_fn       # (dlg, payload) -> None  (appends to current menu)


def _enum_actions(dlg, needle):
    existing = dlg._existing_cmd_ids()
    for action_id, text in dlg._catalog.items():
        if needle and needle not in text.lower() and needle not in action_id.lower():
            continue
        if action_id in existing:
            continue
        yield (action_id, text)


def _add_action(dlg, payload):
    action_id = payload
    if action_id not in dlg._existing_cmd_ids():
        dlg._cur_items().append({"id": action_id, "label": ""})
        dlg._render_items()


def _enum_blend(dlg, needle):
    existing = {it.get("blend") for it in dlg._cur_items()
                if isinstance(it, dict) and it.get("blend")}
    for oid, label in LAYER_BLEND_MODES:
        if needle and needle not in label.lower() and needle not in oid.lower():
            continue
        if oid in existing:
            continue
        yield (oid, label)


def _add_blend(dlg, payload):
    oid = payload
    existing = {it.get("blend") for it in dlg._cur_items()
                if isinstance(it, dict) and it.get("blend")}
    if oid not in existing:
        dlg._cur_items().append({"blend": oid, "label": dict(LAYER_BLEND_MODES).get(oid, oid)})
        dlg._render_items()


def _enum_brush_blend(dlg, needle):
    existing = {it.get("bblend") for it in dlg._cur_items()
                if isinstance(it, dict) and it.get("bblend")}
    for oid, label in BRUSH_BLEND_MODES:
        if needle and needle not in label.lower() and needle not in oid.lower():
            continue
        if oid in existing:
            continue
        yield (oid, label)


def _add_brush_blend(dlg, payload):
    oid = payload
    existing = {it.get("bblend") for it in dlg._cur_items()
                if isinstance(it, dict) and it.get("bblend")}
    if oid not in existing:
        dlg._cur_items().append({"bblend": oid,
                                 "label": dict(BRUSH_BLEND_MODES).get(oid, oid)})
        dlg._render_items()


def _enum_brush_values(dlg, needle):
    existing = {it.get("bval") for it in dlg._cur_items()
                if isinstance(it, dict) and it.get("bval")}
    for spec, label in BRUSH_VALUES:
        if needle and needle not in label.lower() and needle not in spec.lower():
            continue
        if spec in existing:
            continue
        yield (spec, label)


def _add_brush_value(dlg, payload):
    spec = payload
    existing = {it.get("bval") for it in dlg._cur_items()
                if isinstance(it, dict) and it.get("bval")}
    if spec in existing:
        return
    dlg._cur_items().append({"bval": spec,
                             "label": dict(BRUSH_VALUES).get(spec, spec)})
    dlg._render_items()


def _add_color(dlg, payload):
    if payload.startswith("fg:") or payload.startswith("bg:"):
        target, hexc = payload.split(":", 1)
        _append_color(dlg, hexc, target)


def _append_color(dlg, hexc, target):
    existing = {it.get("color") + ":" + it.get("target", "fg")
                for it in dlg._cur_items()
                if isinstance(it, dict) and it.get("color")}
    key = hexc + ":" + target
    if key in existing:
        return
    label = "%s (%s)" % (hexc, "Fg" if target == "fg" else "Bg")
    dlg._cur_items().append({"color": hexc, "target": target, "label": label})
    dlg._render_items()


def _enum_palettes(dlg, needle):
    # The palette source renders a palette -> colors tree in _reload_available;
    # this enum is a no-op placeholder required by the AddSource signature.
    return iter(())


def _enum_brushes(dlg, needle):
    existing = {it.get("brush") for it in dlg._cur_items()
                if isinstance(it, dict) and it.get("brush")}
    try:
        presets = Krita.instance().resources("preset")
    except Exception:
        return
    for name in presets:
        if needle and needle not in name.lower():
            continue
        if name in existing:
            continue
        yield (name, name)


def _add_brush(dlg, payload):
    name = payload
    existing = {it.get("brush") for it in dlg._cur_items()
                if isinstance(it, dict) and it.get("brush")}
    if name in existing:
        return
    dlg._cur_items().append({"brush": name, "label": name})
    dlg._render_items()


# Order = order shown in the "Add items" combo. Append new sources here to extend.
def _script_label(filename):
    """Default menu label for a library script (its file stem)."""
    return os.path.splitext(filename or "")[0]


def _enum_scripts(dlg, needle):
    existing = {it.get("script") for it in dlg._cur_items()
                if isinstance(it, dict) and it.get("script")}
    for filename, label in list_scripts():
        if needle and needle not in label.lower() and needle not in filename.lower():
            continue
        if filename in existing:
            continue
        yield (filename, label)


def _add_script(dlg, payload):
    filename = script_filename(payload)
    if not filename:
        return
    existing = {it.get("script") for it in dlg._cur_items()
                if isinstance(it, dict) and it.get("script")}
    if filename in existing:
        return
    dlg._cur_items().append({"script": filename, "label": ""})
    dlg._render_items()


ADD_SOURCES = [
    AddSource("actions", "Krita Actions", TYPE_CMD, _enum_actions, _add_action),
    AddSource("blend", "Layer Blend Mode", TYPE_BLEND, _enum_blend, _add_blend),
    AddSource("bblend", "Brush Blend Mode", TYPE_BBLEND, _enum_brush_blend, _add_brush_blend),
    AddSource("bval", "Brush Value", TYPE_BVAL, _enum_brush_values, _add_brush_value),
    AddSource("palette", "Krita Palettes", TYPE_COLOR, _enum_palettes, _add_color),
    AddSource("brush", "Brushes", TYPE_BRUSH, _enum_brushes, _add_brush),
    AddSource("script", "Scripts", TYPE_SCRIPT, _enum_scripts, _add_script),
]


class _MenuItemDelegate(QStyledItemDelegate):
    """Paints the Current Menu list exactly like the popup list menu (icon column,
    30px rows, separators, headers, checkable toggles) so the editor mirrors the
    real menu. Drawing it ourselves (not the default QListWidgetItem style) lets
    us match the popup's geometry and colours while keeping click/drag behaviour."""

    HEIGHT = 32
    ICON_X = 10
    ICON_SIZE = 20
    TEXT_X = 40

    def sizeHint(self, option, index):
        typ = index.data(ROLE_TYPE)
        h = 8 if typ == TYPE_SEP else self.HEIGHT
        return QSize(300, h)

    def paint(self, p, option, index):
        typ = index.data(ROLE_TYPE)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        checked = bool(index.data(ROLE_CHECKED))
        is_sel = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if is_sel:
            p.fillRect(option.rect, QColor(61, 61, 61))
        elif is_hover:
            p.fillRect(option.rect, QColor(46, 46, 46))
        if typ == TYPE_SEP:
            p.setPen(QColor("#4a4a4a"))
            y = option.rect.center().y()
            p.drawLine(option.rect.left() + 8, y, option.rect.right() - 8, y)
            return
        if typ == TYPE_HEADER:
            color = QColor("#9a9a9a")
        elif is_sel:
            color = QColor("#ffffff")
        else:
            color = QColor("#e8e8e8")
        x = self.ICON_X
        if typ == TYPE_TOGGLE:
            box = 16
            by = option.rect.center().y() - box // 2
            p.setPen(QColor(120, 120, 120))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(x, by, box, box)
            if checked:
                p.setPen(QColor(230, 230, 230))
                p.drawLine(x + 3, by + box // 2, x + box // 2, by + box - 3)
                p.drawLine(x + box // 2, by + box - 3, x + box - 3, by + 3)
            x = self.TEXT_X
        elif icon is not None and not icon.isNull():
            pix = icon.pixmap(QSize(self.ICON_SIZE, self.ICON_SIZE))
            p.drawPixmap(x, option.rect.center().y() - self.ICON_SIZE // 2, pix)
            x = self.TEXT_X
        fm = option.fontMetrics
        p.setPen(color)
        p.drawText(QRect(x, option.rect.top(), option.rect.right() - x,
                         option.rect.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)


class _MenuItemsList(QListWidget):
    """Current-menu list: reorder, drop onto a submenu to nest, expose mime for crumbs.

    Drops must accept CopyAction (not MoveAction). We rewrite the menu data and
    rebuild the list ourselves; MoveAction would make Qt delete the source row
    again after startDrag returns, so the item vanishes until the next refresh.
    """

    def __init__(self, dialog, parent=None):
        super().__init__(parent)
        self._dialog = dialog
        self._drag_row = -1
        self._nest_highlight = None
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    def mimeTypes(self):
        return [MIME_MENU_ITEM]

    def mimeData(self, items):
        mime = QMimeData()
        if items:
            row = self.row(items[0])
            self._drag_row = row
            mime.setData(MIME_MENU_ITEM, QByteArray(str(row).encode("ascii")))
        return mime

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if item is None:
            return
        self._drag_row = self.row(item)
        # Copy only: Move makes QAbstractItemView remove the source row after drop.
        super().startDrag(Qt.DropAction.CopyAction)

    def supportedDropActions(self):
        return Qt.DropAction.CopyAction

    def _source_row(self, event):
        if self._drag_row >= 0:
            return self._drag_row
        raw = bytes(event.mimeData().data(MIME_MENU_ITEM)).decode("ascii", "ignore").strip()
        try:
            return int(raw)
        except ValueError:
            return -1

    @staticmethod
    def _nest_zone(list_widget, item, pos):
        """True when the pointer is over the middle of a submenu row (not its edges)."""
        if item is None or item.data(ROLE_TYPE) != TYPE_MENU:
            return False
        rect = list_widget.visualItemRect(item)
        if not rect.isValid():
            return False
        margin = max(6, rect.height() // 5)
        return rect.top() + margin <= pos.y() <= rect.bottom() - margin

    def _accept_copy(self, event):
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def _set_nest_highlight(self, item):
        if item is self._nest_highlight:
            return
        if self._nest_highlight is not None:
            self._nest_highlight.setBackground(QBrush())
        self._nest_highlight = item
        if item is not None:
            item.setBackground(QBrush(QColor(82, 122, 159)))

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME_MENU_ITEM):
            self._accept_copy(event)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if not event.mimeData().hasFormat(MIME_MENU_ITEM):
            self._set_nest_highlight(None)
            event.ignore()
            return
        super().dragMoveEvent(event)
        pos = _event_pos(event)
        target = self.itemAt(pos)
        self._set_nest_highlight(target if self._nest_zone(self, target, pos) else None)
        self._accept_copy(event)

    def dragLeaveEvent(self, event):
        self._set_nest_highlight(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._set_nest_highlight(None)
        if not event.mimeData().hasFormat(MIME_MENU_ITEM):
            event.ignore()
            return
        src = self._source_row(event)
        if src < 0:
            event.ignore()
            return
        pos = _event_pos(event)
        target = self.itemAt(pos)
        # Any item (command, brush, submenu, …) can drop into a submenu row.
        if (self._nest_zone(self, target, pos)
                and self._dialog._nest_item_into_submenu(src, self.row(target))):
            self._accept_copy(event)
            self._drag_row = -1
            return
        indicator = self.dropIndicatorPosition()
        if self._dialog._reorder_menu_item(src, target, indicator):
            self._accept_copy(event)
        else:
            event.ignore()
        self._drag_row = -1


class _PathCrumb(QPushButton):
    """Breadcrumb that accepts a Current Menu item drop to move it up to that level."""

    def __init__(self, dialog, depth, label, parent=None):
        super().__init__(label, parent)
        self._dialog = dialog
        self._depth = depth
        self.setFlat(True)
        self.setAcceptDrops(True)
        self.setToolTip("Click to open. Drop an item here to move it into this menu.")
        self.clicked.connect(lambda _=False: dialog._go_to_depth(depth))

    def _accept_copy(self, event):
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def _set_drop_style(self, active):
        self.setStyleSheet("font-weight: bold; text-decoration: underline;" if active else "")

    def dragEnterEvent(self, event):
        if (event.mimeData().hasFormat(MIME_MENU_ITEM)
                and self._depth < len(self._dialog.path) - 1):
            self._set_drop_style(True)
            self._accept_copy(event)
        else:
            self._set_drop_style(False)
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dragLeaveEvent(self, event):
        self._set_drop_style(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._set_drop_style(False)
        if not event.mimeData().hasFormat(MIME_MENU_ITEM):
            event.ignore()
            return
        raw = bytes(event.mimeData().data(MIME_MENU_ITEM)).decode("ascii", "ignore").strip()
        try:
            src = int(raw)
        except ValueError:
            event.ignore()
            return
        if self._dialog._move_item_to_path_depth(src, self._depth):
            self._accept_copy(event)
        else:
            event.ignore()


class _ScriptEditorDialog(QDialog):
    """Editor for one library script: name + Python code (with Save & Run)."""

    def __init__(self, parent=None, filename="", code=""):
        super().__init__(parent)
        self.setWindowTitle("TFM Script")
        self.resize(760, 520)
        root = QVBoxLayout(self)
        root.setSpacing(8)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit(os.path.splitext(filename or "")[0])
        self.name_edit.setPlaceholderText("my_script")
        name_row.addWidget(self.name_edit, 1)
        root.addLayout(name_row)

        self.code_edit = QPlainTextEdit()
        self.code_edit.setPlainText(code if code else SCRIPT_TEMPLATE)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setFixedPitch(True)
        self.code_edit.setFont(mono)
        root.addWidget(self.code_edit, 1)

        hint = QLabel("Injected into the script: krita / app (the Krita instance), "
                      "document / doc, window, view, layer / node (the active node).\n"
                      "Stored as <name>.py in the TFM script library folder.")
        hint.setWordWrap(True)
        root.addWidget(hint)

        row = QHBoxLayout()
        run_btn = QPushButton("Save && Run")
        run_btn.setToolTip("Save the file and run it once on the current document")
        run_btn.clicked.connect(self._save_and_run)
        row.addWidget(run_btn)
        row.addStretch()
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        root.addLayout(row)

    def _save(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "TFM", "Give the script a name first.")
            return ""
        fn = write_script(name, self.code_edit.toPlainText())
        if not fn:
            QMessageBox.warning(self, "TFM", "Could not write the script file.")
            return ""
        return fn

    def _save_and_run(self):
        fn = self._save()
        if fn:
            run_script(fn)

    def accept(self):
        if not self._save():
            return
        super().accept()

__all__ = [name for name in list(globals()) if not name.startswith("__")]
