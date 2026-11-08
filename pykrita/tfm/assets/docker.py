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
from ..i18n import tr
from ..ui_chrome import apply_muted_label, make_empty_state, position_empty_state, sync_empty_state

class AssetLibraryDocker(DockWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("Asset Library", "资产库"))
        from ..manager import assets_directory
        try:
            self._root = store.ensure_assets(assets_directory())
        except OSError:
            self._root = store.ensure_assets(store.default_assets_dir())
        self._thumbs = {}
        self._thumb_order = []
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
        grid_host = QtWidgets.QWidget(self)
        grid_host_layout = QVBoxLayout(grid_host)
        grid_host_layout.setContentsMargins(0, 0, 0, 0)
        grid_host_layout.setSpacing(0)
        self.grid = ImageGrid(self)
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
        self._thumbs.clear()
        folder = self._current_folder()
        try:
            known = set(store.list_folders(self._root))
        except store.AssetError:
            known = set()
        if folder not in known:
            folder = ""
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

    def _document(self):
        try:
            canvas = self.canvas()
        except Exception:
            canvas = None
        if canvas is not None:
            try:
                view = canvas.view()
                if view is not None and view.document() is not None:
                    return view.document()
            except Exception:
                pass
        try:
            return Krita.instance().activeDocument()
        except Exception:
            return None

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

    def _note_change(self, folder, select_image=None, status=None):
        if self._dragging:
            self._pending = (folder, select_image, status)
            return
        self._reload(folder, select_image, status)

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
            self.tree.clear()
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

    def _add_tree_level(self, parent_item, parent_rel, was_empty, keep_open):
        folder_flags = (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
            | Qt.ItemFlag.ItemIsEditable
        )
        marker_flags = (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        for entry in store.merged_children(self._root, parent_rel):
            parent = self.tree if parent_item is None else parent_item
            if entry["type"] == "folder":
                rel = "{}/{}".format(parent_rel, entry["name"]) if parent_rel else entry["name"]
                item = QTreeWidgetItem(parent, [entry["name"]])
                item.setData(0, Qt.ItemDataRole.UserRole, rel)
                item.setData(0, _KIND_ROLE, "folder")
                item.setData(0, _LABEL_ROLE, entry["name"])
                item.setFlags(folder_flags)
                item.setToolTip(0, "Double-click the name to rename it. Drag to reorder. Drop a layer or image here.")
                item.setExpanded(was_empty or rel in keep_open)
                self._add_tree_level(item, rel, was_empty, keep_open)
                continue
            if entry["type"] == "separator":
                item = QTreeWidgetItem(parent, [""])
                item.setData(0, Qt.ItemDataRole.UserRole, "")
                item.setData(0, _KIND_ROLE, "separator")
                item.setData(0, _ID_ROLE, entry["id"])
                item.setFlags(marker_flags)
                item.setSizeHint(0, QSize(0, 14))
                item.setToolTip(0, "Drag to reorder.")
                continue
            text = entry.get("text") or tr("Title", "标题")
            item = QTreeWidgetItem(parent, [text])
            item.setData(0, Qt.ItemDataRole.UserRole, "")
            item.setData(0, _KIND_ROLE, "title")
            item.setData(0, _ID_ROLE, entry["id"])
            item.setData(0, _LABEL_ROLE, text)
            item.setFlags(marker_flags | Qt.ItemFlag.ItemIsEditable)
            item.setToolTip(0, "A title is only a label. Double-click to edit it. Drag to reorder.")

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
        self._apply_view_mode(self._saved_view_mode(folder), persist=False)
        self._loading = True
        self.grid.blockSignals(True)
        try:
            self._fill_grid_items(folder, select_image)
        finally:
            self.grid.blockSignals(False)
            self._loading = False

    def _fill_grid_items(self, folder, select_image):
        self.grid.clear()
        self._pending_thumbs = []
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
            item.setToolTip(self._tip(path, name))
            item.setTextAlignment(self.grid._item_alignment())
            item.setSizeHint(self.grid._item_size_hint())
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDragEnabled
                | Qt.ItemFlag.ItemIsEditable
            )
            self.grid.addItem(item)
            self._pending_thumbs.append(item)
            if rel == select_image:
                chosen = item
        if chosen is not None:
            self.grid.setCurrentItem(chosen)
            chosen.setSelected(True)
            self.grid.scrollToItem(chosen)
        self._sync_grid_empty_state()
        QTimer.singleShot(0, self._fill_pending_thumbs)

    def _sync_grid_empty_state(self):
        empty = getattr(self, "grid_empty", None)
        if empty is None:
            return
        sync_empty_state(empty, self.grid.count() == 0)
        position_empty_state(empty, self.grid)

    def eventFilter(self, obj, event):
        if obj is getattr(self, "grid", None) and event.type() == QEvent.Type.Resize:
            position_empty_state(getattr(self, "grid_empty", None), self.grid)
        return super().eventFilter(obj, event)

    def _fill_pending_thumbs(self):
        pending = getattr(self, "_pending_thumbs", None) or []
        if not pending:
            return
        batch = pending[:24]
        self._pending_thumbs = pending[24:]
        for item in batch:
            path = item.data(Qt.ItemDataRole.UserRole + 20)
            if path:
                item.setIcon(self._icon(path))
        if self._pending_thumbs:
            QTimer.singleShot(0, self._fill_pending_thumbs)

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

    def _icon(self, path):
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            stamp = None
        key = (path, stamp)
        cached = self._thumbs.get(key)
        if cached is not None:
            try:
                self._thumb_order.remove(key)
            except ValueError:
                pass
            self._thumb_order.append(key)
            return cached
        icon = _thumbnail(path, THUMB_EDGE)
        self._thumbs[key] = icon
        self._thumb_order.append(key)
        while len(self._thumb_order) > 400:
            old = self._thumb_order.pop(0)
            self._thumbs.pop(old, None)
        return icon

    def _tip(self, path, name):
        lines = [os.path.splitext(name)[0]]
        sidecar = store.read_sidecar(path) or {}
        kind = sidecar.get("kind")
        if kind == filter_asset.KIND:
            filter_id = sidecar.get("filter") or "?"
            lines.append("Filter layer · {}".format(filter_id))
            lines.append("Saved as a filter preset (parameters included).")
        elif kind == group_asset.KIND:
            children = sidecar.get("children") or []
            lines.append("Layer group · {} item(s)".format(len(children)))
            skipped = sidecar.get("skipped") or []
            if skipped:
                lines.append("Skipped unsupported: {}".format(", ".join(skipped[:6])))
        elif kind == group_asset.PAINT_KIND:
            lines.append("Paint layer")
        else:
            size = _dimensions(path)
            if size is not None:
                lines.append("{} × {}".format(size[0], size[1]))
        masks = sidecar.get("masks") or []
        if masks:
            lines.append("Transparency mask × {}".format(len(masks)))
        meta = store.read_meta(path)
        if meta is not None:
            lines.append("Position {}, {}".format(meta[0], meta[1]))
        return "\n".join(lines)

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

    def _reorder_dropped(self, payload, slot):
        kind = payload.get("kind") or "folder"
        dest = slot.get("into") or slot.get("parent") or ""
        before = None if slot.get("into") else slot.get("before")
        try:
            if kind == "folder":
                old = payload.get("path") or ""
                new_rel = store.relocate_node(self._root, "folder", old, dest, before)
                if new_rel != old:
                    self._retarget_view_modes(old, new_rel)
                self._note_change(new_rel)
                return
            store.relocate_node(self._root, kind, payload.get("id") or "", dest, before)
            self._note_change(self._browsed)
        except store.AssetError as error:
            self._tell(str(error))

    def _saved_folder(self):
        try:
            rel = Krita.instance().readSetting("TFM", "assets_last_folder", "") or ""
        except Exception:
            return ""
        rel = str(rel).replace("\\", "/").strip("/")
        if not rel:
            return ""
        try:
            known = set(store.list_folders(self._root))
        except store.AssetError:
            return ""
        return rel if rel in known else ""

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

    def _active_view(self):
        try:
            window = Krita.instance().activeWindow()
            if window is None:
                return None
            return window.activeView()
        except Exception:
            return None

    def _host(self):
        try:
            window = Krita.instance().activeWindow()
            if window is None:
                return None
            return window.qwindow()
        except Exception:
            return None

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

    def _invert_transform(self, transform):
        inverted = transform.inverted()
        if isinstance(inverted, tuple):
            matrix, ok = inverted
            if not ok:
                raise ValueError("transform")
            return matrix
        return inverted

    def _widget_to_image(self, view, point):
        local = QPointF(point.x(), point.y())
        flake = self._invert_transform(view.flakeToCanvasTransform()).map(local)
        image = view.flakeToImageTransform().map(flake)
        return image.x(), image.y()

    def _drop_on_canvas(self, widget, local, mime):
        rels = asset_paths(mime)
        if not rels:
            return
        point = _canvas_local_point(widget, local)
        view = self._active_view()
        if view is None:
            self._tell("Open a document first.")
            return
        try:
            center = self._widget_to_image(view, point)
        except Exception:
            try:
                middle = view.canvas().preferredCenter()
                center = (middle.x(), middle.y())
            except Exception:
                self._tell("Could not place that image on the canvas.")
                return
        self._insert_rels(rels, center)

    def _insert_selected(self):
        self._insert_rels(self._selected_rels(), None, "paint")

    def _insert_selected_as_reference(self):
        self._insert_rels(self._selected_rels(), None, "reference")

    def _insert_image_item(self, item):
        rel = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if rel:
            self._insert_rels([rel], None, "paint")

    def _insert_rels(self, rels, center, mode="paint"):
        if not rels:
            self._tell("Select an image first.")
            return
        doc = self._document()
        if doc is None:
            self._tell("Open a document first.")
            return
        view = self._active_view()
        try:
            with _wait_cursor():
                for index, rel in enumerate(rels):
                    point = None if center is None else (center[0] + index * 16, center[1] + index * 16)
                    self._insert_one(doc, view, rel, mode, point)
        except store.AssetError as error:
            self._tell(str(error))
            return
        except Exception:
            self._tell("Could not insert that image.")
            return
        try:
            doc.refreshProjection()
            doc.waitForDone()
            doc.setModified(True)
        except Exception:
            pass

    def _insert_one(self, doc, view, rel, mode, center):
        path = store.image_path(self._root, rel)
        name = os.path.splitext(os.path.basename(path))[0]
        size = _dimensions(path)
        image = QImage(path)
        if size is None and not image.isNull():
            size = (image.width(), image.height())
        width = size[0] if size else 0
        height = size[1] if size else 0
        x, y = self._top_left(doc, view, width, height, center)
        if mode == "reference":
            self._insert_reference(path, x, y)
            return
        parent, above = _insertion_point(doc)
        if parent is None:
            raise store.AssetError("Open a document first.")
        sidecar = store.read_sidecar(path) or {}
        kind = sidecar.get("kind")
        if kind == filter_asset.KIND:
            node = filter_asset.create_layer(doc, name, sidecar, parent, above)
            try:
                doc.setActiveNode(node)
            except Exception:
                pass
            return
        if kind == group_asset.KIND:
            node = group_asset.create_layer(doc, name, sidecar, parent, above)
            try:
                doc.setActiveNode(node)
            except Exception:
                pass
            return
        if kind == group_asset.PAINT_KIND:
            node = group_asset.create_paint_layer(doc, name, sidecar, parent, above)
            try:
                doc.setActiveNode(node)
            except Exception:
                pass
            return
        if not self._can_bake(doc, path):
            raise store.AssetError("That image can only be placed in an RGBA 8-bit or 16-bit document.")
        if image.isNull():
            image = QImage(path)
        if image.isNull():
            raise store.AssetError("Could not read that image.")
        if width * height > MAX_BAKE_PIXELS:
            raise store.AssetError("That image is too large to place as a paint layer.")
        payload = pixels.paint_bytes(image, doc.colorDepth())
        if not payload or payload[1] < 1:
            raise store.AssetError("Could not write the image into a layer.")
        raw, width, height = payload
        x, y = self._top_left(doc, view, width, height, center)
        node = doc.createNode(name, "paintlayer")
        if node is None:
            raise store.AssetError("Could not create a paint layer.")
        if not node.setPixelData(pixels.qbytearray_from(raw), x, y, width, height):
            raise store.AssetError("Could not write the image into a layer.")
        if not parent.addChildNode(node, above):
            raise store.AssetError("Could not add the layer.")
        try:
            doc.setActiveNode(node)
        except Exception:
            pass

    def _top_left(self, doc, view, width, height, center):
        if center is not None:
            return int(round(center[0] - width / 2.0)), int(round(center[1] - height / 2.0))
        try:
            if view is not None:
                middle = view.canvas().preferredCenter()
                return int(round(middle.x() - width / 2.0)), int(round(middle.y() - height / 2.0))
        except Exception:
            pass
        return (doc.width() - width) // 2, (doc.height() - height) // 2

    def _insert_reference(self, path, x, y):
        image = QImage(path)
        if image.isNull():
            raise store.AssetError("Could not read that image.")
        QApplication.clipboard().setImage(image)
        host = self._host()
        tool = self._reference_tool(host)
        if tool is None:
            raise store.AssetError("Could not create a reference image.")
        QtCore.QMetaObject.invokeMethod(tool, "pasteReferenceImage")
        self._move_reference(host, x, y)
        QTimer.singleShot(0, lambda host=host, x=x, y=y: self._move_reference(host, x, y))

    def _reference_tool(self, host):
        tool = self._find_reference_tool(host)
        if tool is not None:
            return tool
        app = Krita.instance()
        for name in ("ToolReferenceImages", "KritaShape/ToolReferenceImages"):
            try:
                action = app.action(name)
            except Exception:
                action = None
            if action is not None:
                action.trigger()
                break
        return self._find_reference_tool(host)

    def _find_reference_tool(self, host):
        if host is None:
            return None
        try:
            found = host.findChildren(QObject, "ToolReferenceImages")
        except Exception:
            return None
        return found[0] if found else None

    def _move_reference(self, host, x, y):
        view = self._active_view()
        if host is None or view is None:
            return
        try:
            image = QPointF(x, y)
            flake = self._invert_transform(view.flakeToImageTransform()).map(image)
            document = view.flakeToDocumentTransform().map(flake)
        except Exception:
            return
        xbox = host.findChild(QtWidgets.QWidget, "positionXSpinBox")
        ybox = host.findChild(QtWidgets.QWidget, "positionYSpinBox")
        if xbox is None or ybox is None:
            return
        for box, value in ((xbox, document.x()), (ybox, document.y())):
            changer = getattr(box, "changeValue", None)
            if changer is not None:
                changer(float(value))
            else:
                box.setValue(float(value))

    def _can_bake(self, doc, path):
        try:
            model = doc.colorModel()
            depth = doc.colorDepth()
        except Exception:
            return False
        if model != "RGBA" or depth not in ("U8", "U16"):
            return False
        size = _dimensions(path)
        if size is None:
            return True
        return size[0] * size[1] <= MAX_BAKE_PIXELS

    def _drop_on_folder(self, folder, mime):
        kind = drop_kind(mime)
        if kind == "folder":
            self._move_dropped_folder(folder, mime)
            return
        if not folder:
            self._need_folder()
            return
        if kind == "asset":
            self._move_asset_items(folder, mime)
        elif kind == "files":
            self._import_paths(folder, _local_images(mime))
        elif kind == "image":
            self._save_dropped_image(folder, mime)

    def _save_active_asset(self):
        folder = self._need_folder()
        if not folder:
            return
        doc = self._document()
        if doc is None:
            self._tell("Open a document first.")
            return
        try:
            node = doc.activeNode()
        except Exception:
            node = None
        if node is None:
            self._tell("Select a layer first.")
            return
        if filter_asset.is_filter_layer(node):
            self._persist_structured_asset(
                folder, node, doc, filter_asset.capture, filter_asset.preview_image, "Filter")
            return
        if group_asset.is_group_layer(node):
            self._persist_structured_asset(
                folder,
                node,
                doc,
                lambda current, document=doc: group_asset.capture(
                    current, document, pixel_budget=MAX_BAKE_PIXELS),
                group_asset.preview_image,
                "Group",
            )
            return
        if mask_asset.has_transparency_mask(node):
            self._persist_structured_asset(
                folder,
                node,
                doc,
                lambda current, document=doc: group_asset.capture_paint(
                    current, document, pixel_budget=MAX_BAKE_PIXELS),
                lambda current, edge=THUMB_EDGE: filter_asset.preview_image(current, edge),
                "Layer",
            )
            return
        try:
            bounds = node.bounds()
        except Exception:
            self._tell("This layer cannot be saved.")
            return
        if bounds.isEmpty() or bounds.width() < 1 or bounds.height() < 1:
            self._tell("The active layer has no pixels to save.")
            return
        try:
            path = store.new_image_path(self._root, folder, node.name() or "Layer")
        except store.AssetError as error:
            self._tell(str(error))
            return
        try:
            with _wait_cursor():
                image = _projection_image(node, doc, bounds)
                if image is not None:
                    write_png(image, path)
                else:
                    saved = node.save(path, doc.xRes() or 1.0, doc.yRes() or 1.0, InfoObject(), bounds)
                    if not saved:
                        raise store.AssetError("Krita could not export this layer.")
        except store.AssetError as error:
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            self._tell(str(error))
            return
        except Exception:
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            self._tell("Krita could not export this layer.")
            return
        try:
            store.write_meta(path, bounds.x(), bounds.y())
        except (OSError, ValueError, store.AssetError):
            pass
        rel = store.relative_path(self._root, path)
        self._reload(folder, rel)

    def _persist_structured_asset(self, folder, node, doc, capture, preview, fallback_name):
        try:
            payload = capture(node)
        except store.AssetError as error:
            self._tell(str(error))
            return
        try:
            path = store.new_image_path(self._root, folder, node.name() or fallback_name)
        except store.AssetError as error:
            self._tell(str(error))
            return
        try:
            with _wait_cursor():
                image = preview(node, THUMB_EDGE)
                try:
                    bounds = node.bounds()
                except Exception:
                    bounds = None
                if (
                    bounds is not None
                    and not bounds.isEmpty()
                    and bounds.width() >= 1
                    and bounds.height() >= 1
                    and bounds.width() * bounds.height() <= MAX_BAKE_PIXELS
                ):
                    projection = _projection_image(node, doc, bounds)
                    if projection is not None and not projection.isNull():
                        image = projection
                write_png(image, path)
                store.write_sidecar(path, payload)
        except store.AssetError as error:
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            self._tell(str(error))
            return
        except Exception:
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            sidecar = path + ".json"
            if os.path.isfile(sidecar):
                try:
                    os.remove(sidecar)
                except OSError:
                    pass
            self._tell("Could not save that layer.")
            return
        rel = store.relative_path(self._root, path)
        self._reload(folder, rel)

    def _move_dropped_folder(self, dest, mime):
        rel = folder_rel_from_mime(mime)
        if not rel:
            self._set_status(tr("That folder is not in the asset library.", "该文件夹不在资产库中。"))
            return
        try:
            moved = store.move_folder(self._root, rel, dest)
        except store.AssetError as error:
            self._set_status(str(error))
            return
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        if moved == rel and parent == (dest or ""):
            self._set_status(tr("Nothing was moved.", "没有移动任何内容。"))
            return
        if moved != rel:
            self._retarget_view_modes(rel, moved)
        self._note_change(moved, status='Moved "{}".'.format(moved.rsplit("/", 1)[-1]))

    def _move_asset_items(self, folder, mime):
        moved = 0
        last = None
        for rel in asset_paths(mime):
            current = rel.rsplit("/", 1)[0] if "/" in rel else ""
            if current == (folder or ""):
                continue
            try:
                last = store.move_image(self._root, rel, folder)
                moved += 1
            except store.AssetError:
                continue
        if not moved:
            self._set_status(tr("Nothing was moved.", "没有移动任何内容。"))
            return
        text = "Moved 1 image." if moved == 1 else "Moved {} images.".format(moved)
        self._note_change(folder, last, text)

    def _import_paths(self, folder, paths):
        saved = []
        with _wait_cursor():
            for path in paths:
                try:
                    saved.append(store.import_file(self._root, folder, path))
                except store.AssetError:
                    continue
        if not saved:
            self._set_status(tr("No images were imported.", "没有导入任何图片。"))
            return
        text = "Imported 1 image." if len(saved) == 1 else "Imported {} images.".format(len(saved))
        self._note_change(folder, saved[-1], text)

    def _save_dropped_image(self, folder, mime):
        doc = self._document()
        if (
            mime is not None
            and mime.hasFormat("application/x-krita-node-internal-pointer")
            and doc is not None
        ):
            try:
                node = doc.activeNode()
            except Exception:
                node = None
            if filter_asset.is_filter_layer(node):
                self._persist_structured_asset(
                    folder, node, doc, filter_asset.capture, filter_asset.preview_image, "Filter")
                return
            if group_asset.is_group_layer(node):
                self._persist_structured_asset(
                    folder,
                    node,
                    doc,
                    lambda current, document=doc: group_asset.capture(
                        current, document, pixel_budget=MAX_BAKE_PIXELS),
                    group_asset.preview_image,
                    "Group",
                )
                return
            if mask_asset.has_transparency_mask(node):
                self._persist_structured_asset(
                    folder,
                    node,
                    doc,
                    lambda current, document=doc: group_asset.capture_paint(
                        current, document, pixel_budget=MAX_BAKE_PIXELS),
                    lambda current, edge=THUMB_EDGE: filter_asset.preview_image(current, edge),
                    "Layer",
                )
                return
        try:
            with _wait_cursor():
                image = image_from_mime(mime)
                path = store.new_image_path(self._root, folder, "Layer")
                write_png(image, path)
        except store.AssetError as error:
            self._set_status(str(error))
            return
        except Exception:
            self._set_status(tr("Could not save that image.", "无法保存该图片。"))
            return
        rel = store.relative_path(self._root, path)
        label = os.path.splitext(os.path.basename(path))[0]
        self._note_change(
            folder,
            rel,
            'Saved "{}". Inserting it will center the image.'.format(label),
        )

    def _start_drag(self):
        rels = self._selected_rels()
        if not rels:
            return
        paths = []
        for rel in rels:
            try:
                paths.append(store.image_path(self._root, rel))
            except store.AssetError:
                continue
        if not paths:
            return
        mime = QMimeData()
        mime.setData(ASSET_MIME, QByteArray(json.dumps({"paths": rels}).encode("utf-8")))
        mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
        image = QImage(paths[0])
        if not image.isNull():
            mime.setImageData(image)
        drag = QDrag(self.grid)
        drag.setMimeData(mime)
        icon = self.grid.currentItem().icon() if self.grid.currentItem() is not None else QIcon()
        pixmap = icon.pixmap(72, 72)
        if not pixmap.isNull():
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(12, 12))
        self._dragging = True
        try:
            _run_drag(drag)
        finally:
            self._dragging = False
            pending = self._pending
            self._pending = None
            if pending is not None:
                self._reload(*pending)

    def _start_folder_drag(self):
        item = self.tree.currentItem()
        kind = _item_kind(item)
        if kind == "folder":
            rel = item.data(0, Qt.ItemDataRole.UserRole) or ""
            if not rel:
                return
            payload = {"kind": "folder", "path": rel}
            label = rel.rsplit("/", 1)[-1]
        elif kind in ("separator", "title"):
            marker_id = item.data(0, _ID_ROLE) or ""
            if not marker_id:
                return
            payload = {"kind": kind, "id": marker_id}
            label = item.text(0) if kind == "title" and item.text(0) else "—"
        else:
            return
        mime = QMimeData()
        mime.setData(FOLDER_MIME, QByteArray(json.dumps(payload).encode("utf-8")))
        drag = QDrag(self.tree)
        drag.setMimeData(mime)
        pixmap = QPixmap(168, 28)
        pixmap.fill(QColor(48, 48, 48))
        painter = QPainter(pixmap)
        try:
            painter.setPen(QColor(235, 235, 235))
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, label)
        finally:
            painter.end()
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(12, 14))
        self._dragging = True
        try:
            _run_drag(drag)
        finally:
            self._dragging = False
            self.tree.forget_highlight()
            pending = self._pending
            self._pending = None
            if pending is not None:
                self._reload(*pending)

