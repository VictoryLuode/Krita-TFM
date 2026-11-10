"""MenuEditingMixin responsibilities extracted without changing saved menu formats."""
from .editor_context import *  # shared Qt/editor dependencies


class MenuEditingMixin:
    def _menu_state(self):
        import copy
        return copy.deepcopy((self.popup_shortcut, self.lists))

    def has_unsaved_changes(self):
        return self._menu_state() != self._saved_menu_state or bool(self._pending_overrides)

    def _cur_menu(self):
        return self.path[-1] if self.path else {"name": "", "shortcut": "", "items": []}

    def _cur_items(self):
        return self._cur_menu().get("items", [])

    def _name(self):
        return self._cur_menu().get("name", "")

    def _go_to_depth(self, depth):
        if 0 <= depth < len(self.path):
            self.path = self.path[: depth + 1]
            self._render_current()

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

    def _cur_top_list(self):
        if 0 <= self.current < len(self.lists):
            return self.lists[self.current]
        return None

    def _on_form_changed(self):
        lst = self._cur_top_list()
        if lst is None:
            return
        lst["menu_mode"] = self.form_combo.currentData()
        self._services.save_config(self.popup_shortcut, self.lists)
        self._saved_menu_state = self._menu_state()
        self._services.notify_refresh()
        self._warn_pie_limits(lst)

    def _on_show_icons_changed(self):
        lst = self._cur_top_list()
        if lst is None:
            return
        lst["show_icons"] = self.show_icons_check.isChecked()
        self._services.save_config(self.popup_shortcut, self.lists)
        self._saved_menu_state = self._menu_state()
        self._services.notify_refresh()

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
        if any(item.get("name") == name for item in self.lists) or self._services.load_overrides().get(name):
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
            if new_name != old_name and (self._services.load_overrides().get(old_name) or self._services.load_overrides().get(new_name)):
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
        while name in names or self._services.load_overrides().get(name):
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
        if self._services.load_overrides().get(name):
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

    def _existing_cmd_ids(self):
        out = set()
        for it in self._cur_items():
            if isinstance(it, str):
                out.add(it)
            elif isinstance(it, dict) and it.get("id"):
                out.add(it["id"])
        return out

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

