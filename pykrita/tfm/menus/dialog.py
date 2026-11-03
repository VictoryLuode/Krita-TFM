"""MenuBelt - multi-list editor dialog.

Supports nested menus, custom-named commands. Provides
a live Current Menu list, shortcut conflict detection, and config export/import.
"""

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
        root = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", ".."))
        db = os.path.join(root, "resourcecache.sqlite")
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


class ListMenuDialog(QWidget):
    """Multi-menu editor with nested submenu navigation + a live Current Menu list."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(920, 560)

        self._catalog = dict(catalog_actions())
        self.popup_shortcut, self.lists = load_config()
        self.current = 0
        self.path = [self.lists[self.current]] if self.lists else []
        self._loading_sc = False
        self._pending_overrides = {}   # list name -> [record] to apply on accept()
        self._brush_icons = {}      # preset name -> QIcon (or None)
        self._presets = None        # cached resources("preset") dict
        self._tags_loaded = False   # lazy: brush tag filter data
        self._brush_tags = []       # sorted tag names for brush presets
        self._preset_tags = {}      # preset name -> frozenset(tag names)
        self._palette_cache = None  # lazy: {palette_name -> [(hex, name), ...]}
        self._checkable_actions = None  # lazy: [(action_id, label)] for toggle picker
        self._sources = sorted(ADD_SOURCES, key=lambda s: s.label.lower())
        self._action_categories = load_action_categories()
        catalog_ids = set(self._catalog.keys())
        self._categories = sorted({v for k, v in self._action_categories.items()
                                   if k in catalog_ids})

        self._build_ui()
        self._reload_sidebar()
        self._update_form_combo()
        self._update_show_icons_check()
        self._render_current()
        self._update_left_shortcut()
        self._update_tag_widget()
        self._reload_available()
        self._saved_menu_state = self._menu_state()

    def _menu_state(self):
        import copy
        return copy.deepcopy((self.popup_shortcut, self.lists))

    def has_unsaved_changes(self):
        return self._menu_state() != self._saved_menu_state or bool(self._pending_overrides)

    # ---------- Size (remembered) ----------
    def _apply_default_size(self):
        try:
            app = Krita.instance()
            w = app.readSetting("TFM", "dialog_width", "")
            h = app.readSetting("TFM", "dialog_height", "")
            if not (w and h):
                w = app.readSetting("menubelt", "dialog_width", "")
                h = app.readSetting("menubelt", "dialog_height", "")
            if w and h:
                self.resize(int(w), int(h))
                return
        except Exception:
            pass
        try:
            geo = QApplication.primaryScreen().availableGeometry()
            self.resize(max(920, int(geo.width() * 0.6)), max(560, int(geo.height() * 0.65)))
        except Exception:
            self.resize(980, 620)

    def _persist_size(self):
        try:
            app = Krita.instance()
            app.writeSetting("TFM", "dialog_width", str(self.width()))
            app.writeSetting("TFM", "dialog_height", str(self.height()))
        except Exception:
            pass

    def done(self, result):
        self._persist_size()
        super().done(result)

    # ---------- Shortcut conflicts / overrides ----------
    @staticmethod
    def _shortcut_file():
        """Path of Krita's kritashortcutsrc (None when it cannot be located)."""
        try:
            from .qtcompat import QStandardPaths
            qt_dirs = [QStandardPaths.writableLocation(loc) for loc in (
                QStandardPaths.StandardLocation.AppConfigLocation,
                QStandardPaths.StandardLocation.GenericConfigLocation,
                QStandardPaths.StandardLocation.AppDataLocation,
            )]
        except Exception:
            qt_dirs = []
        return find_shortcut_file(qt_dirs)

    @staticmethod
    def _action_shortcuts(action):
        """PortableText list of an action's current shortcuts."""
        out = []
        try:
            seqs = list(action.shortcuts())
        except Exception:
            seqs = []
        if not seqs:
            try:
                s = action.shortcut()
                seqs = [] if s.isEmpty() else [s]
            except Exception:
                seqs = []
        for s in seqs:
            txt = s.toString(QKeySequence.SequenceFormat.PortableText)
            if txt:
                out.append(txt)
        return out

    @staticmethod
    def _clear_action_shortcuts(action):
        """Drop every live shortcut from a Krita action (applies to the session)."""
        try:
            action.setShortcuts([])
        except Exception:
            pass
        try:
            action.setShortcut(QKeySequence())
        except Exception:
            pass

    def _conflicts_for(self, key):
        """[(kind, label, owner)] bound to `key`, excluding the list being edited."""
        out = []
        for i, lst in enumerate(self.lists):
            if i != self.current and (lst.get("shortcut") or "") == key:
                out.append(("list", lst.get("name") or "", lst))
        try:
            actions = Krita.instance().actions()
        except Exception as e:
            print("menubelt: cannot list actions: %s" % e)
            actions = []
        for a in actions:
            try:
                if key not in self._action_shortcuts(a):
                    continue
                label = (a.text() or a.objectName() or "").replace("&", "").strip()
            except RuntimeError:
                continue
            out.append(("action", label or a.objectName(), a))
        return out

    def _pending_action_ids(self):
        return {r.get("id") for recs in self._pending_overrides.values() for r in recs}

    def _ask_override(self, key, conflicts):
        """Ask whether TFM may take `key` over. True = override."""
        pending = self._pending_action_ids()
        rows = []
        for kind, label, owner in conflicts:
            if kind == "list":
                rows.append("    \u2022 %s   (another TFM menu)" % label)
            elif owner.objectName() in pending:
                rows.append("    \u2022 %s   (already being unbound)" % label)
            else:
                rows.append("    \u2022 %s" % label)
        box = QMessageBox(self)
        box.setWindowTitle("Shortcut conflict")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("\u201c%s\u201d is already taken by:" % key)
        box.setInformativeText(
            "\n".join(rows) +
            "\n\nOverride unbinds the other side automatically. A Krita action's "
            "binding is written to kritashortcutsrc as \u201cnone\u201d, so it stays "
            "unbound after a restart (use Restore in Menu Settings to get it back).")
        take = box.addButton("Override", QMessageBox.ButtonRole.AcceptRole)
        keep = box.addButton("Pick another key", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep)
        exec_(box)
        return box.clickedButton() is take

    def _apply_pending_overrides(self):
        """Do the external (Krita-side) part of the overrides accepted in this dialog."""
        if not self._pending_overrides:
            return True
        path = self._shortcut_file()
        if path is None:
            QMessageBox.warning(self, "TFM", "Krita's shortcut file location could not be found. The override was not applied.")
            return False
        try:
            original = read_text(path, strict=True)
        except OSError as error:
            QMessageBox.warning(self, "TFM", "Could not read the shortcut file: {}".format(error))
            return False
        previous = parse_entries(original)
        records = []
        for name, recs in list(self._pending_overrides.items()):
            for item in recs:
                rec = {k: v for k, v in item.items() if k != "action"}
                rec["prev_file"] = previous.get(rec["id"])
                records.append((name, rec, item.get("action")))
        # Persist the complete recovery record before touching the host.
        from . import config as menu_config
        try:
            data = menu_config._read_raw(strict=True)
        except (OSError, ValueError):
            QMessageBox.warning(self, "TFM", "Could not read the menu configuration. The override was not applied.")
            return False
        overrides = data.get("overrides")
        if not isinstance(overrides, dict):
            overrides = {}
        for name, rec, _ in records:
            history = overrides.setdefault(name or "", [])
            if not any(existing.get("id") == rec.get("id") and existing.get("key") == rec.get("key") for existing in history if isinstance(existing, dict)):
                history.append(rec)
        data["overrides"] = overrides
        if not menu_config._write_raw(data):
            return False
        if path is not None:
            target = set_entries(original, {rec["id"]: UNBOUND for _, rec, _ in records})
            if target != original:
                from . import shortcuts
                if not shortcuts.write_text(path, target):
                    return False
        for _, _, action in records:
            if action is not None:
                self._clear_action_shortcuts(action)
        self._pending_overrides = {}
        return True

    def _update_undo_button(self):
        if not hasattr(self, "undo_sc_btn"):
            return
        name = self.lists[self.current].get("name") if self.lists else None
        self.undo_sc_btn.setEnabled(bool(load_overrides().get(name or "")))

    def _restore_overrides(self):
        """Give the Krita bindings back and clear this menu's key (avoids re-colliding)."""
        if not self.lists:
            return
        name = self.lists[self.current].get("name") or ""
        records = load_overrides().get(name) or []
        if not records:
            return
        keys = sorted({r.get("key") for r in records if r.get("key")})
        if QMessageBox.question(
                self, "Restore shortcuts",
                "Give the original Krita shortcut(s) back to:\n\n    %s\n\n"
                "This also clears this menu's shortcut (%s) so the two no longer "
                "collide." % (
                    "\n    ".join("%s  \u2192  %s" % (r.get("label") or r.get("id"), r.get("key"))
                                  for r in records),
                    ", ".join(keys) or "-")
        ) != QMessageBox.StandardButton.Yes:
            return
        path = self._shortcut_file()
        if path is None:
            QMessageBox.warning(self, "TFM", "Krita's shortcut file location could not be found. Recovery records were kept.")
            return
        if not restore_shortcuts(path, {r["id"]: r.get("prev_file") for r in records}):
            QMessageBox.warning(self, "TFM", "Could not restore the shortcut file. Recovery records were kept.")
            return
        try:
            actions = {a.objectName(): a for a in Krita.instance().actions()}
        except Exception:
            actions = {}
        for r in records:
            act = actions.get(r.get("id"))
            seqs = [QKeySequence.fromString(s, QKeySequence.SequenceFormat.PortableText)
                    for s in (r.get("prev_runtime") or [])]
            if act is not None and seqs:
                try:
                    act.setShortcuts(seqs)
                except Exception as e:
                    print("menubelt: cannot restore %s: %s" % (r.get("id"), e))
        if (self.lists[self.current].get("shortcut") or "") in keys:
            self.lists[self.current]["shortcut"] = ""
            self._update_left_shortcut()
        if not save_config(self.popup_shortcut, self.lists):
            QMessageBox.warning(self, "TFM", "Shortcuts were restored, but the menu configuration could not be saved. Recovery records were kept.")
            return
        if pop_overrides(name) is None:
            QMessageBox.warning(self, "TFM", "Shortcuts and menu configuration were restored, but recovery records could not be cleared. Try Restore again.")
            return
        self._pending_overrides.pop(name, None)
        notify_refresh()
        self._update_undo_button()

    # ---------- UI ----------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        body = QHBoxLayout()
        body.setSpacing(12)

        # Left: top-level menus + per-menu popup shortcut
        left_box = QGroupBox("Menu List")
        left = QVBoxLayout(left_box)
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("menuList")
        self.sidebar.currentRowChanged.connect(self._on_switch_list)
        self.sidebar.itemChanged.connect(self._on_sidebar_item_changed)
        self.sidebar.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.sidebar.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.sidebar.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.sidebar.model().rowsMoved.connect(self._sync_lists_order)
        left.addWidget(self.sidebar)
        self.sidebar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sidebar.customContextMenuRequested.connect(self._sidebar_context_menu)
        left_box.setMinimumWidth(200)
        body.addWidget(left_box, 1)

        # Current Menu (its own panel, right of Menu List)
        current_box = QGroupBox("Current Menu")
        self.current_box = current_box
        cm = QVBoxLayout(current_box)
        header_row = QHBoxLayout()
        self.crumb_row = QHBoxLayout()
        header_row.addLayout(self.crumb_row)
        header_row.addStretch()
        cm.addLayout(header_row)
        self.items_list = _MenuItemsList(self)
        self.items_list.setObjectName("menuItems")
        self.items_list.itemDoubleClicked.connect(self._on_item_double_click)
        self.items_list.setUniformItemSizes(False)
        self.items_list.setSpacing(0)
        self.items_list.setItemDelegate(_MenuItemDelegate(self.items_list))
        cm.addWidget(self.items_list)

        # Menu settings (per-list popup behaviour)
        settings_box = QGroupBox("Menu Settings")
        st = QVBoxLayout(settings_box)
        st.setContentsMargins(8, 6, 8, 6)

        # Menu form (list / pie)
        form_row = QHBoxLayout()
        form_row.addWidget(QLabel("Menu mode:"))
        self.form_combo = QComboBox()
        self.form_combo.addItem("List", "list")
        self.form_combo.addItem("Pie", "pie")
        self.form_combo.setToolTip(
            "List: linear cursor menu.\n"
            "Pie: Blender-style radial menu (up to 8 items, submenus not shown).")
        self.form_combo.currentIndexChanged.connect(self._on_form_changed)
        form_row.addWidget(self.form_combo)
        form_row.addStretch()
        st.addLayout(form_row)

        # Show icons (Krita action icons + brush thumbnails)
        self.show_icons_check = QCheckBox("Show icons")
        self.show_icons_check.setToolTip("Display Krita action icons and brush thumbnails in this menu.")
        self.show_icons_check.toggled.connect(self._on_show_icons_changed)
        st.addWidget(self.show_icons_check)

        # Per-list popup shortcut (inside Menu Settings)
        sc_row = QHBoxLayout()
        sc_row.addWidget(QLabel("Shortcut:"))
        self.list_sc_edit = QKeySequenceEdit()
        self.list_sc_edit.setMinimumWidth(90)
        self.list_sc_edit.setToolTip(
            "Press a key combination to pop this menu at the cursor.\n"
            "If it collides with another binding you can take it over.")
        self.list_sc_edit.keySequenceChanged.connect(self._on_list_shortcut_changed)
        sc_row.addWidget(self.list_sc_edit)
        sc_clear = QPushButton("Clear")
        sc_clear.clicked.connect(self._clear_list_shortcut)
        sc_row.addWidget(sc_clear)
        self.undo_sc_btn = QPushButton("Restore")
        self.undo_sc_btn.setToolTip(
            "Give back the Krita shortcuts this menu took over\n"
            "(enabled after an override)")
        self.undo_sc_btn.clicked.connect(self._restore_overrides)
        sc_row.addWidget(self.undo_sc_btn)
        sc_row.addStretch()
        st.addLayout(sc_row)

        self.items_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.items_list.customContextMenuRequested.connect(self._items_context_menu)
        cm.addWidget(settings_box)
        body.addWidget(current_box, 2)

        # Add items (pick a Krita action or a layer blend mode to add)
        avail_box = QGroupBox("Add items")
        av = QVBoxLayout(avail_box)
        self.add_type = QComboBox()
        self.add_type.addItems([s.label for s in self._sources])
        self.add_type.currentIndexChanged.connect(lambda _i: self._on_add_type_changed())
        av.addWidget(self.add_type)
        # Tag filter row: shown only when the brush source is active.
        self.tag_widget = QWidget()
        tag_row = QHBoxLayout(self.tag_widget)
        tag_row.setContentsMargins(0, 0, 0, 0)
        tag_row.addWidget(QLabel("Tag:"))
        self.tag_filter = QComboBox()
        self.tag_filter.currentIndexChanged.connect(lambda _i: self._reload_available())
        tag_row.addWidget(self.tag_filter, 1)
        av.addWidget(self.tag_widget)
        self.tag_widget.setVisible(False)
        # Script library actions: shown only when the script source is active.
        self.script_widget = QWidget()
        scr_row = QHBoxLayout(self.script_widget)
        scr_row.setContentsMargins(0, 0, 0, 0)
        for label, slot, tip in (
                ("New…", self._new_script,
                 "Create a new script file in the library folder"),
                ("Edit…", self._edit_script,
                 "Edit the selected script file"),
                ("Rename…", self._rename_script_file,
                 "Rename the selected script file (menu items follow)"),
                ("Delete", self._delete_script_file,
                 "Delete the selected script file from the library"),
                ("Folder", self._open_scripts_folder,
                 "Open the script library folder")):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            scr_row.addWidget(b)
        scr_row.addStretch()
        av.addWidget(self.script_widget)
        self.script_widget.setVisible(False)
        search_row = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search…")
        self.search_box.textChanged.connect(self._reload_available)
        search_row.addWidget(self.search_box)
        av.addLayout(search_row)
        self.add_tree = QTreeWidget()
        self.add_tree.setHeaderHidden(True)
        self.add_tree.setIndentation(14)
        if PYQT6 and sys.platform == "win32":
            self.add_tree.collapsed.connect(self._refresh_tree_accessibility)
        self.add_tree.itemDoubleClicked.connect(self._on_tree_double_click)
        av.addWidget(self.add_tree, 1)  # tree takes the remaining space
        add_btn = QPushButton("Add")
        add_btn.setToolTip("Add the selected item (or double-click it)")
        add_btn.clicked.connect(self._add_selected)
        av.addWidget(add_btn)
        self.detail_box = QLabel()
        self.detail_box.setWordWrap(True)
        self.detail_box.setFixedHeight(104)
        self.detail_box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        av.addWidget(self.detail_box)
        self.add_tree.itemSelectionChanged.connect(self._on_avail_selection_changed)
        body.addWidget(avail_box, 2)

        root.addLayout(body)

        # Bottom: export/import + OK/Cancel
        bottom = QHBoxLayout()
        im = QPushButton("Import…")
        im.clicked.connect(self._import_config)
        bottom.addWidget(im)
        ex = QPushButton("Export…")
        ex.clicked.connect(self._export_config)
        bottom.addWidget(ex)
        bottom.addStretch()
        ok = QPushButton("Save Menus")
        ok.clicked.connect(self.save_menus)
        bottom.addWidget(ok)
        root.addLayout(bottom)

    # ---------- Current menu / path ----------
    def _cur_menu(self):
        return self.path[-1] if self.path else {"name": "", "shortcut": "", "items": []}

    def _cur_items(self):
        return self._cur_menu().get("items", [])

    def _name(self):
        return self._cur_menu().get("name", "")

    def _update_current_title(self):
        name = self._name()
        self.current_box.setTitle(("Current Menu : %s" % name) if name else "Current Menu")

    def _render_path_bar(self):
        while self.crumb_row.count():
            it = self.crumb_row.takeAt(0).widget()
            if it is not None:
                it.deleteLater()
        # Submenu navigation crumbs — only shown while inside a submenu (i>0).
        if len(self.path) > 1:
            for i, node in enumerate(self.path):
                if i > 0:
                    self.crumb_row.addWidget(QLabel("\u25b8"))
                self.crumb_row.addWidget(_PathCrumb(self, i, node.get("name", "?")))

    def _go_to_depth(self, depth):
        if 0 <= depth < len(self.path):
            self.path = self.path[: depth + 1]
            self._render_current()

    def _sidebar_context_menu(self, pos):
        item = self.sidebar.itemAt(pos)
        if item is not None:
            self.sidebar.setCurrentItem(item)
        menu = QMenu(self.sidebar)
        menu.addAction("Add", self._new_list)
        if item is not None:
            menu.addAction("Rename", self._rename_list)
            menu.addAction("Duplicate", self._duplicate_list)
            menu.addAction("Delete", self._delete_list)
        exec_(menu, self.sidebar.viewport().mapToGlobal(pos))

    def _items_context_menu(self, pos):
        entry = self.items_list.itemAt(pos)
        if entry is not None:
            self.items_list.setCurrentItem(entry)
        menu = QMenu(self.items_list)
        if self.path:
            menu.addAction("Add Submenu", self._add_submenu)
            menu.addAction("Add Header", self._add_header)
            menu.addAction("Add Separator", self._add_separator)
            menu.addAction("Add Toggle", self._add_toggle)
        if entry is not None:
            menu.addSeparator()
            if entry.data(ROLE_TYPE) == TYPE_MENU:
                menu.addAction("Open", self._enter_submenu)
                menu.addAction("Ungroup", self._ungroup_submenu)
            if entry.data(ROLE_TYPE) != TYPE_SEP:
                menu.addAction("Rename", self._rename_item)
            menu.addAction("Remove", self._remove_selected)
        if menu.actions():
            exec_(menu, self.items_list.viewport().mapToGlobal(pos))

    def _ungroup_submenu(self):
        row = self.items_list.currentRow()
        items = self._cur_items()
        if not 0 <= row < len(items):
            return
        submenu = items[row]
        if not isinstance(submenu, dict) or submenu.get("name") is None:
            return
        children = submenu.get("items")
        if not isinstance(children, list):
            return
        items[row:row + 1] = children
        self._render_items()
        if items:
            self.items_list.setCurrentRow(min(row, len(items) - 1))
        self._reload_available()

    # ---------- Sidebar / list management ----------
    def _reload_sidebar(self):
        self.sidebar.blockSignals(True)
        self.sidebar.clear()
        for lst in self.lists:
            item = QListWidgetItem(lst["name"])
            item.setData(ROLE_INDEX, lst["name"])
            active = bool(lst.get("active", True))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if active else Qt.CheckState.Unchecked)
            self.sidebar.addItem(item)
            self._style_sidebar_item(item, active)
        if 0 <= self.current < self.sidebar.count():
            self.sidebar.setCurrentRow(self.current)
        self.sidebar.blockSignals(False)

    def _style_sidebar_item(self, item, active):
        font = QFont()
        font.setItalic(not active)
        item.setFont(font)
        item.setForeground(QBrush(QColor(150, 150, 150)) if not active else QBrush())

    def _on_sidebar_item_changed(self, item):
        name = item.data(ROLE_INDEX)
        if not name:
            return
        active = (item.checkState() == Qt.CheckState.Checked)
        lst = next((l for l in self.lists if l.get("name") == name), None)
        if lst is None:
            return
        if bool(lst.get("active", True)) == active:
            return  # not a check-state change (e.g. reorder also fires itemChanged)
        lst["active"] = active
        self._style_sidebar_item(item, active)
        save_config(self.popup_shortcut, self.lists)
        notify_refresh()

    def _on_switch_list(self, row):
        if 0 <= row < len(self.lists):
            self.current = row
            self.path = [self.lists[row]]
            self._update_left_shortcut()
            self._update_form_combo()
            self._update_show_icons_check()
            self._render_current()

    def _cur_top_list(self):
        if 0 <= self.current < len(self.lists):
            return self.lists[self.current]
        return None

    def _on_form_changed(self):
        lst = self._cur_top_list()
        if lst is None:
            return
        lst["menu_mode"] = self.form_combo.currentData()
        save_config(self.popup_shortcut, self.lists)
        notify_refresh()

    def _update_form_combo(self):
        lst = self._cur_top_list()
        self.form_combo.blockSignals(True)
        if lst is None:
            self.form_combo.setEnabled(False)
            self.form_combo.blockSignals(False)
            return
        self.form_combo.setEnabled(True)
        idx = self.form_combo.findData(lst.get("menu_mode", lst.get("form", "list")))
        self.form_combo.setCurrentIndex(max(0, idx))
        self.form_combo.blockSignals(False)

    def _on_show_icons_changed(self):
        lst = self._cur_top_list()
        if lst is None:
            return
        lst["show_icons"] = self.show_icons_check.isChecked()
        save_config(self.popup_shortcut, self.lists)
        notify_refresh()

    def _update_show_icons_check(self):
        lst = self._cur_top_list()
        self.show_icons_check.blockSignals(True)
        if lst is None:
            self.show_icons_check.setEnabled(False)
            self.show_icons_check.blockSignals(False)
            return
        self.show_icons_check.setEnabled(True)
        self.show_icons_check.setChecked(bool(lst.get("show_icons", True)))
        self.show_icons_check.blockSignals(False)

    def _sync_lists_order(self, *_):
        by_name = {lst["name"]: lst for lst in self.lists}
        new_order = []
        for i in range(self.sidebar.count()):
            name = self.sidebar.item(i).data(ROLE_INDEX)
            if name in by_name:
                new_order.append(by_name[name])
        if len(new_order) == len(self.lists):
            self.lists[:] = new_order
        self.current = max(0, self.sidebar.currentRow())
        self._update_left_shortcut()

    def _new_list(self):
        name, ok = QInputDialog.getText(self, "Add", "List name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if any(item.get("name") == name for item in self.lists) or load_overrides().get(name):
            QMessageBox.warning(self, "TFM", "A menu with this name already exists.")
            return
        self.lists.append({"name": name, "shortcut": "", "items": []})
        self.current = len(self.lists) - 1
        self.path = [self.lists[self.current]]
        self._reload_sidebar()
        self._render_current()
        self._update_left_shortcut()

    def _rename_list(self):
        if not self.lists:
            return
        new_name, ok = QInputDialog.getText(
            self, "Rename List", "New name:", text=self.lists[self.current]["name"])
        if ok and new_name.strip():
            old_name = self.lists[self.current]["name"]
            new_name = new_name.strip()
            if new_name != old_name and (load_overrides().get(old_name) or load_overrides().get(new_name)):
                QMessageBox.warning(self, "TFM", "Restore the affected shortcuts before renaming this menu.")
                return
            if new_name != old_name and any(i != self.current and item.get("name") == new_name for i, item in enumerate(self.lists)):
                QMessageBox.warning(self, "TFM", "A menu with this name already exists.")
                return
            if old_name in self._pending_overrides:
                self._pending_overrides[new_name] = self._pending_overrides.pop(old_name)
            self.lists[self.current]["name"] = new_name
            self._reload_sidebar()
            self._render_path_bar()

    def _duplicate_list(self):
        if not self.lists:
            return
        src = self.lists[self.current]
        # lists are plain JSON data, so a json round-trip is a clean deep copy
        dup = json.loads(json.dumps(src))
        base = src.get("name", "Menu") + " copy"
        names = {item.get("name") for item in self.lists}
        name = base
        suffix = 2
        while name in names or load_overrides().get(name):
            name = "{} {}".format(base, suffix)
            suffix += 1
        dup["name"] = name
        dup["shortcut"] = ""
        self.lists.insert(self.current + 1, dup)
        self.current += 1
        self.path = [self.lists[self.current]]
        self._reload_sidebar()
        self._render_current()
        self._update_left_shortcut()

    def _delete_list(self):
        if not self.lists:
            return
        name = self.lists[self.current].get("name") or ""
        if load_overrides().get(name):
            QMessageBox.warning(self, "TFM", "Restore this menu's overridden shortcuts before deleting it.")
            return
        if QMessageBox.question(
                self, "Delete List",
                f"Delete the list \u201c{self.lists[self.current]['name']}\u201d?") == QMessageBox.StandardButton.Yes:
            self._pending_overrides.pop(name, None)
            self.lists.pop(self.current)
            self.current = max(0, min(self.current, len(self.lists) - 1))
            self.path = [self.lists[self.current]] if self.lists else []
            self._reload_sidebar()
            self._render_current()
            self._update_left_shortcut()

    # ---------- Shortcut ----------
    def _drop_pending(self):
        if self.lists:
            self._pending_overrides.pop(self.lists[self.current].get("name") or "", None)

    def _revert_shortcut_field(self, value):
        self._loading_sc = True
        self.list_sc_edit.setKeySequence(QKeySequence(value or ""))
        self._loading_sc = False

    def _on_list_shortcut_changed(self, seq):
        if self._loading_sc or not self.lists:
            return
        name = self.lists[self.current].get("name") or ""
        key = seq.toString(QKeySequence.SequenceFormat.PortableText)
        previous = self.lists[self.current].get("shortcut", "") or ""
        # A new key invalidates the override accepted for the previous one.
        self._pending_overrides.pop(name, None)
        if not key or key == previous:
            self.lists[self.current]["shortcut"] = key
            return
        conflicts = self._conflicts_for(key)
        if conflicts and not self._ask_override(key, conflicts):
            self._revert_shortcut_field(previous)
            return
        self.lists[self.current]["shortcut"] = key
        records = []
        for kind, label, owner in conflicts:
            if kind == "list":
                owner["shortcut"] = ""      # in-memory only: Cancel discards it
                continue
            records.append({
                "id": owner.objectName(),
                "label": label,
                "key": key,
                "prev_runtime": self._action_shortcuts(owner),
                "action": owner,            # external part is applied on accept()
            })
        if records:
            self._pending_overrides[name] = records

    def _clear_list_shortcut(self):
        if not self.lists:
            return
        self._drop_pending()
        self.lists[self.current]["shortcut"] = ""
        self._revert_shortcut_field("")

    def _update_left_shortcut(self):
        if not self.lists:
            return
        self._loading_sc = True
        self.list_sc_edit.setKeySequence(
            self.lists[self.current].get("shortcut", ""))
        self._loading_sc = False
        self._update_undo_button()

    # ---------- Current menu items ----------
    @staticmethod
    def _token_of(it):
        if isinstance(it, str):
            return it
        if isinstance(it, dict):
            if it.get("id"):
                return it["id"]
            if it.get("blend") is not None:
                return "blend:" + (it.get("blend", "") or "")
            if it.get("bblend") is not None:
                return "bblend:" + (it.get("bblend", "") or "")
            if it.get("bval") is not None:
                return "bval:" + (it.get("bval", "") or "")
            if it.get("color") is not None:
                return "color:" + (it.get("color", "") or "") + ":" + (it.get("target", "fg") or "fg")
            if it.get("sep"):
                return "sep"
            if it.get("header") is not None:
                return "header:" + (it.get("header", "") or "")
            if it.get("toggle") is not None:
                return "toggle:" + (it.get("toggle", "") or "")
            if it.get("brush") is not None:
                return "brush:" + (it.get("brush", "") or "")
            if it.get("script") is not None:
                return "script:" + (it.get("script", "") or "")
            if it.get("name") is not None:
                return it["name"]
        return None

    def _item_icon(self, it):
        """Return a QIcon for an item (action icon / brush thumb / colour swatch)."""
        if isinstance(it, str):
            aid = it
        elif isinstance(it, dict):
            if it.get("color") is not None:
                return self._color_swatch_icon(it.get("color", ""))
            if it.get("toggle") is not None:
                aid = it["toggle"]
            elif it.get("id"):
                aid = it["id"]
            elif it.get("brush") is not None:
                return self._brush_pixmap_icon(it["brush"])
            else:
                return None
        else:
            return None
        try:
            act = Krita.instance().action(aid)
            if act is not None:
                icon = act.icon()
                if not icon.isNull():
                    return icon
        except Exception:
            pass
        return None

    @staticmethod
    def _color_swatch_icon(hexc):
        try:
            pix = QPixmap(20, 20)
            pix.fill(QColor(hexc))
            return QIcon(pix)
        except Exception:
            return None

    @staticmethod
    def _swatch_to_hex(sw):
        """Convert a palette Swatch to a #rrggbb hex string (from display-ordered
        RGB components). Returns None on any error / non-RGB model."""
        try:
            mc = sw.color()
            if mc is None:
                return None
            comps = mc.componentsOrdered()
            if len(comps) < 3:
                return None
            r = int(round(max(0.0, min(1.0, comps[0])) * 255))
            g = int(round(max(0.0, min(1.0, comps[1])) * 255))
            b = int(round(max(0.0, min(1.0, comps[2])) * 255))
            return "#%02x%02x%02x" % (r, g, b)
        except Exception:
            return None

    def _ensure_palette_cache(self):
        """Build the palette -> colours cache once (avoids re-parsing every
        palette on every visit to the Krita Palettes source)."""
        if self._palette_cache is not None:
            return
        cache = {}
        try:
            pals = Krita.instance().resources("palette")
        except Exception:
            pals = {}
        for name, res in pals.items():
            try:
                pal = Palette(res)
                n = pal.numberOfEntries()
                items = []
                for i in range(n):
                    try:
                        sw = pal.entryByIndex(i)
                        if sw is None or not sw.isValid():
                            continue
                        hexc = self._swatch_to_hex(sw)
                        if not hexc:
                            continue
                        cname = (sw.name() or "").strip()
                        items.append((hexc, cname if cname else hexc))
                    except Exception:
                        continue
                if items:
                    cache[name] = items
            except Exception:
                continue
        self._palette_cache = cache

    def _populate_palette_tree(self, needle):
        """Fill the Add pane with Krita palettes -> their colours as addable
        swatches (colour items reuse the Color source's add path)."""
        self._ensure_palette_cache()
        for name, items in self._palette_cache.items():
            if needle and needle not in name.lower():
                continue
            parent = QTreeWidgetItem([name])
            parent.setData(0, ROLE_TYPE, TYPE_CAT)
            parent.setIcon(0, self._color_swatch_icon("#808080"))
            self.add_tree.addTopLevelItem(parent)
            for hexc, label in items:
                child = QTreeWidgetItem([label])
                child.setData(0, ROLE_TOKEN, "fg:" + hexc)
                child.setData(0, ROLE_TYPE, TYPE_COLOR)
                icon = self._color_swatch_icon(hexc)
                if icon is not None:
                    child.setIcon(0, icon)
                parent.addChild(child)
        self.add_tree.expandAll()

    def _get_presets(self):
        """Cached dict of all Krita brush presets (name -> Resource)."""
        if self._presets is None:
            self._presets = Krita.instance().resources("preset")
        return self._presets

    def _brush_pixmap_icon(self, name):
        if name in self._brush_icons:
            return self._brush_icons[name]
        icon = None
        try:
            presets = self._get_presets()
            resource = presets.get(name)
            if resource is None:
                for p in presets.values():
                    try:
                        if p.filename() == name:
                            resource = p
                            break
                    except Exception:
                        continue
            if resource is not None:
                img = resource.image()
                if not img.isNull():
                    icon = QIcon(QPixmap.fromImage(
                        img.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)))
        except Exception:
            icon = None
        self._brush_icons[name] = icon
        return icon

    def _render_current(self):
        self._update_current_title()
        self._render_path_bar()
        self._render_items()

    def _render_items(self):
        items = self._cur_items()
        self.items_list.clear()
        for idx, it in enumerate(items):
            token = self._token_of(it)
            typ, text = TYPE_CMD, token or "?"
            if isinstance(it, str):
                text = self._catalog.get(it, it)
            elif isinstance(it, dict):
                if it.get("id"):
                    text = it.get("label", "") or self._catalog.get(it["id"], it["id"])
                elif it.get("blend") is not None:
                    typ, text = TYPE_BLEND, it.get("label", it["blend"])
                elif it.get("bblend") is not None:
                    typ, text = TYPE_BBLEND, it.get("label", it["bblend"])
                elif it.get("brush") is not None:
                    typ, text = TYPE_BRUSH, it.get("label", it["brush"])
                elif it.get("bval") is not None:
                    typ, text = TYPE_BVAL, it.get("label", it["bval"])
                elif it.get("color") is not None:
                    typ, text = TYPE_COLOR, it.get("label", it["color"])
                elif it.get("script") is not None:
                    typ = TYPE_SCRIPT
                    fn = script_filename(it.get("script", ""))
                    text = it.get("label", "") or _script_label(fn)
                    if not os.path.exists(os.path.join(SCRIPTS_DIR, fn)):
                        text += "  (missing)"
                elif it.get("sep"):
                    typ, text = TYPE_SEP, ""
                elif it.get("header") is not None:
                    typ, text = TYPE_HEADER, it.get("label", it["header"]) or it["header"]
                elif it.get("toggle") is not None:
                    typ, text = TYPE_TOGGLE, it.get("label", it["toggle"]) or it["toggle"]
                elif it.get("name") is not None:
                    typ, text = TYPE_MENU, it["name"]
            entry = QListWidgetItem(text)
            icon = self._item_icon(it)
            if icon is not None and typ != TYPE_TOGGLE:
                entry.setIcon(icon)
            entry.setData(ROLE_INDEX, idx)
            entry.setData(ROLE_TOKEN, token)
            entry.setData(ROLE_TYPE, typ)
            if typ == TYPE_MENU:
                entry.setToolTip(
                    "%s  [%s]\nDrop items onto this row to move them into the submenu."
                    % (text, token))
            else:
                entry.setToolTip(f"{text}  [{token}]")
            if typ == TYPE_TOGGLE:
                checked = False
                try:
                    act = Krita.instance().action(it.get("toggle", ""))
                    checked = bool(act.isChecked()) if act else False
                except Exception:
                    checked = False
                entry.setData(ROLE_CHECKED, checked)
            self.items_list.addItem(entry)

    def _existing_cmd_ids(self):
        out = set()
        for it in self._cur_items():
            if isinstance(it, str):
                out.add(it)
            elif isinstance(it, dict) and it.get("id"):
                out.add(it["id"])
        return out

    def _on_avail_selection_changed(self):
        self._show_item_details(self.add_tree.currentItem())

    def _show_item_details(self, item):
        """Fill the bottom detail box with API info for the selected add item."""
        if item is None or item.data(0, ROLE_TYPE) == TYPE_CAT:
            src = self._current_source()
            if src is not None and src.key == "script":
                self.detail_box.setText(
                    "No script selected.\n"
                    "Folder: %s\n"
                    "New… creates a file there (Edit… changes it); "
                    "Add puts it into this menu." % SCRIPTS_DIR)
            else:
                self.detail_box.setText("")
            return
        src = self._current_source()
        payload = item.data(0, ROLE_TOKEN)
        if src and src.key == "actions" and payload:
            name = item.text(0)
            cat = self._action_categories.get(payload, "other")
            shortcut = ""
            try:
                act = Krita.instance().action(payload)
                if act is not None:
                    shortcut = act.shortcut().toString() or ""
            except Exception:
                pass
            lines = [
                "Krita action: %s" % name,
                "id: %s" % payload,
                "category: %s" % cat,
            ]
            if shortcut:
                lines.append("shortcut: %s" % shortcut)
            lines.append("API: Krita.instance().action('%s').trigger()" % payload)
            self.detail_box.setText("\n".join(lines))
        elif item.data(0, ROLE_TYPE) == TYPE_BLEND and payload:
            label = dict(LAYER_BLEND_MODES).get(payload, payload)
            self.detail_box.setText(
                "Layer blend mode: %s\n"
                "id: %s\n"
                "API: Krita.instance().activeDocument().activeNode()\n"
                "     .setBlendingMode('%s')" % (label, payload, payload))
        elif item.data(0, ROLE_TYPE) == TYPE_BBLEND and payload:
            label = dict(BRUSH_BLEND_MODES).get(payload, payload)
            self.detail_box.setText(
                "Brush blend mode: %s\n"
                "id: %s\n"
                "API: Krita.instance().activeWindow().activeView()\n"
                "     .setCurrentBlendingMode('%s')" % (label, payload, payload))
        elif item.data(0, ROLE_TYPE) == TYPE_SCRIPT and payload:
            path = os.path.join(SCRIPTS_DIR, script_filename(payload))
            self.detail_box.setText(
                "Script: %s\n"
                "file: %s\n"
                "status: %s\n"
                "run: exec() with krita/app, document/doc, window, view,\n"
                "     layer/node injected" % (
                    _script_label(payload), path,
                    "found" if os.path.exists(path) else "MISSING"))
        else:
            self.detail_box.setText("")

    def _current_source(self):
        idx = self.add_type.currentIndex()
        if 0 <= idx < len(self._sources):
            return self._sources[idx]
        return None

    def _ensure_tags_loaded(self):
        if not self._tags_loaded:
            self._brush_tags, self._preset_tags = _load_preset_tags()
            self._tags_loaded = True

    def _update_tag_widget(self):
        src = self._current_source()
        is_brush = src is not None and src.key == "brush"
        self.tag_widget.setVisible(is_brush)
        if not is_brush:
            return
        self._ensure_tags_loaded()
        items = ["All tags"] + self._brush_tags
        self.tag_filter.blockSignals(True)
        self.tag_filter.clear()
        self.tag_filter.addItems(items)
        self.tag_filter.blockSignals(False)

    def _on_add_type_changed(self):
        self._update_tag_widget()
        self._update_script_widget()
        self._reload_available()

    def _update_script_widget(self):
        """Show the script library actions only while the Scripts source is active."""
        src = self._current_source()
        is_script = src is not None and src.key == "script"
        if is_script:
            ensure_scripts_dir()
        self.script_widget.setVisible(is_script)

    def _refresh_tree_accessibility(self, _index):
        # Qt 6 can retain accessible cells keyed by pre-collapse visible rows.
        # UIA sibling navigation then revisits stale cells indefinitely. Setting
        # the existing root emits Qt's accessibility ModelReset without clearing
        # the model, selection or expansion state. Do this synchronously, before
        # Windows processes another accessibility request.
        tree = self.add_tree
        scroll = tree.verticalScrollBar().value()
        tree.setRootIndex(tree.rootIndex())
        tree.verticalScrollBar().setValue(scroll)

    def _reload_available(self):
        self.add_tree.clear()
        src = self._current_source()
        if src is None:
            return
        needle = self.search_box.text().strip().lower()
        if src.key == "actions":
            # Group by Krita's ready-made categories -> tree of category > action.
            groups = {}
            for action_id, text in src.enum_fn(self, needle):
                cat = self._action_categories.get(action_id) or "Other"
                groups.setdefault(cat, []).append((action_id, text))
            for cat in sorted(groups):
                parent = QTreeWidgetItem([cat])
                parent.setData(0, ROLE_TYPE, TYPE_CAT)
                self.add_tree.addTopLevelItem(parent)
                for action_id, text in groups[cat]:
                    leaf = QTreeWidgetItem([text])
                    leaf.setData(0, ROLE_TOKEN, action_id)
                    leaf.setData(0, ROLE_TYPE, TYPE_CMD)
                    parent.addChild(leaf)
        elif src.key == "palette":
            self._populate_palette_tree(needle)
        else:
            current_tag = None
            if src.key == "brush":
                t = self.tag_filter.currentText()
                current_tag = t if (t and t != "All tags") else None
                if current_tag is not None:
                    self._ensure_tags_loaded()
            for payload, text in src.enum_fn(self, needle):
                if src.key == "brush" and current_tag is not None:
                    tags = self._preset_tags.get(payload)
                    if not tags or current_tag not in tags:
                        continue
                leaf = QTreeWidgetItem([text])
                leaf.setData(0, ROLE_TOKEN, payload)
                leaf.setData(0, ROLE_TYPE, src.item_type)
                if src.key == "brush":
                    icon = self._brush_pixmap_icon(payload)
                    if icon is not None:
                        leaf.setIcon(0, icon)
                self.add_tree.addTopLevelItem(leaf)
        self.add_tree.expandAll()

    def _nest_item_into_submenu(self, src_row, dest_row):
        """Move the item at src_row into the submenu at dest_row. True on success."""
        items = self._cur_items()
        if not (0 <= src_row < len(items) and 0 <= dest_row < len(items)):
            return False
        if src_row == dest_row:
            return False
        dest = items[dest_row]
        if not isinstance(dest, dict) or dest.get("name") is None:
            return False
        item = items.pop(src_row)
        if src_row < dest_row:
            dest_row -= 1
        dest = items[dest_row]
        children = dest.setdefault("items", [])
        if not isinstance(children, list):
            dest["items"] = children = []
        children.append(item)
        self._render_items()
        self._reload_available()
        return True

    def _reorder_menu_item(self, src_row, target_item, indicator):
        """Reorder within the current menu from a custom drag drop. True on success."""
        items = self._cur_items()
        n = len(items)
        if not 0 <= src_row < n:
            return False
        on_item = QAbstractItemView.DropIndicatorPosition.OnItem
        above = QAbstractItemView.DropIndicatorPosition.AboveItem
        below = QAbstractItemView.DropIndicatorPosition.BelowItem
        if target_item is None:
            dest = n
        else:
            dest = self.items_list.row(target_item)
            if indicator == below or indicator == on_item:
                dest += 1
            elif indicator != above:
                dest = n
        if dest > src_row:
            dest -= 1
        if dest == src_row:
            return True
        item = items.pop(src_row)
        items.insert(dest, item)
        self._render_items()
        self.items_list.setCurrentRow(dest)
        return True

    def _move_item_to_path_depth(self, src_row, depth):
        """Move an item from the current submenu up into path[depth]. True on success."""
        if not (0 <= depth < len(self.path) - 1):
            return False
        items = self._cur_items()
        if not 0 <= src_row < len(items):
            return False
        item = items.pop(src_row)
        parent_items = self.path[depth].setdefault("items", [])
        if not isinstance(parent_items, list):
            self.path[depth]["items"] = parent_items = []
        child = self.path[depth + 1]
        try:
            insert_at = parent_items.index(child)
        except ValueError:
            insert_at = len(parent_items)
        parent_items.insert(insert_at, item)
        self._render_items()
        self._reload_available()
        return True

    def _on_item_double_click(self, *_):
        entry = self.items_list.currentItem()
        if entry is None:
            return
        if entry.data(ROLE_TYPE) == TYPE_MENU:
            self._enter_submenu()
        else:
            self._rename_item()

    def _enter_submenu(self):
        idx = self.items_list.currentRow()
        if idx < 0 or not self._cur_items():
            return
        it = self._cur_items()[idx]
        if isinstance(it, dict) and it.get("name") is not None:
            self.path.append(it)
            self._render_current()

    def _add_selected(self):
        entry = self.add_tree.currentItem()
        if entry is None or not self.path:
            return
        # Category headers are not addable.
        if entry.data(0, ROLE_TYPE) == TYPE_CAT:
            return
        src = self._current_source()
        if src is None:
            return
        src.add_fn(self, entry.data(0, ROLE_TOKEN))
        self._reload_available()  # refresh dedup after adding

    def _on_tree_double_click(self, item, _column):
        # Double-click a leaf to add it; a category header just expands/collapses.
        if item is not None and item.data(0, ROLE_TYPE) != TYPE_CAT:
            self._add_selected()

    # ---------- Script library (the Scripts add-source) ----------
    def _selected_script(self):
        item = self.add_tree.currentItem()
        if item is None or item.data(0, ROLE_TYPE) != TYPE_SCRIPT:
            return ""
        return script_filename(item.data(0, ROLE_TOKEN) or "")

    def _new_script(self):
        if exec_(_ScriptEditorDialog(self)) == QDialog.DialogCode.Accepted:
            self._reload_available()

    def _edit_script(self):
        fn = self._selected_script()
        if not fn:
            QMessageBox.information(self, "TFM", "Select a script in the list first.")
            return
        if exec_(_ScriptEditorDialog(self, fn, read_script(fn))) == QDialog.DialogCode.Accepted:
            self._reload_available()

    def _rename_script_file(self):
        fn = self._selected_script()
        if not fn:
            QMessageBox.information(self, "TFM", "Select a script in the list first.")
            return
        if os.path.normcase(script_path(fn)) != os.path.normcase(os.path.join(SCRIPTS_DIR, fn)):
            QMessageBox.information(self, "TFM", "This is a bundled example. Edit it first to create your own copy before renaming it.")
            return
        new_name, ok = QInputDialog.getText(self, "Rename Script", "New name:",
                                            text=os.path.splitext(fn)[0])
        if not ok or not new_name.strip():
            return
        new_fn = rename_script(fn, new_name)
        if not new_fn:
            QMessageBox.warning(
                self, "TFM",
                "Could not rename the script (a script with that name may already exist).")
            return
        self._remap_script_items(fn, new_fn)
        self._render_items()
        self._reload_available()

    def _delete_script_file(self):
        fn = self._selected_script()
        if not fn:
            QMessageBox.information(self, "TFM", "Select a script in the list first.")
            return
        if os.path.normcase(script_path(fn)) != os.path.normcase(os.path.join(SCRIPTS_DIR, fn)):
            QMessageBox.information(self, "TFM", "This is a bundled example and cannot be deleted.")
            return
        reply = QMessageBox.question(
            self, "Delete Script",
            "Delete '%s' from the library?\n\n"
            "The bundled example will be used if one has the same name; "
            "otherwise menu items using it will report 'not found'." % fn,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        if not delete_script(fn):
            QMessageBox.warning(self, "TFM", "Could not delete the script file.")
            return
        self._reload_available()

    def _open_scripts_folder(self):
        path = ensure_scripts_dir()
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception:
            QMessageBox.information(self, "TFM", "Script folder:\n%s" % path)

    def _remap_script_items(self, old_fn, new_fn):
        """Follow a renamed script file from every menu item that uses it."""
        def walk(items):
            for it in items:
                if not isinstance(it, dict):
                    continue
                if it.get("script") == old_fn:
                    it["script"] = new_fn
                if isinstance(it.get("items"), list):
                    walk(it["items"])
        for lst in self.lists:
            walk(lst.get("items", []))

    def _add_submenu(self):
        if not self.path:
            return
        name, ok = QInputDialog.getText(self, "Add Submenu", "Submenu name:")
        if not ok or not name.strip():
            return
        self._cur_items().append({"name": name.strip(), "shortcut": "", "items": []})
        self._render_items()

    def _add_separator(self):
        if not self.path:
            return
        self._cur_items().append({"sep": True, "label": ""})
        self._render_items()

    def _add_header(self):
        if not self.path:
            return
        title, ok = QInputDialog.getText(self, "Add Header", "Header text:")
        if ok and title.strip():
            t = title.strip()
            self._cur_items().append({"header": t, "label": t})
            self._render_items()

    def _add_toggle(self):
        if not self.path:
            return
        if self._checkable_actions is None:
            checkable = []
            try:
                for a in Krita.instance().actions():
                    try:
                        if a.isCheckable() and a.objectName():
                            label = a.text().replace("&", "").strip() or a.objectName()
                            checkable.append((a.objectName(), label))
                    except Exception:
                        continue
            except Exception:
                checkable = []
            checkable.sort(key=lambda x: x[1].lower())
            self._checkable_actions = checkable
        checkable = self._checkable_actions
        if not checkable:
            QMessageBox.information(self, "Add Toggle", "No checkable Krita actions found.")
            return
        items = ["%s  (%s)" % (label, name) for name, label in checkable]
        sel, ok = QInputDialog.getItem(self, "Add Toggle",
                                       "Pick a checkable action (✓ shows its state):",
                                       items, 0, False)
        if ok and sel:
            name = sel.rsplit("  (", 1)[-1].rstrip(")")
            self._cur_items().append({"toggle": name,
                                      "label": dict(checkable).get(name, name)})
            self._render_items()

    def _remove_selected(self):
        row = self.items_list.currentRow()
        if row < 0 or not self._cur_items():
            return
        self._cur_items().pop(row)
        self._render_items()
        self._reload_available()

    def _rename_item(self):
        row = self.items_list.currentRow()
        items = self._cur_items()
        if row < 0 or not items:
            return
        cur = items[row]
        if isinstance(cur, dict) and cur.get("name") is not None:
            new_name, ok = QInputDialog.getText(
                self, "Rename Submenu", "Submenu name:", text=cur["name"])
            if ok and new_name.strip():
                cur["name"] = new_name.strip()
                self._render_items()
                self._render_path_bar()
            return
        if isinstance(cur, dict) and cur.get("blend") is not None:
            new_label, ok = QInputDialog.getText(
                self, "Rename Blend Mode", "Display name:", text=cur.get("label", ""))
            if ok:
                cur["label"] = new_label.strip()
                self._render_items()
            return
        if isinstance(cur, dict) and cur.get("brush") is not None:
            new_label, ok = QInputDialog.getText(
                self, "Rename Brush", "Display name:", text=cur.get("label", ""))
            if ok:
                cur["label"] = new_label.strip()
                self._render_items()
            return
        # command: set custom label
        key = cur.get("id", "") if isinstance(cur, dict) else cur
        default = (cur.get("label", "") if isinstance(cur, dict) else "") \
            or self._catalog.get(key, key)
        if not default:
            entry = self.items_list.currentItem()
            default = entry.text() if entry is not None else ""
        new_label, ok = QInputDialog.getText(
            self, "Rename Item",
            "Custom name (leave empty to use Krita's default):",
            text=default)
        if ok:
            if isinstance(cur, str):
                items[row] = {"id": cur, "label": new_label.strip()}
            else:
                cur["label"] = new_label.strip()
            self._render_items()

    # ---------- Export / import ----------
    def _export_config(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Config", "", "TFM Config (*.json)")
        if not path:
            return
        data = build_config_dict(self.popup_shortcut, self.lists)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "Exported", f"Config exported to\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))

    def _import_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Config", "", "TFM Config (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.popup_shortcut, self.lists = parse_config_dict(data)
        except Exception as e:
            QMessageBox.warning(self, "Import failed", str(e))
            return
        self.current = 0
        self.path = [self.lists[self.current]] if self.lists else []
        self._reload_sidebar()
        self._render_current()
        self._update_left_shortcut()

    # ---------- Conflict check ----------
    def _check_conflicts(self):
        """Message for a *leftover* conflict, or None (accepted overrides clear theirs)."""
        live = {}
        try:
            for a in Krita.instance().actions():
                action_id = a.objectName()
                pending_keys = {r.get("key") for recs in self._pending_overrides.values()
                                for r in recs if r.get("id") == action_id}
                label = (a.text() or action_id or "").replace("&", "").strip()
                for s in self._action_shortcuts(a):
                    if s not in pending_keys:
                        live.setdefault(s, label or action_id)
        except Exception as e:
            print("menubelt: cannot list actions: %s" % e)
        used = {}
        for lst in self.lists:
            key = lst.get("shortcut", "")
            if not key:
                continue
            if key in used:
                return (f"Lists \u201c{used[key]}\u201d and \u201c{lst['name']}\u201d both "
                        f"use shortcut \u201c{key}\u201d.")
            used[key] = lst["name"]
            if key in live:
                return (f"Shortcut \u201c{key}\u201d for list \u201c{lst['name']}\u201d "
                        f"is already used by Krita action \u201c{live[key]}\u201d.")
        return None

    # ---------- Save ----------
    def save_menus(self):
        conflict = self._check_conflicts()
        if conflict:
            QMessageBox.warning(self, "Shortcut conflict", conflict)
            return
        if self._pending_overrides:
            from . import config as menu_config
            try:
                stored = menu_config._read_raw(strict=True)
                stored_lists = stored.get("lists", [])
            except (OSError, ValueError):
                QMessageBox.warning(self, "TFM", "Could not read the menu configuration. Menus were not saved.")
                return
            saved_names = {item.get("name") for item in stored_lists if isinstance(item, dict)} if isinstance(stored_lists, list) else set()
            new_names = set(self._pending_overrides) - saved_names
            path = self._shortcut_file()
            if path is None:
                QMessageBox.warning(self, "TFM", "Krita's shortcut file location could not be found. Menus were not saved.")
                return
            try:
                read_text(path, strict=True)
            except OSError as error:
                QMessageBox.warning(self, "TFM", "Could not read the shortcut file: {}. Menus were not saved.".format(error))
                return
            if new_names:
                staged = list(stored_lists) if isinstance(stored_lists, list) else []
                staged.extend({**item, "shortcut": ""} for item in self.lists if item.get("name") in new_names)
                stored["lists"] = staged
                if not menu_config._write_raw(stored):
                    QMessageBox.warning(self, "TFM", "Could not prepare the new menu for shortcut recovery. Menus were not saved.")
                    return
        if not self._apply_pending_overrides():
            self._update_undo_button()
            QMessageBox.warning(self, "TFM", "Shortcut overrides could not be applied. A new menu may have been saved without a shortcut; recovery records were retained where available. Retry Save or use Restore.")
            return
        if not save_config(self.popup_shortcut, self.lists):
            self._update_undo_button()
            QMessageBox.warning(self, "TFM", "Could not save menu settings. Applied shortcut overrides can be restored using Restore.")
            return
        self._saved_menu_state = self._menu_state()
        self._update_undo_button()
        notify_refresh()
