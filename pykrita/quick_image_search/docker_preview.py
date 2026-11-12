"""Preview dialog helpers for Quick Image Search."""

from .qtcompat import QMenu
try:
    from i18n import tr
except ImportError:
    def tr(english, chinese=None):
        return english
from .panel_widgets import ImagePreview, PATH_ROLE


class PreviewExperienceMixin:
    def cancel_preview_load(self):
        self._pending_preview = None
        if self.preview_dialog is not None and self.preview_dialog.loading:
            self.preview_dialog.close()

    def resume_preview(self, item):
        if not self._closing and self._pending_preview == (self.generation, item):
            self._pending_preview = None
            if self.grid.currentItem() == item and self.preview_dialog is not None and self.preview_dialog.isVisible():
                self.preview_dialog.set_image(item.data(PATH_ROLE))
                self.schedule_adjacent_prefetch()

    def update_preview_navigation(self):
        if self.preview_dialog is not None:
            index = self.grid.currentRow()
            self.preview_dialog.set_navigation(index > 0, 0 <= index < self.grid.count() - 1)

    def navigate_preview(self, direction):
        dialog = self.preview_dialog
        if self._closing or dialog is None or not dialog.isVisible():
            return
        target = self.grid.currentRow() + direction
        if target < 0 or target >= self.grid.count():
            return
        self._prefetch_direction = 1 if direction > 0 else -1
        self._pending_preview = None
        dialog.set_loading()
        self._preview_navigation = True
        try:
            self.grid.setCurrentRow(target)
        finally:
            self._preview_navigation = False
        item = self.grid.item(target)
        path = item.data(PATH_ROLE)
        if path:
            try:
                dialog.set_image(path)
                self.schedule_adjacent_prefetch()
            except ValueError as error:
                dialog.set_error(str(error))
        else:
            self._pending_preview = (self.generation, item)
            self.selection_changed(item)

    def preview(self):
        item = self.grid.currentItem()
        if self._closing or item is None:
            return
        self._prefetch_direction = 1
        self._pending_preview = None
        if self.preview_dialog is not None:
            self.preview_dialog.close()
            self.preview_dialog.deleteLater()
            self.preview_dialog = None
        try:
            dialog = ImagePreview(item.data(PATH_ROLE), self)
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.preview_dialog = dialog
        dialog.navigate.connect(self.navigate_preview)
        dialog.retry_requested.connect(self.retry_preview)
        dialog.context_requested.connect(self.show_preview_menu)
        dialog.finished.connect(self.stop_adjacent_prefetch)
        self.update_preview_navigation()
        dialog.show()
        if not item.data(PATH_ROLE):
            self._pending_preview = (self.generation, item)
            self.selection_changed(item)
        else:
            self.schedule_adjacent_prefetch()

    def build_preview_menu(self):
        dialog = self.preview_dialog
        menu = QMenu(dialog or self)
        item = self.grid.currentItem()
        path = item.data(PATH_ROLE) if item is not None else None
        generation = self.generation
        target, reason = None, tr(
            'Prepare an image and open a document first',
            '请先准备图片并打开文档',
        )
        try:
            target = self.drop_router.current_import_target()
        except (AttributeError, ValueError, RuntimeError) as error:
            reason = str(error)
        ready = bool(target is not None and path and dialog and not dialog.loading and dialog.error_label.isHidden() and not self.busy)
        for text, mode in (
            (tr('Insert as layer', '插入为图层'), 'layer'),
            (tr('Insert as reference', '插入为参考图'), 'reference'),
        ):
            action = menu.addAction(text)
            action.setEnabled(ready)
            action.setToolTip(text if ready else reason)
            action.triggered.connect(lambda checked=False, choice=mode: self.import_preview_image(path, choice, target, generation, item))
        return menu

    def show_preview_menu(self, position):
        dialog = self.preview_dialog
        if dialog is None or not dialog.isVisible():
            return
        menu = self.build_preview_menu()
        dialog._context_menu = menu
        try:
            menu.exec(position)
        finally:
            dialog._context_menu = None
            menu.deleteLater()

    def import_preview_image(self, path, mode, target, generation, item):
        if self._closing or generation != self.generation or self.grid.currentItem() != item:
            return
        if self.preview_dialog is not None:
            self.preview_dialog.close()
        try:
            if self.drop_router.import_file(path, mode, target) is False:
                raise RuntimeError('Krita 未接受此次导入，请重新打开预览再试。')
            self.status.setText('已交给 Krita 导入为' + ('图层。' if mode == 'layer' else '参考图。'))
        except (OSError, ValueError, RuntimeError) as error:
            self.status.setText('导入失败：' + str(error))

