"""TFM menus extension: builds synchronised multi-list entries plus shortcuts.

Shortcuts use a keyboard event filter (not QShortcut), because Krita's canvas
shortcut handling consumes key events before Qt's QShortcut system sees them.

- Tools > TFM submenu (lists -> items)
- Cursor popup menu (reuses the same QMenu; bound to a shortcut)
- A dynamic shortcut per list (each list can pop on its own hotkey)
- Edit dialog (saving changes refreshes every entry + shortcuts automatically)
"""

import os
import time

from krita import Extension, Krita

from ..i18n import tr
from .qtcompat import (
    QAction,
    QApplication,
    QColor,
    QCursor,
    QEvent,
    QFont,
    QIcon,
    QKeySequence,
    QKeySequenceEdit,
    QLineEdit,
    QMenu,
    QMessageBox,
    QObject,
    QPixmap,
    QPlainTextEdit,
    QPoint,
    QTextEdit,
    Qt,
    QtWidgets,
    QWidgetAction,
    event_key_sequence,
    exec_,
)

from .config import (load_last_identity, load_lists, load_overrides,
                     notify_refresh, register_refresh, save_last_identity,
                     run_brush, run_brush_blend, run_brush_value,
                     run_composite_op, run_script, run_set_color)
from .pie import PieWidget
from .shortcuts import find_shortcut_file, migrate_legacy_shortcuts, unbind
from .theme import apply_dark_theme as _apply_dark_theme
from .menu_rows import MenuRow as _MenuRow, SeparatorRow as _SeparatorRow

# Keys that on their own are modifiers, not real shortcuts
_MODIFIER_KEYS = (
    Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
    Qt.Key.Key_unknown, Qt.Key.Key_CapsLock, Qt.Key.Key_NumLock, Qt.Key.Key_ScrollLock,
)
_TEXT_INPUTS = (QLineEdit, QTextEdit, QPlainTextEdit, QKeySequenceEdit)


def _trigger_action(aid):
    """Trigger a Krita action by id (used by pie toggle slices)."""
    try:
        act = Krita.instance().action(aid)
        if act is not None:
            act.trigger()
    except Exception:
        pass


class _KeyFilter(QObject):
    """Installed on the Krita main window; dispatches configured shortcuts."""

    def __init__(self, extension, owner=None):
        super().__init__(owner)
        self._ext = extension

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.isAutoRepeat():
                return False  # ignore key auto-repeat while held (prevents re-triggering)
            key = event.key()
            if key in _MODIFIER_KEYS:
                return False
            # Do not hijack typing in text inputs (e.g. renaming a layer)
            fw = QApplication.focusWidget()
            if isinstance(fw, _TEXT_INPUTS):
                return False
            seq = event_key_sequence(event)
            # Consume keys we own: a key bound to a list must not *also* reach the
            # canvas / another handler (that would make an override half-applied).
            if self._ext.dispatch_shortcut(seq.toString(QKeySequence.SequenceFormat.PortableText)):
                return True
        elif event.type() == QEvent.Type.KeyRelease:
            if event.isAutoRepeat():
                return False  # ignore auto-release pairs while held
            key = event.key()
            if key in _MODIFIER_KEYS:
                return False
            # A pie is shown while the trigger key is held; release activates it.
            self._ext.pie_release()
        return False


class TfmExtension(Extension):
    def __init__(self, parent):
        super().__init__(parent)
        # One entry per window: {window, root_action, menu}
        self._windows = []
        self._shortcut_map = {}   # shortcut string -> callable
        self._popup_active = False
        self._popup_menu_ref = None
        self._last_identity = load_last_identity()  # persisted last-triggered item
        self._pie = None            # active PieWidget (None when no pie is open)
        self._ignore_until = 0.0  # debounce: swallow re-triggers right after closing
        # Brush icon + preset caches (build once, not per menu item)
        self._brush_icons = {}      # preset name -> QIcon (or None)
        self._presets = None        # cached resources("preset") dict
        # App-level key filter (global, sees every key press regardless of focus)
        self._app_filter = _KeyFilter(self)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._app_filter)
        register_refresh(self._rebuild_all)

    def setup(self):
        pass

    def createActions(self, window):
        # Trigger action (whole-menu popup; also usable via Krita shortcuts editor)
        migrated = migrate_legacy_shortcuts(find_shortcut_file())
        popup_action = window.createAction(
            "tfm_popup", tr("Pop Up Custom List", "弹出自定义列表"), "")
        if "tfm_popup" in migrated:
            popup_action.setShortcut(QKeySequence(migrated["tfm_popup"]))
        popup_action.triggered.connect(self.pop_menu)

        # Group TFM commands under a single Tools submenu.
        root_action = window.createAction("tfm_tools_menu", "TFM", "tools")
        tools_menu = QMenu(window.qwindow())
        root_action.setMenu(tools_menu)
        edit_action = window.createAction(
            "tfm_edit", tr("Configure TFM", "配置 TFM"), "")
        edit_action.triggered.connect(self.open_editor)

        color_range_action = window.createAction(
            "tfm_color_range", tr("Advanced Selection…", "高级选区…"), "Select")
        color_range_action.triggered.connect(self.open_color_range)
        from ..manager import (
            color_range_enabled, convert_color_space_enabled, assets_enabled,
            search_enabled)
        color_range_action.setVisible(color_range_enabled())
        color_range_action.setEnabled(color_range_enabled())

        assets_action = window.createAction("tfm_assets", tr("Asset Library", "资产库"), "")
        assets_action.triggered.connect(self.show_assets)
        assets_action.setVisible(assets_enabled())
        assets_action.setEnabled(assets_enabled())
        save_asset_action = window.createAction("tfm_save_asset", tr("Save Asset", "保存资产"), "")
        save_asset_action.triggered.connect(self.save_asset)
        save_asset_action.setVisible(assets_enabled())
        save_asset_action.setEnabled(assets_enabled())
        search_action = window.createAction("tfm_image_search", tr("Quick Image Search", "快速搜图"), "")
        search_action.triggered.connect(self.show_image_search)
        search_action.setVisible(search_enabled())
        search_action.setEnabled(search_enabled())
        convert_action = window.createAction(
            "tfm_convert_color_space",
            tr("Convert All Layers to Default Color Space", "将所有图层转换为默认色彩空间"),
            "")
        convert_action.triggered.connect(self.convert_layers_color_space)
        convert_action.setVisible(convert_color_space_enabled())
        convert_action.setEnabled(convert_color_space_enabled())
        tools_menu.addAction(assets_action)
        tools_menu.addAction(save_asset_action)
        tools_menu.addAction(search_action)
        tools_menu.addAction(convert_action)
        tools_menu.addAction(edit_action)

        self._windows.append({
            "window": window,
            "root_action": root_action,
            "tools_menu": tools_menu,
            "edit_action": edit_action,
        })
        self._rebuild(window)
        self._register_shortcuts()

    # ---------- Build / refresh ----------
    def _rebuild_all(self):
        for entry in self._windows:
            self._rebuild(entry["window"])
        self._register_shortcuts()

    def _rebuild(self, window):
        """Keep the direct Tools action registered; rebuild popup shortcuts."""
        for entry in self._windows:
            if entry["window"] is window:
                break

    # ---------- Dynamic shortcuts (event filter based) ----------
    def _register_shortcuts(self):
        # Rebuild the shortcut lookup map from current config.
        # Whole-menu popup trigger is bound via Krita's own Keyboard Shortcuts
        # editor (the tfm_popup action), so only per-list keys
        # are registered here. The app-level event filter stays installed.
        # Scanning every Krita action is only needed when the key set changes.
        previous = set(self._shortcut_map)
        self._shortcut_map = {}
        for lst in load_lists():
            if not lst.get("active", True):
                continue
            key = lst.get("shortcut", "")
            if key:
                name = lst["name"]
                if lst.get("menu_mode", lst.get("form", "list")) == "pie":
                    self._shortcut_map[key] = (lambda n=name: self.pop_pie(n))
                else:
                    self._shortcut_map[key] = (lambda n=name: self.pop_list(n))
        if set(self._shortcut_map) != previous:
            self._reassert_overrides()

    def _reassert_overrides(self):
        """Re-take keys recorded as overridden when a Krita action holds one again.

        Krita regenerates kritashortcutsrc whenever its shortcut editor is saved,
        which can hand a key back to the built-in action. TFM only ever
        re-clears an action whose *current* shortcut is a key one of our active
        lists still uses — a binding the user moved elsewhere is left alone.
        """
        try:
            mine = {lst.get("shortcut") for lst in load_lists()
                    if lst.get("active", True) and lst.get("shortcut")}
        except Exception:
            return
        if not mine:
            return
        wanted = {}
        for records in load_overrides().values():
            for rec in records:
                if rec.get("key") in mine:
                    wanted[rec.get("id")] = rec
        if not wanted:
            return
        try:
            actions = Krita.instance().actions()
        except Exception:
            return
        path = find_shortcut_file()
        for a in actions:
            try:
                oid = a.objectName()
            except RuntimeError:
                continue
            rec = wanted.get(oid)
            if rec is None:
                continue
            try:
                held = [s.toString(QKeySequence.SequenceFormat.PortableText) for s in a.shortcuts()]
            except Exception:
                held = []
            if not held:
                try:
                    s = a.shortcut()
                    held = [] if s.isEmpty() else [s.toString(QKeySequence.SequenceFormat.PortableText)]
                except Exception:
                    held = []
            if rec.get("key") not in held:
                continue          # the user rebound it: not ours to touch
            try:
                a.setShortcuts([])
            except Exception:
                pass
            if path is not None:
                unbind(path, oid)
            print("tfm: re-took %s from %s" % (rec.get("key"), oid))

    def _list_index_by_name(self, name):
        for i, lst in enumerate(load_lists()):
            if lst.get("name") == name:
                return i
        return -1

    def dispatch_shortcut(self, seq_str):
        """Called by the event filter with the pressed key sequence (PortableText).

        Returns True when the key is one of ours — the caller then consumes the key
        event, so nothing else (canvas input, another action) reacts to it too.
        """
        if self._pie is not None or self._popup_active:
            return False  # a pie or list popup is already open
        cb = self._shortcut_map.get(seq_str)
        if cb is None:
            return False
        cb()
        return True

    # ---------- Behaviour ----------
    def _active_menu(self):
        active = Krita.instance().activeWindow()
        if active is not None:
            try:
                active.qwindow()
            except RuntimeError:
                active = None
        for entry in self._windows:
            if active is not None and entry["window"] is active:
                return entry["menu"]
        return self._windows[0]["menu"] if self._windows else None

    def _find_action(self, ident_map, identity):
        """Return the QAction in ident_map whose identity matches (or None)."""
        if identity is None or not ident_map:
            return None
        for act, ident in ident_map.items():
            if ident == identity:
                return act
        return None

    def _popup_anchor(self, menu, ident_map):
        """Return (pos, at_action) so the popup opens with the LAST-triggered item
        under the cursor (both axes), falling back to the raw cursor position."""
        pos = QCursor.pos()
        at = self._find_action(ident_map, self._last_identity)
        if at is not None:
            try:
                rect = menu.actionGeometry(at)
                if rect.isValid():
                    # Qt anchors the menu's left edge at pos.x (that's why X sits at
                    # the leftmost); shift left by the item's centre so the cursor
                    # points at the item's middle instead.
                    pos = QPoint(pos.x() - rect.center().x(), pos.y())
            except Exception:
                pass
        return pos, at

    def pop_menu(self, *_):
        """Open the whole multi-list menu under the cursor of the active window."""
        if self._popup_active or time.time() < self._ignore_until:
            return
        ident_map = {}
        menu = self._build_popup_menu(self._active_window_widget(), ident_map)
        pos, at = self._popup_anchor(menu, ident_map)
        self._popup_active = True
        try:
            triggered = exec_(menu, pos, at)
            if triggered is not None:
                ident = ident_map.get(triggered)
                if ident is not None:
                    self._last_identity = ident
                    save_last_identity(ident)
        finally:
            self._popup_active = False
            self._popup_menu_ref = None
            self._ignore_until = time.time() + 0.3
            menu.deleteLater()

    def pop_list(self, target):
        """Open only one list (given its index or name) as a cursor menu."""
        if self._popup_active or time.time() < self._ignore_until:
            return
        index = target if isinstance(target, int) else self._list_index_by_name(target)
        if index < 0:
            return
        try:
            lst = load_lists()[index]
        except (IndexError, TypeError):
            return
        if not lst.get("active", True):
            return
        parent = self._active_window_widget()
        ident_map = {}
        menu = QMenu(parent)
        _apply_dark_theme(menu)
        self._build_menu_node(menu, lst, ident_map, lst.get("show_icons", True))
        if not menu.actions():
            menu.deleteLater()
            return
        # Prepend a menu-name header (disabled title) above a divider.
        first = menu.actions()[0]
        title = QAction(lst["name"], menu)
        title.setEnabled(False)
        tf = title.font()
        tf.setPointSize(max(6, tf.pointSize() - 1))
        title.setFont(tf)
        menu.insertAction(first, title)
        sep_act = QWidgetAction(menu)
        sep_act.setDefaultWidget(_SeparatorRow())
        menu.insertAction(first, sep_act)
        self._force_close_on_trigger(menu)
        pos, at = self._popup_anchor(menu, ident_map)
        self._popup_active = True
        try:
            triggered = exec_(menu, pos, at)
            if triggered is not None:
                ident = ident_map.get(triggered)
                if ident is not None:
                    self._last_identity = ident
                    save_last_identity(ident)
        finally:
            self._popup_active = False
            self._popup_menu_ref = None
            self._ignore_until = time.time() + 0.3
            menu.deleteLater()

    # ---------- Pie (radial) form ----------
    def _pie_slices(self, lst):
        """Build [(label, icon|None, trigger_callable)] for a list's leaf items."""
        slices = []
        for entry in lst.get("items", []):
            aid, label = None, ""
            if isinstance(entry, str):
                aid = entry
            elif isinstance(entry, dict):
                if entry.get("id"):
                    aid, label = entry["id"], entry.get("label", "")
                elif entry.get("blend") is not None:
                    oid = entry.get("blend", "")
                    slices.append((entry.get("label", oid), None,
                                   lambda o=oid: run_composite_op(o)))
                    continue
                elif entry.get("bblend") is not None:
                    oid = entry.get("bblend", "")
                    slices.append((entry.get("label", oid), None,
                                   lambda o=oid: run_brush_blend(o)))
                    continue
                elif entry.get("bval") is not None:
                    spec = entry.get("bval", "")
                    slices.append((entry.get("label", spec), None,
                                   lambda s=spec: run_brush_value(s)))
                    continue
                elif entry.get("color") is not None:
                    hexc = entry.get("color", "#000000")
                    target = entry.get("target", "fg")
                    slices.append((entry.get("label", hexc),
                                   self._color_icon(hexc),
                                   lambda h=hexc, t=target: run_set_color(h, t)))
                    continue
                elif entry.get("toggle") is not None:
                    aid = entry.get("toggle", "")
                    checked = False
                    try:
                        nat = Krita.instance().action(aid)
                        checked = bool(nat.isChecked()) if nat else False
                    except Exception:
                        checked = False
                    slices.append((entry.get("label", aid), None,
                                   lambda a=aid: _trigger_action(a)))
                    continue
                elif entry.get("brush") is not None:
                    bfile = entry.get("brush", "")
                    slices.append((entry.get("label", bfile), self._brush_icon(bfile),
                                   lambda f=bfile: run_brush(f)))
                    continue
                elif entry.get("script") is not None:
                    sfile = entry.get("script", "")
                    label = entry.get("label", "") or os.path.splitext(sfile)[0]
                    slices.append((label, None, lambda f=sfile: run_script(f)))
                    continue
                elif entry.get("name") is not None:
                    continue  # submenu: not representable in a single-level pie (v1)
                else:
                    continue
            else:
                continue
            act = Krita.instance().action(aid)
            if act is None:
                continue
            icon = act.icon()
            slices.append((label or act.text().replace("&", "").strip(),
                           icon if not icon.isNull() else None, act.trigger))
        return slices

    def pop_pie(self, target):
        """Show a Blender-style radial menu for a pie-form list (index or name)."""
        if self._pie is not None:
            return
        index = target if isinstance(target, int) else self._list_index_by_name(target)
        if index < 0:
            return
        try:
            lst = load_lists()[index]
        except (IndexError, TypeError):
            return
        if not lst.get("active", True):
            return
        slices = self._pie_slices(lst)
        if not slices:
            return
        pie = PieWidget(slices, self._active_window_widget())
        self._pie = pie
        pie.show_pie(QCursor.pos())

    def pie_release(self):
        """Activate the currently highlighted pie item and close the pie."""
        pie = self._pie
        if pie is None:
            return
        trig = pie.current_trigger()
        self._pie = None
        pie.close_pie()
        if trig is not None:
            trig()

    def _build_popup_menu(self, parent, ident_map=None):
        """Build a fresh cursor popup menu (lists -> items + edit footer)."""
        menu = QMenu(parent)
        _apply_dark_theme(menu)
        for lst in load_lists():
            if not lst.get("active", True):
                continue
            sub = menu.addMenu(lst["name"])
            _apply_dark_theme(sub)
            self._build_menu_node(sub, lst, ident_map, lst.get("show_icons", True))
        sep_act = QWidgetAction(menu)
        sep_act.setDefaultWidget(_SeparatorRow())
        menu.addAction(sep_act)
        edit_act = menu.addAction(tr("Configure TFM…", "配置 TFM…"))
        edit_act.triggered.connect(self.open_editor)
        self._force_close_on_trigger(menu)
        return menu

    def _add_row(self, menu, text, icon, callback, shortcut="", enabled=True,
                 checkable=False, checked=False):
        """Add a QWidgetAction row that paints its own icon+text, so icons render
        even under Krita's global stylesheet (which makes QMenu drop action icons).
        Returns the QWidgetAction."""
        act = QWidgetAction(menu)
        row = _MenuRow(text, icon=icon, shortcut=shortcut,
                       checkable=checkable, checked=checked)
        row.setPalette(menu.palette())
        row.setEnabled(enabled)
        act.setDefaultWidget(row)
        act.setEnabled(enabled)
        if callback is not None:
            act.triggered.connect(lambda _=False: callback())
        menu.addAction(act)
        return act

    def _add_cmd(self, menu, action_id, label, show_icons, ident_map):
        """Add a command (Krita action) row; trigger() runs the native action."""
        try:
            native = Krita.instance().action(action_id)
        except RuntimeError:
            native = None
        if native is None:
            return
        text = label or native.text().replace("&", "").strip()
        icon = None
        if show_icons:
            try:
                icon = native.icon()
                if icon.isNull():
                    icon = None
            except RuntimeError:
                icon = None
        try:
            sc = native.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        except Exception:
            sc = ""
        act = self._add_row(menu, text, icon, native.trigger, shortcut=sc,
                            enabled=native.isEnabled())
        if ident_map is not None:
            ident_map[act] = ("cmd", action_id)

    @staticmethod
    def _color_icon(hexc):
        """A small solid-colour swatch QIcon for a #rrggbb colour item."""
        try:
            pix = QPixmap(20, 20)
            pix.fill(QColor(hexc))
            return QIcon(pix)
        except Exception:
            return None

    def _add_toggle(self, menu, entry, ident_map):
        """Add a checkable toggle row backed by a Krita action (isChecked/trigger)."""
        aid = entry.get("toggle", "")
        native = None
        try:
            native = Krita.instance().action(aid)
        except RuntimeError:
            native = None
        checked = False
        enabled = True
        if native is not None:
            try:
                checked = bool(native.isChecked())
            except Exception:
                checked = False
            try:
                enabled = native.isEnabled()
            except Exception:
                enabled = True
        label = entry.get("label", aid) or aid
        row = _MenuRow(label, icon=None, checkable=True, checked=checked)
        row.setPalette(menu.palette())
        row.setEnabled(enabled)
        act = QWidgetAction(menu)
        act.setDefaultWidget(row)
        act.setEnabled(enabled)
        if native is not None:
            act.triggered.connect(lambda _=False, n=native: n.trigger())
        menu.addAction(act)
        if ident_map is not None:
            ident_map[act] = ("toggle", aid)

    def _get_presets(self):
        """Cached dict of all Krita brush presets (name -> Resource).

        Calling resources("preset") enumerates every preset; building a menu with
        N brush items called it N times (O(N^2) -> seconds of lag). Cache it once.
        """
        if self._presets is None:
            self._presets = Krita.instance().resources("preset")
        return self._presets

    def _brush_icon(self, name):
        """Return a QIcon built from a brush preset's thumbnail image (or None).

        Icons are cached per preset name so each brush only loads its image once.
        """
        if name in self._brush_icons:
            return self._brush_icons[name]
        icon = None
        try:
            presets = self._get_presets()
            resource = presets.get(name)
            if resource is None:
                # fallback: legacy configs stored the preset filename
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
                    # downscale once to a small pixmap; avoids a full-size copy
                    icon = QIcon(QPixmap.fromImage(
                        img.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)))
        except Exception:
            icon = None
        self._brush_icons[name] = icon
        return icon

    def _build_menu_node(self, parent_menu, node, ident_map=None, show_icons=True):
        """Recursively add a menu node's commands and submenus.

        ident_map (optional) maps each added leaf QWidgetAction -> an identity
        tuple, so the popup can remember/relocate the last-triggered item.
        """
        for entry in node.get("items", []):
            if isinstance(entry, str):
                self._add_cmd(parent_menu, entry, "", show_icons, ident_map)
                continue
            if not isinstance(entry, dict):
                continue
            if entry.get("id"):
                self._add_cmd(parent_menu, entry["id"], entry.get("label", ""),
                              show_icons, ident_map)
            elif entry.get("blend") is not None:
                label = entry.get("label", entry["blend"])
                act = self._add_row(parent_menu, label, None,
                                    lambda o=entry.get("blend", ""): run_composite_op(o))
                if ident_map is not None:
                    ident_map[act] = ("blend", entry.get("blend", ""))
            elif entry.get("bblend") is not None:
                label = entry.get("label", entry["bblend"])
                act = self._add_row(parent_menu, label, None,
                                    lambda o=entry.get("bblend", ""): run_brush_blend(o))
                if ident_map is not None:
                    ident_map[act] = ("bblend", entry.get("bblend", ""))
            elif entry.get("bval") is not None:
                label = entry.get("label", entry["bval"])
                act = self._add_row(parent_menu, label, None,
                                    lambda s=entry.get("bval", ""): run_brush_value(s))
                if ident_map is not None:
                    ident_map[act] = ("bval", entry.get("bval", ""))
            elif entry.get("color") is not None:
                hexc = entry.get("color", "#000000")
                target = entry.get("target", "fg")
                row_icon = self._color_icon(hexc)
                act = self._add_row(parent_menu,
                                    entry.get("label", hexc), row_icon,
                                    lambda h=hexc, t=target: run_set_color(h, t))
                if ident_map is not None:
                    ident_map[act] = ("color", hexc + ":" + target)
            elif entry.get("sep"):
                sep_act = QWidgetAction(parent_menu)
                sep_widget = _SeparatorRow()
                sep_act.setDefaultWidget(sep_widget)
                parent_menu.addAction(sep_act)
            elif entry.get("header") is not None:
                label = entry.get("label", entry["header"]) or entry["header"]
                self._add_row(parent_menu, label, None, None, enabled=False)
            elif entry.get("toggle") is not None:
                self._add_toggle(parent_menu, entry, ident_map)
            elif entry.get("brush") is not None:
                label = entry.get("label", entry["brush"])
                icon = self._brush_icon(entry.get("brush", "")) if show_icons else None
                act = self._add_row(parent_menu, label, icon,
                                    lambda f=entry.get("brush", ""): run_brush(f))
                if ident_map is not None:
                    ident_map[act] = ("brush", entry.get("brush", ""))
            elif entry.get("script") is not None:
                fn = entry.get("script", "")
                label = entry.get("label", "") or os.path.splitext(fn)[0]
                act = self._add_row(parent_menu, label, None,
                                    lambda f=fn: run_script(f))
                if ident_map is not None:
                    ident_map[act] = ("script", fn)
            elif entry.get("name") is not None:
                sub = parent_menu.addMenu(entry["name"])
                self._build_menu_node(sub, entry, ident_map, show_icons)

    def _force_close_on_trigger(self, menu):
        """Force the menu to close after ANY item is clicked (even checkable).

        Connects to a stable method on the extension (not a closure capturing the
        menu) so that stale connections are safe after the menu is deleted.
        """
        self._popup_menu_ref = menu
        for act in menu.actions():
            if act.isSeparator():
                continue
            sub = act.menu()
            if sub is not None:
                self._force_close_on_trigger(sub)
            else:
                act.triggered.connect(self._close_current_popup)

    def _close_current_popup(self):
        m = self._popup_menu_ref
        if m is not None:
            try:
                m.close()   # end the exec_ event loop
            except RuntimeError:
                pass
            try:
                m.hide()
            except RuntimeError:
                pass

    def _active_window_widget(self):
        active = Krita.instance().activeWindow()
        if active is not None:
            try:
                return active.qwindow()
            except RuntimeError:
                pass
        try:
            return self._windows[-1]["window"].qwindow()
        except (IndexError, RuntimeError):
            return None

    def show_assets(self, *_):
        from ..manager import assets_enabled
        self._show_docker("tfm_assets", tr("Asset Library", "资产库"), assets_enabled())

    def save_asset(self, *_):
        from ..manager import assets_enabled, _assets_docks
        if not assets_enabled():
            return
        for dock in _assets_docks():
            saver = getattr(dock, "_save_active_asset", None)
            if saver is not None:
                saver()
                return
        self.show_assets()
        for dock in _assets_docks():
            saver = getattr(dock, "_save_active_asset", None)
            if saver is not None:
                saver()
                return

    def show_image_search(self, *_):
        from ..manager import search_enabled
        self._show_docker(
            "tfm_quick_image_search",
            tr("Quick Image Search", "快速搜图"),
            search_enabled(),
        )

    def _show_docker(self, object_name, title, enabled):
        window = Krita.instance().activeWindow()
        if window is None:
            return
        host = window.qwindow()
        if not enabled:
            QMessageBox.information(
                host,
                title,
                tr(
                    "{} is turned off. Enable it under Tools → TFM → Configure TFM → Tools.",
                    "{} 已关闭。请到 工具 → TFM → 配置 TFM → 工具 中启用。",
                ).format(title),
            )
            return
        dock = host.findChild(QtWidgets.QDockWidget, object_name)
        if dock is None:
            QMessageBox.information(
                host,
                title,
                tr(
                    "The {} panel is not available yet. Restart Krita, then use Tools → TFM → {}.",
                    "{} 面板尚未就绪。请重启 Krita，然后使用 工具 → TFM → {}。",
                ).format(title, title),
            )
            return
        toggle = dock.toggleViewAction()
        if toggle is not None:
            toggle.setVisible(True)
            toggle.setEnabled(True)
        dock.setVisible(True)
        dock.raise_()

    def open_editor(self, *_):
        from ..manager import show_manager
        show_manager(QApplication.activeWindow())

    def open_color_range(self, *_):
        from ..color_range import open_color_range
        open_color_range()

    def convert_layers_color_space(self, *_):
        from ..color_space import run_convert
        from ..manager import convert_color_space_enabled
        if not convert_color_space_enabled():
            QMessageBox.information(
                self._active_window_widget(),
                tr("Convert Layers", "转换图层"),
                tr(
                    "Layer Color Space is turned off. Enable it under Tools → TFM → Configure TFM → Tools.",
                    "图层色彩空间已关闭。请到 工具 → TFM → 配置 TFM → 工具 中启用。",
                ),
            )
            return
        run_convert(self._active_window_widget())

