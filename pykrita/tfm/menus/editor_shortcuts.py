"""ShortcutEditingMixin responsibilities extracted without changing saved menu formats."""
from .editor_context import *  # shared Qt/editor dependencies


class ShortcutEditingMixin:
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
            print("tfm: cannot list actions: %s" % e)
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
            original = self._services.read_text(path, strict=True)
        except OSError as error:
            QMessageBox.warning(self, "TFM", "Could not read the shortcut file: {}".format(error))
            return False
        previous = self._services.parse_entries(original)
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
            target = self._services.set_entries(original, {rec["id"]: UNBOUND for _, rec, _ in records})
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
        self.undo_sc_btn.setEnabled(bool(self._services.load_overrides().get(name or "")))

    def _restore_overrides(self):
        """Give the Krita bindings back and clear this menu's key (avoids re-colliding)."""
        if not self.lists:
            return
        name = self.lists[self.current].get("name") or ""
        records = self._services.load_overrides().get(name) or []
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
        if not self._services.restore_shortcuts(path, {r["id"]: r.get("prev_file") for r in records}):
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
                    print("tfm: cannot restore %s: %s" % (r.get("id"), e))
        if (self.lists[self.current].get("shortcut") or "") in keys:
            self.lists[self.current]["shortcut"] = ""
            self._update_left_shortcut()
        if not self._services.save_config(self.popup_shortcut, self.lists):
            QMessageBox.warning(self, "TFM", "Shortcuts were restored, but the menu configuration could not be saved. Recovery records were kept.")
            return
        if self._services.pop_overrides(name) is None:
            QMessageBox.warning(self, "TFM", "Shortcuts and menu configuration were restored, but recovery records could not be cleared. Try Restore again.")
            return
        self._pending_overrides.pop(name, None)
        self._services.notify_refresh()
        self._update_undo_button()

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
            self._refresh_conflict_banner()
            return
        conflicts = self._conflicts_for(key)
        if conflicts and not self._ask_override(key, conflicts):
            self._revert_shortcut_field(previous)
            self._refresh_conflict_banner()
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
        self._refresh_conflict_banner()

    def _clear_list_shortcut(self):
        if not self.lists:
            return
        self._drop_pending()
        self.lists[self.current]["shortcut"] = ""
        self._revert_shortcut_field("")
        self._refresh_conflict_banner()

    def _update_left_shortcut(self):
        if not self.lists:
            return
        self._loading_sc = True
        self.list_sc_edit.setKeySequence(
            self.lists[self.current].get("shortcut", ""))
        self._loading_sc = False
        self._update_undo_button()
        self._refresh_conflict_banner()

    def _refresh_conflict_banner(self):
        label = getattr(self, "shortcut_conflict_label", None)
        if label is None:
            return
        conflict = self._check_conflicts()
        if conflict:
            label.setText(tr(
                "Shortcut conflict: {} Use Override when assigning, or Clear / Restore, then Save Menus.",
                "快捷键冲突：{} 分配时用「接管」，或清除/恢复后再「保存菜单」。",
            ).format(conflict))
            apply_warning_label(label)
            label.show()
        else:
            label.clear()
            label.hide()

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
            print("tfm: cannot list actions: %s" % e)
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

