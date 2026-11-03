"""fxmanager settings dialog.

This dialog manages the filter registry and processing policy. It never applies
filters or creates Krita nodes; those actions remain in Krita's native UI.
"""

from . import operations, settings
from .catalog import FILTERS, FILTER_DEFAULT_SPECS
from .qtcompat import (
    QColor,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QScrollArea,
    QWidget,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QMenu,
    QInputDialog,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    Qt,
    QtCore,
    PYQT6,
    checked_state,
    exec_,
    item_is_user_checkable,
    unchecked_state,
    user_role,
    _palette_role,
)

_ROLE = user_role()


def _dark_palette(widget):
    palette = widget.palette()
    palette.setColor(_palette_role("Window"), QColor("#303030"))
    palette.setColor(_palette_role("Base"), QColor("#1e1e1e"))
    palette.setColor(_palette_role("AlternateBase"), QColor("#252525"))
    palette.setColor(_palette_role("Text"), QColor("#eeeeee"))
    palette.setColor(_palette_role("WindowText"), QColor("#eeeeee"))
    palette.setColor(_palette_role("Highlight"), QColor("#527a9f"))
    palette.setColor(_palette_role("HighlightedText"), QColor("#ffffff"))
    widget.setPalette(palette)


class _CategoryList(QListWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def dragEnterEvent(self, event):
        item = self.owner._category_list.currentItem()
        if event.source() is self.owner._category_list and item and item.data(_ROLE) in self.owner._managed:
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        item = self.owner._category_list.currentItem()
        if event.source() is self.owner._category_list and item and item.data(_ROLE) in self.owner._managed:
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        source = self.currentItem()
        pos = event.position().toPoint() if PYQT6 else event.pos()
        target = self.itemAt(pos)
        if event.source() is not self or source is None or source.data(_ROLE) not in self.owner._managed:
            event.ignore()
            return
        target_category = target.data(_ROLE + 1) if target is not None else None
        if not target_category:
            event.ignore()
            return
        source_category = source.data(_ROLE + 1)
        if source_category == target_category:
            event.ignore()
            return
        ident = source.data(_ROLE)
        # The list is rebuilt after the drag. Accepting the proposed Move
        # makes Qt delete the dragged row from that rebuilt model and Krita hangs.
        event.setDropAction(Qt.DropAction.IgnoreAction if PYQT6 else Qt.IgnoreAction)
        event.accept()
        QtCore.QTimer.singleShot(0, lambda: self.owner._move_filter(ident, target_category))


class FxManagerDialog(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(980, 620)
        _dark_palette(self)
        self._pending = settings.load()
        self._pending["filter_defaults"] = {key: dict(value) for key, value in self._pending.get("filter_defaults", {}).items()}
        self._managed = set(self._pending.get("managed_filters", []))
        self._enabled = set(self._pending.get("enabled_filters", []))
        raw_categories = self._pending.get("filter_categories", {})
        raw = {str(k): list(dict.fromkeys(v)) for k, v in raw_categories.items()
               if isinstance(k, str) and k and isinstance(v, list)
               and all(isinstance(x, str) for x in v)} if isinstance(raw_categories, dict) else {}
        default_categories = ["Adjust", "Artistic", "Blur", "Colors", "Edge Detection", "Emboss", "Enhance", "Map", "Other"]
        aliases = {"Uncategorized": "Other", "Segmentation": "Enhance"}
        self._categories = {name: [] for name in default_categories}
        seen = set()
        old_ids = {}
        for entry in FILTERS:
            if entry["id"].startswith("tfm_"):
                suffix = entry["id"][len("tfm_"):]
                old_ids["filtermanager_" + suffix] = entry["id"]
                old_ids["fxmanager_" + suffix] = entry["id"]
        if raw:
            for old_name, ids in raw.items():
                name = aliases.get(old_name, old_name)
                if name not in self._categories:
                    name = "Other"
                for ident in ids:
                    ident = old_ids.get(ident, ident)
                    if ident not in seen:
                        self._categories[name].append(ident)
                        seen.add(ident)
        previously_known = {ident for ids in self._categories.values() for ident in ids}
        previously_known.update(ident for ident in self._pending.get("managed_filters", []) if isinstance(ident, str))

        def place(entry):
            name = aliases.get(entry.get("category", "Other"), entry.get("category", "Other"))
            category = self._categories.get(name, self._categories["Other"])
            if entry.get("category") == "Segmentation":
                category = self._categories["Enhance"]
            if entry["id"] not in category:
                category.append(entry["id"])

        if raw:
            for entry in FILTERS:
                if entry["id"] not in previously_known:
                    place(entry)
        else:
            for entry in FILTERS:
                place(entry)
        assigned = {ident for ids in self._categories.values() for ident in ids}
        self._categories["Other"].extend(ident for ident in self._pending.get("managed_filters", []) if ident not in assigned)
        if "managed_filters" not in self._pending:
            self._managed = {entry["id"] for entry in FILTERS}
        if "enabled_filters" not in self._pending:
            self._enabled = set(self._managed)
        elif "managed_filters" in self._pending:
            # A filter the saved file has never mentioned is new, not one the
            # user removed. Removed filters stay in the saved category lists.
            for entry in FILTERS:
                ident = entry["id"]
                if ident not in previously_known:
                    self._managed.add(ident)
                    self._enabled.add(ident)
        self._collapsed_categories = set()
        self._build_ui()
        self._reload()
        self._saved_filter_state = self._filter_state()

    def _filter_state(self):
        import copy
        return (copy.deepcopy(self._pending.get("filter_defaults", {})),
                set(self._managed), set(self._enabled), [(name, list(ids)) for name, ids in self._categories.items()])

    def has_unsaved_changes(self):
        return self._filter_state() != self._saved_filter_state

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        columns = QHBoxLayout()
        left = QVBoxLayout()
        filter_label = QLabel("Filters")
        filter_label.setToolTip(
            "Check a filter to register it in Krita's Filter menu (requires Save Filters, then restart Krita). "
            "Uncheck to hide it after restart. Drag a filter onto another category header to move it.")
        left.addWidget(filter_label)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search...")
        self._search.textChanged.connect(self._reload)
        left.addWidget(self._search)
        self._category_list = _CategoryList(self)
        self._category_list.setDragDropMode((QAbstractItemView.DragDropMode.DragDrop if PYQT6 else QAbstractItemView.DragDrop))
        self._category_list.setAcceptDrops(True)
        self._category_list.setDragDropOverwriteMode(False)
        self._category_list.setDropIndicatorShown(True)
        self._category_list.setDefaultDropAction((Qt.DropAction.MoveAction if PYQT6 else Qt.MoveAction))
        self._category_list.currentItemChanged.connect(self._category_selected)
        self._category_list.itemClicked.connect(self._toggle_category)
        self._category_list.itemChanged.connect(self._enabled_changed)
        self._category_list.model().rowsMoved.connect(self._categories_moved)
        self._category_list.setContextMenuPolicy((Qt.ContextMenuPolicy.CustomContextMenu if PYQT6 else Qt.CustomContextMenu))
        self._category_list.customContextMenuRequested.connect(self._category_menu)
        left.addWidget(self._category_list, 1)
        middle = QVBoxLayout()
        middle.addWidget(QLabel("Filter Details"))
        self._detail = QTextBrowser()
        self._detail.setOpenExternalLinks(False)
        middle.addWidget(self._detail, 1)
        middle.addWidget(QLabel("Default Parameters"))
        self._parameter_scroll = QScrollArea()
        self._parameter_scroll.setWidgetResizable(True)
        self._parameter_scroll.setMinimumHeight(180)
        middle.addWidget(self._parameter_scroll, 2)
        self._restore_defaults = QPushButton("Restore Factory Defaults")
        self._restore_defaults.clicked.connect(self._restore_selected_defaults)
        middle.addWidget(self._restore_defaults)

        self._status = QLabel()
        self._status.setWordWrap(True)
        middle.addWidget(self._status)

        columns.addLayout(left, 1)
        columns.addLayout(middle, 2)
        root.addLayout(columns, 1)

        line = QHBoxLayout()
        line.addStretch(1)
        self._save = QPushButton("Save Filters")
        self._save.clicked.connect(self.save_filters)
        line.addWidget(self._save)
        root.addLayout(line)

    def _style_filter_item(self, item, enabled):
        font = item.font()
        font.setItalic(not enabled)
        item.setFont(font)
        item.setForeground(QColor("#9a9a9a") if not enabled else QColor("#eeeeee"))

    def _reload(self):
        selected_id = None
        current = self._category_list.currentItem()
        if current is not None and current.data(_ROLE) is not None:
            selected_id = current.data(_ROLE)
        # Every catalog filter stays listed; the checkbox alone controls on/off.
        self._managed = {entry["id"] for entry in FILTERS}
        try:
            self._rows = operations.inspect()
        except operations.RegistryQueryError as error:
            self._rows = []
            blocked = self._category_list.blockSignals(True)
            try:
                self._category_list.clear()
            finally:
                self._category_list.blockSignals(blocked)
            self._show_selected()
            self._detail.setPlainText(
                "{}\nRegistration status is unknown. Reopen TFM to retry.".format(error)
            )
            return
        needle = self._search.text().strip().lower()
        row_by_id = {row["id"]: row for row in self._rows}
        self._category_list.blockSignals(True)
        self._category_list.setDragDropMode((QAbstractItemView.DragDropMode.NoDragDrop if PYQT6 else QAbstractItemView.NoDragDrop) if needle else (QAbstractItemView.DragDropMode.DragDrop if PYQT6 else QAbstractItemView.DragDrop))
        self._category_list.clear()
        self._category_items = {}
        self._filter_items = {}
        visible_ids = []
        for name, ids in self._categories.items():
            if needle and needle in name.lower():
                category_rows = [row_by_id[ident] for ident in ids if ident in row_by_id]
            else:
                category_rows = [row_by_id[ident] for ident in ids if ident in row_by_id
                                 and (not needle or needle in row_by_id[ident]["label"].lower() or needle in ident.lower())]
            category_rows = [row for row in category_rows if row["id"] in row_by_id]
            matching = [row for row in category_rows
                        if not needle or needle in name.lower() or needle in row["label"].lower() or needle in row["id"].lower()]
            if needle and needle not in name.lower() and not matching:
                continue
            expanded = bool(needle) or name not in self._collapsed_categories
            header = QListWidgetItem(("▾  " if expanded else "▸  ") + name)
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            header.setData(_ROLE, None)
            header.setData(_ROLE + 1, name)
            header.setFlags(header.flags() & ~item_is_user_checkable())
            self._category_list.addItem(header)
            self._category_items[name] = header
            for row in category_rows:
                ident = row["id"]
                if needle and needle not in name.lower() and needle not in row["label"].lower() and needle not in ident.lower():
                    continue
                enabled = ident in self._enabled
                item = QListWidgetItem(row["label"])
                item.setData(_ROLE, ident)
                item.setData(_ROLE + 1, name)
                item.setToolTip(row["description"])
                flags = item.flags() | item_is_user_checkable()
                editable = getattr(Qt.ItemFlag, "ItemIsEditable", None)
                if editable is None:
                    editable = getattr(Qt, "ItemIsEditable", None)
                if editable is not None:
                    flags = flags & ~editable
                item.setFlags(flags)
                item.setCheckState(checked_state() if enabled else unchecked_state())
                self._style_filter_item(item, enabled)
                self._category_list.addItem(item)
                item.setHidden(not expanded)
                self._filter_items[ident] = item
                if expanded:
                    visible_ids.append(ident)
        if selected_id in visible_ids:
            selected = self._filter_items[selected_id]
            self._category_list.setCurrentItem(selected)
            self._category_list.scrollToItem(selected)
        elif visible_ids:
            first = self._filter_items[visible_ids[0]]
            self._category_list.setCurrentItem(first)
            self._category_list.scrollToItem(first)
        elif self._category_list.count():
            self._category_list.setCurrentRow(0)
        self._category_list.blockSignals(False)
        self._show_selected()

    def _show_selected(self, *args):
        item = self._category_list.currentItem()
        row = next((entry for entry in self._rows if item is not None and item.data(_ROLE) is not None and entry["id"] == item.data(_ROLE)), None)
        self._show_parameters(row["id"] if row else None)
        if row is None:
            self._detail.clear()
            return
        lines = ["<h2>{}</h2>".format(row["label"]),
                 "<p>{}</p>".format(row["description"]),
                 "<p><b>Status:</b> {}<br><b>Category:</b> {}<br><b>ID:</b> {}</p>".format(
                     "registered" if row["registered"] else "missing",
                     item.data(_ROLE + 1) if item else row["category"], row["id"])]
        if row.get("settings"):
            lines.append("<p><b>Filter parameters</b></p><ul>")
            for spec in row["settings"]:
                kind = spec.get("type", "value")
                value = "action" if kind == "action" else ("default {}".format(spec["default"]) if "default" in spec else "manual control")
                bounds = " ({}–{})".format(spec["min"], spec["max"]) if "min" in spec and "max" in spec else ""
                lines.append("<li>{} — {}{}</li>".format(spec["label"], value, bounds))
            lines.append("</ul>")
        self._detail.setHtml("".join(lines))

    def _show_parameters(self, ident):
        specs = FILTER_DEFAULT_SPECS.get(ident, [])
        self._restore_defaults.setEnabled(bool(specs))
        container = QWidget()
        form = QFormLayout(container)
        self._parameter_controls = {}
        values = self._pending["filter_defaults"].get(ident, {})
        for spec in specs:
            key = spec["key"]
            value = values.get(key, spec["default"])
            if "options" in spec:
                control = QComboBox()
                for option in spec["options"]:
                    val, label = option if isinstance(option, (list, tuple)) else (option, option.title())
                    control.addItem(label, val)
                control.setCurrentIndex(max(0, control.findData(value)))
                control.currentIndexChanged.connect(lambda _index, i=ident, k=key, c=control: self._set_default(i, k, c.currentData()))
            elif isinstance(spec["default"], bool):
                control = QCheckBox()
                control.setChecked(value)
                control.toggled.connect(lambda v, i=ident, k=key: self._set_default(i, k, v))
            else:
                control = QDoubleSpinBox()
                control.setDecimals(0 if spec.get("type") == "integer" else 4)
                control.setRange(spec["min"], spec["max"])
                control.setSingleStep(1 if spec.get("type") == "integer" else 0.01)
                control.setValue(value)
                control.valueChanged.connect(lambda v, i=ident, k=key: self._set_default(i, k, v))
            control.setObjectName("default_" + key)
            self._parameter_controls[key] = control
            form.addRow(spec["label"], control)
        if not specs:
            form.addRow(QLabel("No editable defaults for this filter."))
        self._parameter_scroll.setWidget(container)

    def _set_default(self, ident, key, value):
        self._pending["filter_defaults"].setdefault(ident, {})[key] = value

    def _restore_selected_defaults(self):
        item = self._category_list.currentItem()
        if item is not None and item.data(_ROLE) is not None:
            ident = item.data(_ROLE)
            self._pending["filter_defaults"].pop(ident, None)
            self._show_parameters(ident)

    def _enabled_changed(self, item):
        ident = item.data(_ROLE)
        if ident is None:
            return
        enabled = item.checkState() == checked_state()
        if enabled:
            self._enabled.add(ident)
        else:
            self._enabled.discard(ident)
        self._style_filter_item(item, enabled)

    def _current_category(self):
        item = self._category_list.currentItem()
        category = item.data(_ROLE + 1) if item is not None else None
        return category if category in self._categories else next(iter(self._categories))

    def _category_selected(self, current, _previous=None):
        self._show_selected()

    def _toggle_category(self, item):
        if item is None or item.data(_ROLE) is not None:
            return
        name = item.data(_ROLE + 1)
        if not name:
            return
        if self._search.text().strip():
            return
        if name in self._collapsed_categories:
            self._collapsed_categories.remove(name)
        else:
            self._collapsed_categories.add(name)
        expanded = name not in self._collapsed_categories
        item.setText(("▾  " if expanded else "▸  ") + name)
        for ident in self._categories[name]:
            child = self._filter_items.get(ident)
            if child is not None:
                child.setHidden(not expanded)

    def _categories_moved(self, *args):
        names = [self._category_list.item(i).data(_ROLE + 1) for i in range(self._category_list.count())
                 if self._category_list.item(i).data(_ROLE) is None]
        ordered = {name: self._categories[name] for name in names if name in self._categories}
        ordered.update((name, ids) for name, ids in self._categories.items() if name not in ordered)
        self._categories = ordered

    def _reorder_filters(self, category):
        visible = [self._category_list.item(i).data(_ROLE) for i in range(self._category_list.count())
                   if self._category_list.item(i).data(_ROLE + 1) == category
                   and self._category_list.item(i).data(_ROLE) in self._managed]
        old = self._categories[category]
        iterator = iter(visible)
        self._categories[category] = [next(iterator) if ident in visible else ident for ident in old]

    def _move_filter(self, ident, target):
        if ident not in self._managed or target not in self._categories:
            return False
        for ids in self._categories.values():
            while ident in ids:
                ids.remove(ident)
        self._categories[target].append(ident)
        self._reload()
        return True

    def _category_menu(self, pos):
        item = self._category_list.itemAt(pos)
        if item is None or item.data(_ROLE) is None:
            return
        self._category_list.setCurrentItem(item)
        ident = item.data(_ROLE)
        menu = QMenu(self)
        submenu = menu.addMenu("Move to category")
        moves = {submenu.addAction(name): name for name in self._categories if name != item.data(_ROLE + 1)}
        if not moves:
            return
        action = (menu.exec if PYQT6 else menu.exec_)(self._category_list.viewport().mapToGlobal(pos))
        if action in moves:
            self._move_filter(ident, moves[action])

    def _filter_menu(self, pos):
        return self._category_menu(pos)

    def save_filters(self):
        catalog_ids = {entry["id"] for entry in FILTERS}
        self._managed = set(catalog_ids)
        self._pending.update({
            "managed_filters": list(dict.fromkeys(
                ident for ids in self._categories.values() for ident in ids if ident in catalog_ids)),
            "filter_categories": {name: list(ids) for name, ids in self._categories.items()},
            "enabled_filters": [ident for ident in self._enabled if ident in catalog_ids],
        })
        values = {key: self._pending[key] for key in
                  ("managed_filters", "filter_categories", "enabled_filters", "filter_defaults")}
        if settings.save(values):
            self._saved_filter_state = self._filter_state()
            self._status.setText(
                "Filter settings saved. Restart Krita for enable/disable changes to apply in the Filter menu.")
        else:
            self._status.setText("Could not save TFM filter settings.")


def show_dialog(parent=None):
    dialog = FxManagerDialog(parent)
    return exec_(dialog)
