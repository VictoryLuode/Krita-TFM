"""AssetOperationsMixin; original docker method names remain available through inheritance."""
from .panel_context import *  # shared Qt/asset dependencies
from tfm_diagnostics import record_error


class AssetOperationsMixin:
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
        except Exception as error:
            record_error('asset.insert', error)
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
        except Exception as error:
            record_error("asset.export", error, path=path)
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            self._tell("Krita could not export this layer.")
            return
        try:
            store.write_meta(path, bounds.x(), bounds.y())
        except (OSError, ValueError, store.AssetError) as error:
            record_error('asset.save_metadata', error, path=path)
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
        except Exception as error:
            record_error("asset.export", error, path=path)
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

