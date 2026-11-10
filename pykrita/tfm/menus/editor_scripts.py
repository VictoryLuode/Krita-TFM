"""ScriptEditingMixin responsibilities extracted without changing saved menu formats."""
from .editor_context import *  # shared Qt/editor dependencies


class ScriptEditingMixin:
    def _update_script_widget(self):
        """Show the script library actions only while the Scripts source is active."""
        src = self._current_source()
        is_script = src is not None and src.key == "script"
        if is_script:
            self._services.ensure_scripts_dir()
        self.script_widget.setVisible(is_script)

    def _selected_script(self):
        item = self.add_tree.currentItem()
        if item is None or item.data(0, ROLE_TYPE) != TYPE_SCRIPT:
            return ""
        return script_filename(item.data(0, ROLE_TOKEN) or "")

    def _new_script(self):
        if exec_(_ScriptEditorDialog(self)) == QDialog.DialogCode.Accepted:
            self._reload_available()

    def _edit_script(self):
        fn = self._selected_script()
        if not fn:
            QMessageBox.information(self, "TFM", "Select a script in the list first.")
            return
        if exec_(_ScriptEditorDialog(self, fn, self._services.read_script(fn))) == QDialog.DialogCode.Accepted:
            self._reload_available()

    def _rename_script_file(self):
        fn = self._selected_script()
        if not fn:
            QMessageBox.information(self, "TFM", "Select a script in the list first.")
            return
        if os.path.normcase(self._services.script_path(fn)) != os.path.normcase(os.path.join(SCRIPTS_DIR, fn)):
            QMessageBox.information(self, "TFM", "This is a bundled example. Edit it first to create your own copy before renaming it.")
            return
        new_name, ok = QInputDialog.getText(self, "Rename Script", "New name:",
                                            text=os.path.splitext(fn)[0])
        if not ok or not new_name.strip():
            return
        new_fn = self._services.rename_script(fn, new_name)
        if not new_fn:
            QMessageBox.warning(
                self, "TFM",
                "Could not rename the script (a script with that name may already exist).")
            return
        self._remap_script_items(fn, new_fn)
        self._render_items()
        self._reload_available()

    def _delete_script_file(self):
        fn = self._selected_script()
        if not fn:
            QMessageBox.information(self, "TFM", "Select a script in the list first.")
            return
        if os.path.normcase(self._services.script_path(fn)) != os.path.normcase(os.path.join(SCRIPTS_DIR, fn)):
            QMessageBox.information(self, "TFM", "This is a bundled example and cannot be deleted.")
            return
        reply = QMessageBox.question(
            self, "Delete Script",
            "Delete '%s' from the library?\n\n"
            "The bundled example will be used if one has the same name; "
            "otherwise menu items using it will report 'not found'." % fn,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        if not self._services.delete_script(fn):
            QMessageBox.warning(self, "TFM", "Could not delete the script file.")
            return
        self._reload_available()

    def _open_scripts_folder(self):
        path = self._services.ensure_scripts_dir()
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception:
            QMessageBox.information(self, "TFM", "Script folder:\n%s" % path)

    def _remap_script_items(self, old_fn, new_fn):
        """Follow a renamed script file from every menu item that uses it."""
        def walk(items):
            for it in items:
                if not isinstance(it, dict):
                    continue
                if it.get("script") == old_fn:
                    it["script"] = new_fn
                if isinstance(it.get("items"), list):
                    walk(it["items"])
        for lst in self.lists:
            walk(lst.get("items", []))

