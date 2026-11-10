"""Menu editor UI and compatible public exports."""
from .editor_context import *  # noqa: F403
from .editor_shortcuts import ShortcutEditingMixin
from .editor_scripts import ScriptEditingMixin
from .editor_model import MenuEditingMixin

class ListMenuDialog(ShortcutEditingMixin, ScriptEditingMixin, MenuEditingMixin, QWidget):
    """Multi-menu editor with nested submenu navigation + a live Current Menu list."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._services = sys.modules[__name__]
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
        self._refresh_conflict_banner()
        self._update_tag_widget()
        self._reload_available()
        self._saved_menu_state = self._menu_state()



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









    # ---------- UI ----------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        body = QHBoxLayout()
        body.setSpacing(8)

        # Left: top-level menus
        left_box = QGroupBox(tr("Menus", "菜单"))
        left = QVBoxLayout(left_box)
        left.setContentsMargins(8, 8, 8, 8)
        left.setSpacing(6)
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
        left_box.setMinimumWidth(180)
        body.addWidget(left_box, 1)

        # Centre: current menu items + compact settings bar
        current_box = QGroupBox(tr("Current menu", "当前菜单"))
        self.current_box = current_box
        cm = QVBoxLayout(current_box)
        cm.setContentsMargins(8, 8, 8, 8)
        cm.setSpacing(6)
        header_row = QHBoxLayout()
        self.crumb_row = QHBoxLayout()
        header_row.addLayout(self.crumb_row)
        header_row.addStretch()
        cm.addLayout(header_row)

        items_host = QWidget()
        items_layout = QVBoxLayout(items_host)
        items_layout.setContentsMargins(0, 0, 0, 0)
        items_layout.setSpacing(0)
        self.items_list = _MenuItemsList(self)
        self.items_list.setObjectName("menuItems")
        self.items_list.itemDoubleClicked.connect(self._on_item_double_click)
        self.items_list.setUniformItemSizes(False)
        self.items_list.setSpacing(0)
        self.items_list.setItemDelegate(_MenuItemDelegate(self.items_list))
        items_layout.addWidget(self.items_list)
        self.items_empty = make_empty_state(
            items_host,
            tr("This menu is empty.\nAdd actions from the right panel.",
               "此菜单为空。\n从右侧面板添加动作。"),
        )
        self.items_empty.hide()
        self.items_list.installEventFilter(self)
        cm.addWidget(items_host, 1)

        # Compact settings strip (not a nested GroupBox)
        settings_bar = QHBoxLayout()
        settings_bar.setSpacing(6)
        settings_bar.addWidget(QLabel(tr("Mode", "模式")))
        self.form_combo = QComboBox()
        self.form_combo.addItem(tr("List", "列表"), "list")
        self.form_combo.addItem(tr("Pie", "饼状"), "pie")
        self.form_combo.setToolTip(
            "List: linear cursor menu.\n"
            "Pie: Blender-style radial menu (up to 8 items, submenus not shown).")
        self.form_combo.currentIndexChanged.connect(self._on_form_changed)
        settings_bar.addWidget(self.form_combo)
        self.show_icons_check = QCheckBox(tr("Icons", "图标"))
        self.show_icons_check.setToolTip("Display Krita action icons and brush thumbnails in this menu.")
        self.show_icons_check.toggled.connect(self._on_show_icons_changed)
        settings_bar.addWidget(self.show_icons_check)
        settings_bar.addWidget(QLabel(tr("Shortcut", "快捷键")))
        self.list_sc_edit = QKeySequenceEdit()
        self.list_sc_edit.setMinimumWidth(90)
        self.list_sc_edit.setToolTip(
            "Press a key combination to pop this menu at the cursor.\n"
            "If it collides with another binding you can take it over.")
        self.list_sc_edit.keySequenceChanged.connect(self._on_list_shortcut_changed)
        settings_bar.addWidget(self.list_sc_edit)
        sc_clear = icon_tool_button(
            self, tr("Clear", "清除"),
            tr("Clear this menu shortcut", "清除此菜单快捷键"),
            "SP_LineEditClearButton", self._clear_list_shortcut)
        settings_bar.addWidget(sc_clear)
        self.undo_sc_btn = icon_tool_button(
            self, tr("Restore", "恢复"),
            tr("Give back the Krita shortcuts this menu took over",
               "把此菜单占用的 Krita 快捷键还回去"),
            "SP_BrowserReload", self._restore_overrides)
        settings_bar.addWidget(self.undo_sc_btn)
        settings_bar.addStretch()
        cm.addLayout(settings_bar)
        self.shortcut_conflict_label = QLabel("")
        apply_warning_label(self.shortcut_conflict_label)
        self.shortcut_conflict_label.hide()
        cm.addWidget(self.shortcut_conflict_label)

        self.items_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.items_list.customContextMenuRequested.connect(self._items_context_menu)
        body.addWidget(current_box, 2)

        # Add items (pick a Krita action or a layer blend mode to add)
        avail_box = QGroupBox(tr("Add items", "添加项目"))
        av = QVBoxLayout(avail_box)
        av.setContentsMargins(8, 8, 8, 8)
        av.setSpacing(6)
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
        self._saved_menu_state = self._menu_state()
        notify_refresh()

    def _on_switch_list(self, row):
        if 0 <= row < len(self.lists):
            self.current = row
            self.path = [self.lists[row]]
            self._update_left_shortcut()
            self._update_form_combo()
            self._update_show_icons_check()
            self._render_current()



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


    def _warn_pie_limits(self, lst):
        if lst is None or lst.get("menu_mode", lst.get("form", "list")) != "pie":
            return
        items = lst.get("items") or []
        has_submenu = any(isinstance(it, dict) and it.get("type") == "menu" for it in items)
        count = sum(1 for it in items if isinstance(it, dict) and it.get("type") != "sep")
        messages = []
        if count > 8:
            messages.append(tr(
                "Pie menus show at most 8 items ({} configured).",
                "饼状菜单最多显示 8 项（当前配置了 {} 项）。",
            ).format(count))
        if has_submenu:
            messages.append(tr(
                "Submenus are hidden in pie mode.",
                "饼状模式下子菜单会被隐藏。",
            ))
        if not messages:
            return
        from .qtcompat import QMessageBox
        QMessageBox.information(
            self,
            tr("Pie menu", "饼状菜单"),
            "\n".join(messages),
        )

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






    # ---------- Shortcut ----------






    # ---------- Current menu items ----------

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
        self._sync_items_empty_state()

    def _sync_items_empty_state(self):
        empty = getattr(self, "items_empty", None)
        if empty is None:
            return
        sync_empty_state(empty, self.items_list.count() == 0)
        position_empty_state(empty, self.items_list)

    def eventFilter(self, obj, event):
        if obj is getattr(self, "items_list", None) and event.type() == QEvent.Type.Resize:
            position_empty_state(getattr(self, "items_empty", None), self.items_list)
        return super().eventFilter(obj, event)


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




    def _on_item_double_click(self, *_):
        entry = self.items_list.currentItem()
        if entry is None:
            return
        if entry.data(ROLE_TYPE) == TYPE_MENU:
            self._enter_submenu()
        else:
            self._rename_item()



    def _on_tree_double_click(self, item, _column):
        # Double-click a leaf to add it; a category header just expands/collapses.
        if item is not None and item.data(0, ROLE_TYPE) != TYPE_CAT:
            self._add_selected()

    # ---------- Script library (the Scripts add-source) ----------













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
        self._refresh_conflict_banner()
        notify_refresh()
