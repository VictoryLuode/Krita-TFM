"""LibraryViewMixin; original docker method names remain available through inheritance."""
from .panel_context import *  # shared Qt/asset dependencies


class LibraryViewMixin:
    def _current_folder(self):
        item = self.tree.currentItem()
        if _item_kind(item) == "folder":
            return item.data(0, Qt.ItemDataRole.UserRole) or ""
        return self._browsed

    def _folder_changed(self):
        if self._loading:
            return
        item = self.tree.currentItem()
        if _item_kind(item) != "folder":
            return
        self._browsed = item.data(0, Qt.ItemDataRole.UserRole) or ""
        self._remember_folder(self._browsed)
        self._fill_grid(None)

    def _reload(self, folder, select_image=None, status=None):
        self._fill_tree(folder)
        self._fill_grid(select_image)
        if status is not None:
            self._set_status(status)

    def _fill_tree(self, folder):
        was_empty = self.tree.topLevelItemCount() == 0
        expanded = set()
        if not was_empty:
            self._collect_expanded(None, expanded)
        keep_open = expanded | _ancestors(folder)
        self._browsed = folder or ""
        self._loading = True
        self.tree.blockSignals(True)
        edit_item = None
        try:
            self.tree.forget_highlight()
            self._add_tree_level(None, "", was_empty, keep_open)
            current = self._find_folder_item(folder) if folder else None
            if folder and current is None:
                self._browsed = ""
            self._remember_folder(self._browsed)
            edit_id = self._edit_marker
            self._edit_marker = None
            if edit_id:
                edit_item = self._find_marker_item(edit_id)
            if edit_item is not None:
                self.tree.setCurrentItem(edit_item)
                self.tree.scrollToItem(edit_item)
            elif current is not None:
                self.tree.setCurrentItem(current)
                self.tree.scrollToItem(current)
            else:
                self.tree.clearSelection()
                self.tree.setCurrentItem(None)
        finally:
            self.tree.blockSignals(False)
            self._loading = False
        if edit_item is not None:
            QTimer.singleShot(0, lambda item=edit_item: self.tree.editItem(item, 0))

    def _expand_folder(self, item):
        if self._loading or _item_kind(item) != 'folder':
            return
        self._loading = True
        self.tree.blockSignals(True)
        try:
            self._add_tree_level(item,item.data(0,Qt.ItemDataRole.UserRole),False,set())
        finally:
            self.tree.blockSignals(False)
            self._loading = False

    def _add_tree_level(self, parent_item, parent_rel, was_empty, keep_open):
        parent = parent_item or self.tree.invisibleRootItem()
        entries = self._directories.children(parent_rel)
        def identity(item):
            kind = _item_kind(item)
            return kind, item.data(0,Qt.ItemDataRole.UserRole) if kind == 'folder' else item.data(0,_ID_ROLE)
        existing = {identity(parent.child(i)): parent.child(i) for i in range(parent.childCount())}
        wanted = []
        for entry in entries:
            kind = entry['type']
            rel = ('{}/{}'.format(parent_rel,entry['name']) if parent_rel else entry['name']) if kind == 'folder' else ''
            key = kind, rel if kind == 'folder' else entry['id']
            item = existing.pop(key,None)
            if item is None:
                item = QTreeWidgetItem()
            text = entry['name'] if kind == 'folder' else '' if kind == 'separator' else entry.get('text') or tr('Title','标题')
            item.setText(0,text)
            item.setData(0,Qt.ItemDataRole.UserRole,rel)
            item.setData(0,_KIND_ROLE,kind)
            item.setData(0,_LABEL_ROLE,text)
            item.setData(0,_ID_ROLE,entry.get('id',''))
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled
            if kind != 'separator':
                flags |= Qt.ItemFlag.ItemIsEditable
            item.setFlags(flags)
            if kind == 'separator':
                item.setSizeHint(0,QSize(0,14))
            wanted.append(item)
        for item in existing.values():
            parent.takeChild(parent.indexOfChild(item))
        for index,item in enumerate(wanted):
            current = parent.indexOfChild(item)
            if current != index:
                if current >= 0:
                    parent.takeChild(current)
                parent.insertChild(index,item)
            if _item_kind(item) == 'folder':
                rel = item.data(0,Qt.ItemDataRole.UserRole)
                # The arrow is cheap; enumerate children only on expansion.
                item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
                opened = item.isExpanded() or rel in keep_open
                if opened:
                    self._add_tree_level(item,rel,False,keep_open)
                item.setExpanded(opened)
        if parent_item is not None:
            policy = QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator if wanted else QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator
            parent_item.setChildIndicatorPolicy(policy)

    def _find_folder_item(self, rel):
        return self._find_tree_item(lambda item: _item_kind(item) == "folder" and (item.data(0, Qt.ItemDataRole.UserRole) or "") == rel)

    def _find_marker_item(self, marker_id):
        return self._find_tree_item(lambda item: (item.data(0, _ID_ROLE) or "") == marker_id)

    def _find_tree_item(self, match, parent=None):
        count = self.tree.topLevelItemCount() if parent is None else parent.childCount()
        for index in range(count):
            item = self.tree.topLevelItem(index) if parent is None else parent.child(index)
            if match(item):
                return item
            found = self._find_tree_item(match, item)
            if found is not None:
                return found
        return None

    def _collect_expanded(self, item, found):
        if item is None:
            for index in range(self.tree.topLevelItemCount()):
                self._collect_expanded(self.tree.topLevelItem(index), found)
            return
        if item.isExpanded() and _item_kind(item) == "folder":
            found.add(item.data(0, Qt.ItemDataRole.UserRole) or "")
        for index in range(item.childCount()):
            self._collect_expanded(item.child(index), found)

    def _fill_grid(self, select_image):
        folder = self._current_folder()
        restore_scroll = (self.grid.verticalScrollBar().value()
                          if folder == self._grid_folder and select_image is None else None)
        self._apply_view_mode(self._saved_view_mode(folder), persist=False)
        self._loading = True
        self.grid.blockSignals(True)
        try:
            self._fill_grid_items(folder, select_image, restore_scroll)
        finally:
            self.grid.blockSignals(False)
            self._loading = False

    def _fill_grid_items(self, folder, select_image, restore_scroll=None):
        same_folder = folder == self._grid_folder
        explicit_selection = select_image is not None
        if same_folder and select_image is None and self.grid.currentItem() is not None:
            select_image = self.grid.currentItem().data(Qt.ItemDataRole.UserRole)
        selected = set(self._selected_rels()) if same_folder else set()
        scroll = self.grid.verticalScrollBar().value() if same_folder else 0
        if restore_scroll is not None:
            scroll = restore_scroll
        self._grid_folder = folder
        self._thumb_generation = self._thumb_service.reset()
        self._thumb_items.clear()
        self.grid.clear()
        chosen = None
        try:
            names = store.list_images(self._root, folder)
        except store.AssetError:
            names = []
        if not names:
            self._set_status(tr(
                "This folder is empty. Drop a layer or image here to store it.",
                "此文件夹为空。将图层或图片拖到这里即可保存。",
            ))
        for name in names:
            rel = "{}/{}".format(folder, name) if folder else name
            try:
                path = store.image_path(self._root, rel)
            except store.AssetError:
                continue
            item = QListWidgetItem(os.path.splitext(name)[0])
            item.setData(Qt.ItemDataRole.UserRole, rel)
            item.setData(Qt.ItemDataRole.UserRole + 20, path)
            item.setToolTip(os.path.splitext(name)[0])
            item.setTextAlignment(self.grid._item_alignment())
            item.setSizeHint(self.grid._item_size_hint())
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDragEnabled
                | Qt.ItemFlag.ItemIsEditable
            )
            self.grid.addItem(item)
            self._thumb_items[rel] = item
            if rel in selected:
                item.setSelected(True)
            if rel == select_image:
                chosen = item
        if chosen is not None:
            self.grid.setCurrentItem(chosen, QtCore.QItemSelectionModel.SelectionFlag.NoUpdate)
            chosen.setSelected(True)
            if explicit_selection:
                self.grid.scrollToItem(chosen)
        if not explicit_selection:
            self.grid.doItemsLayout()
            self.grid.verticalScrollBar().setValue(scroll)
        self._sync_grid_empty_state()
        self._thumb_timer.start()

    def _sync_grid_empty_state(self):
        empty = getattr(self, "grid_empty", None)
        if empty is None:
            return
        sync_empty_state(empty, self.grid.count() == 0)
        position_empty_state(empty, self.grid)

    def eventFilter(self, obj, event):
        if obj is getattr(self, "grid", None) and event.type() == QEvent.Type.Resize:
            position_empty_state(getattr(self, "grid_empty", None), self.grid)
            self._thumb_timer.start()
        return super().eventFilter(obj, event)

    def _fill_pending_thumbs(self):
        viewport = self.grid.viewport().rect()
        prefetch = viewport.adjusted(0,-viewport.height(),0,viewport.height())
        visible, adjacent = [], []
        edge = max(16,self.grid.iconSize().width())
        for rel,item in self._thumb_items.items():
            rect = self.grid.visualItemRect(item)
            path = item.data(Qt.ItemDataRole.UserRole + 20)
            entry = (rel,path,edge)
            if rect.intersects(viewport):
                visible.append(entry)
            elif rect.intersects(prefetch):
                adjacent.append(entry)
            else:
                # Item icons also own pixel memory; bound these to the viewport
                # neighbourhood instead of retaining one per visited asset.
                if not item.icon().isNull():
                    item.setIcon(QIcon())
        self._thumb_service.request(visible+adjacent)

    def _thumbnail_ready(self, payload):
        generation,rel,path,edge,key,result = payload
        if generation != self._thumb_generation or edge != self.grid.iconSize().width():
            return
        item = self._thumb_items.get(rel)
        if item is None or item.data(Qt.ItemDataRole.UserRole + 20) != path:
            return
        image,dimensions,error,description = result
        item.setIcon(QIcon(QPixmap.fromImage(image)))
        item.setToolTip(description + ('\n'+error if error else ''))

    def _icon(self, path):
        # Compatibility helper used by drag previews: never decode on the GUI.
        for item in self._thumb_items.values():
            if item.data(Qt.ItemDataRole.UserRole + 20) == path:
                return item.icon()
        return QIcon()

    def _tip(self, path, name):
        return asset_tooltip(path, name)

