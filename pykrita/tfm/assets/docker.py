"""Asset Library panel UI and compatible exports."""
from .panel_context import *  # noqa: F403
from .library_view import LibraryViewMixin
from .asset_operations import AssetOperationsMixin
from .drag_drop import AssetDragDropMixin

class AssetLibraryDocker(LibraryViewMixin, AssetOperationsMixin, AssetDragDropMixin, DockWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("Asset Library", "资产库"))
        from ..manager import assets_directory
        try:
            self._root = store.ensure_assets(assets_directory())
        except OSError:
            self._root = store.ensure_assets(store.default_assets_dir())
        self._directories = DirectoryCatalog(self._root)
        self._thumb_service = ThumbnailService(self, describe=asset_tooltip)
        self._thumb_service.ready.connect(self._thumbnail_ready)
        self._thumb_generation = 0
        self._thumb_items = {}
        self._grid_folder = None
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(0)
        self._thumb_timer.timeout.connect(self._fill_pending_thumbs)
        self.destroyed.connect(self._thumb_service.close)
        self._dragging = False
        self._pending = None
        self._loading = False
        self._browsed = ""
        self._edit_marker = None
        self._status_backup = ""

        widget = DropPane(self)
        widget.setMinimumSize(260, 180)
        widget.setToolTip(tr(
            "Drop a layer here to store it. "
            "Double-click a thumbnail to place it as a paint layer. "
            "Ctrl+double-click to rename. Right-click for Place as Reference. "
            "Drag a thumbnail onto the canvas or the Layers docker to place it. "
            "Hold Ctrl and scroll over the images to resize them.",
            "将图层拖到这里保存。"
            "双击缩略图放置为绘制图层。"
            "Ctrl+双击重命名。右键可放置为参考图。"
            "把缩略图拖到画布或图层面板即可放置。"
            "在缩略图上按住 Ctrl 并滚轮可调整大小。",
        ))
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.tree = FolderTree(self)
        self.tree.itemExpanded.connect(self._expand_folder)
        grid_host = QtWidgets.QWidget(self)
        grid_host_layout = QVBoxLayout(grid_host)
        grid_host_layout.setContentsMargins(0, 0, 0, 0)
        grid_host_layout.setSpacing(0)
        self.grid = ImageGrid(self)
        self.grid.verticalScrollBar().valueChanged.connect(lambda _: self._thumb_timer.start())
        self.grid.set_icon_edge(self._saved_icon_edge())
        self.grid.set_list_icon(self._saved_list_icon())
        grid_host_layout.addWidget(self.grid)
        self.grid_empty = make_empty_state(
            grid_host,
            tr("Drop a layer or image here\nto store it in this folder.",
               "把图层或图片拖到这里\n保存到当前文件夹。"),
        )
        self.grid_empty.hide()
        self.grid.installEventFilter(self)

        right = QtWidgets.QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)
        right_layout.addWidget(grid_host, 1)
        right_layout.addWidget(self._build_view_mode_bar())

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.tree)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([150, 420])
        layout.addWidget(splitter, 1)
        self._status = QLabel("")
        apply_muted_label(self._status)
        self._status.setObjectName("tfm_assets_status")
        layout.addWidget(self._status)
        self.setWidget(widget)
        self._reload(self._saved_folder())
        _install_drop_filter(self)
        QTimer.singleShot(0, self._hide_when_disabled)

    def _build_view_mode_bar(self):
        bar = QtWidgets.QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        from ..ui_chrome import standard_icon
        self._view_thumb = QtWidgets.QToolButton()
        self._view_thumb.setCheckable(True)
        self._view_thumb.setAutoRaise(True)
        self._view_thumb.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self._view_thumb.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        thumb_icon = standard_icon(self, "SP_FileDialogListView")
        if not thumb_icon.isNull():
            self._view_thumb.setIcon(thumb_icon)
        self._view_thumb.setText(tr("Thumbs", "缩略图"))
        self._view_thumb.setToolTip(tr("Thumbnail view", "缩略图视图"))
        self._view_list = QtWidgets.QToolButton()
        self._view_list.setCheckable(True)
        self._view_list.setAutoRaise(True)
        self._view_list.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self._view_list.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        list_icon = standard_icon(self, "SP_FileDialogDetailedView")
        if not list_icon.isNull():
            self._view_list.setIcon(list_icon)
        self._view_list.setText(tr("List", "列表"))
        self._view_list.setToolTip(tr("List view", "列表视图"))
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
        self._thumb_service.reset()
        self._directories = DirectoryCatalog(self._root)
        folder = self._current_folder()
        try:
            if not os.path.isdir(store._folder(self._root,folder)):
                folder = ''
        except store.AssetError:
            folder = ''
        self.tree.clear()
        self._reload(folder)

    def _set_status(self, text):
        message = "" if text is None else str(text)
        self._status.setText(message)
        self._status.setToolTip(message)

    def _remember_status(self, text):
        self._status_backup = self._status.text()
        self._set_status(text)

    def _restore_status(self):
        self._set_status(self._status_backup)



















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

    def _saved_list_icon(self):
        try:
            value = int(Krita.instance().readSetting("TFM", "assets_list_size", str(LIST_DEFAULT)))
        except (TypeError, ValueError, AttributeError):
            return LIST_DEFAULT
        return max(LIST_MIN, min(LIST_MAX, value))

    def _remember_list_icon(self, edge):
        self._pending_list_icon = int(edge)
        timer = getattr(self, "_list_icon_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._write_list_icon)
            self._list_icon_timer = timer
        timer.start(300)

    def _write_list_icon(self):
        edge = getattr(self, "_pending_list_icon", None)
        if edge is None:
            return
        try:
            Krita.instance().writeSetting("TFM", "assets_list_size", str(int(edge)))
        except Exception:
            pass

    def _saved_view_mode(self, folder):
        mode = self._read_view_modes().get(folder or "")
        return mode if mode in (VIEW_THUMB, VIEW_LIST) else VIEW_THUMB

    def _remember_view_mode(self, mode):
        folder = self._current_folder() or ""
        modes = self._read_view_modes()
        modes[folder] = VIEW_LIST if mode == VIEW_LIST else VIEW_THUMB
        self._write_view_modes(modes)

    def _retarget_view_modes(self, old, new):
        if not old or old == new:
            return
        modes = self._read_view_modes()
        prefix = old + "/"
        updated = {}
        changed = False
        for key, mode in modes.items():
            if key == old:
                updated[new] = mode
                changed = True
            elif key.startswith(prefix):
                updated[new + key[len(old):]] = mode
                changed = True
            else:
                updated[key] = mode
        if changed:
            self._write_view_modes(updated)

    def _forget_view_modes(self, folder):
        if not folder:
            return
        modes = self._read_view_modes()
        prefix = folder + "/"
        updated = {
            key: mode
            for key, mode in modes.items()
            if key != folder and not key.startswith(prefix)
        }
        if len(updated) != len(modes):
            self._write_view_modes(updated)

    def _read_view_modes(self):
        try:
            raw = Krita.instance().readSetting("TFM", "assets_view_modes", "")
        except Exception:
            return {}
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        modes = {}
        for key, value in data.items():
            if value in (VIEW_THUMB, VIEW_LIST):
                modes[str(key)] = value
        return modes

    def _write_view_modes(self, modes):
        try:
            Krita.instance().writeSetting(
                "TFM",
                "assets_view_modes",
                json.dumps(modes, sort_keys=True),
            )
        except Exception:
            pass



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
        item = self.tree.currentItem()
        kind = _item_kind(item)
        before = None
        if kind == "folder":
            parent = item.data(0, Qt.ItemDataRole.UserRole) or ""
        elif kind in ("separator", "title"):
            parent = _parent_rel(item)
            nxt = _next_sibling(self.tree, item)
            before = _node_ref(nxt) if nxt is not None else None
        else:
            parent = ""
        try:
            rel = store.create_folder(self._root, parent, "New Folder")
            if kind in ("separator", "title"):
                rel = store.relocate_node(self._root, "folder", rel, parent, before)
        except store.AssetError as error:
            self._tell(str(error))
            return
        self._reload(rel)

    def _new_marker(self, kind):
        item = self.tree.currentItem()
        if item is None:
            parent = ""
            before = None
        else:
            parent = _parent_rel(item)
            nxt = _next_sibling(self.tree, item)
            before = _node_ref(nxt) if nxt is not None else None
        try:
            entry = store.insert_marker(self._root, parent, kind, before, tr("Title", "标题"))
        except store.AssetError as error:
            self._tell(str(error))
            return
        if kind == "title":
            self._edit_marker = entry["id"]
        self._reload(self._browsed)

    def _delete_folder(self):
        item = self.tree.currentItem()
        kind = _item_kind(item)
        if kind in ("separator", "title"):
            marker_id = item.data(0, _ID_ROLE) or ""
            if kind == "title":
                message = 'Delete the title "{}"?'.format(item.text(0))
            else:
                message = "Delete this separator?"
            if not self._confirm(message):
                return
            try:
                store.remove_marker(self._root, marker_id)
            except store.AssetError as error:
                self._tell(str(error))
                return
            self._reload(self._browsed)
            return
        rel = self._current_folder()
        if not rel:
            self._set_status(tr("Select a folder first.", "请先选择文件夹。"))
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
        self._forget_view_modes(rel)
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
        kind = _item_kind(item)
        rel = item.data(0, Qt.ItemDataRole.UserRole) or "" if kind == "folder" else ""
        menu = QMenu(self)
        add_menu = menu.addMenu(tr("Add", "添加"))
        add_menu.addAction(tr("Add Folder", "添加文件夹"), self._new_folder)
        add_menu.addAction(tr("Add Separator", "添加分隔符"), lambda: self._new_marker("separator"))
        add_menu.addAction(tr("Add Title", "添加标题"), lambda: self._new_marker("title"))
        rename = menu.addAction(tr("Rename", "重命名"), self._begin_rename)
        delete = menu.addAction(tr("Delete", "删除"), self._delete_folder)
        rename.setEnabled(kind == "title" or bool(rel))
        delete.setEnabled(kind in ("separator", "title") or bool(rel))
        exec_(menu, self.tree.mapToGlobal(pos))

    def _begin_rename(self):
        item = self.tree.currentItem()
        if item is None or _item_kind(item) == "separator":
            return
        self.tree.editItem(item, 0)

    def _folder_renamed(self, item, column):
        if self._loading or column != 0:
            return
        if _item_kind(item) == "title":
            self._title_edited(item)
            return
        if _item_kind(item) == "separator":
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
        self._retarget_view_modes(rel, renamed)
        QTimer.singleShot(0, lambda renamed=renamed, label=label: self._reload(
            renamed, status='Renamed to "{}".'.format(label)))

    def _title_edited(self, item):
        marker_id = item.data(0, _ID_ROLE) or ""
        previous = item.data(0, _LABEL_ROLE) or ""
        text = item.text(0).strip()
        if not marker_id or not text or text == previous:
            if previous and item.text(0) != previous:
                self._loading = True
                item.setText(0, previous)
                self._loading = False
            return
        try:
            cleaned = store.rename_title(self._root, marker_id, text)
        except store.AssetError as error:
            self._loading = True
            item.setText(0, previous)
            self._loading = False
            self._tell(str(error))
            return
        self._loading = True
        item.setText(0, cleaned)
        item.setData(0, _LABEL_ROLE, cleaned)
        self._loading = False


    def _saved_folder(self):
        try:
            rel = Krita.instance().readSetting("TFM", "assets_last_folder", "") or ""
        except Exception:
            return ""
        rel = str(rel).replace("\\", "/").strip("/")
        if not rel:
            return ""
        try:
            return rel if os.path.isdir(store._folder(self._root,rel)) else ""
        except store.AssetError:
            return ""

    def _remember_folder(self, folder):
        folder = (folder or "").replace("\\", "/").strip("/")
        if folder == getattr(self, "_remembered_folder", None):
            return
        self._remembered_folder = folder
        try:
            Krita.instance().writeSetting("TFM", "assets_last_folder", folder)
        except Exception:
            pass

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
























