"""AssetDragDropMixin; original docker method names remain available through inheritance."""
from .panel_context import *  # shared Qt/asset dependencies


class AssetDragDropMixin:
    def _note_change(self, folder, select_image=None, status=None):
        if self._dragging:
            self._pending = (folder, select_image, status)
            return
        self._reload(folder, select_image, status)

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

