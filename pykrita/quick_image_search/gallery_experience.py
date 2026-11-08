from .qtcompat import (Qt, QTimer, QIcon, QKeySequence, QToolButton, QShortcut)
"""Session-local gallery navigation; no provider sessions or user images persisted."""
from pathlib import Path
from urllib.parse import urlsplit

ENTRY_ROLE = Qt.ItemDataRole.UserRole
PATH_ROLE = Qt.ItemDataRole.UserRole + 1
SIZE_ROLE = Qt.ItemDataRole.UserRole + 2


class GalleryExperienceMixin:
    def init_gallery_experience(self, row, prepare_image):
        self._prepare_adjacent_image = prepare_image
        self._prefetch_job = None
        self._prefetch_key = None
        self._prefetch_generation = None
        self._prefetch_attempted = set()
        self._prefetch_direction = 1
        self._prefetch_timer = QTimer(self)
        self._prefetch_timer.setSingleShot(True)
        self._prefetch_timer.setInterval(220)
        self._prefetch_timer.timeout.connect(self.prefetch_adjacent)
        self._back_stack = []
        self._pending_gallery_back = False
        self._page_context = None
        self._pagination_rebuild = None
        self.back_button = QToolButton()
        self.back_button.setText('‹')
        self.back_button.setToolTip('返回上一页（Alt+←）')
        self.back_button.setAccessibleName('返回上一页')
        self.back_button.clicked.connect(self.gallery_back)
        self.back_button.hide()
        row.addWidget(self.back_button)
        self._back_shortcut = QShortcut(QKeySequence('Alt+Left'), self)
        self._back_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._back_shortcut.activated.connect(self.gallery_back)

    def reset_gallery_navigation(self, context):
        self._back_stack.clear()
        self._pending_gallery_back = False
        self._page_context = context
        self._pagination_rebuild = None
        self.back_button.hide()

    def capture_gallery(self):
        rows = []
        for index in range(self.grid.count()):
            item = self.grid.item(index)
            rows.append(dict(entry=dict(item.data(ENTRY_ROLE)), icon=QIcon(item.icon()),
                             path=item.data(PATH_ROLE), size=item.data(SIZE_ROLE), error=item.data(Qt.ItemDataRole.UserRole + 3)))
        return dict(rows=rows, selected=self.grid.currentRow(), scroll=self.grid.verticalScrollBar().value(),
                    tile_size=self.grid.tile_size, source=self.source.currentData(), query=self.search_input.text(),
                    placeholder=self.search_input.placeholderText(), translation=self._translation_pair,
                    active=self._active_search, context=self._page_context, has_more=self.has_more,
                    search_source=self._search_source, thumbnails=dict(self._page_thumbnails))

    def remember_similar_parent(self, frame, entry, path):
        if frame['rows']:
            self._back_stack.append(frame)
            del self._back_stack[:-4]
        self._page_context = dict(mode='similar', source='pinterest', entry=dict(entry), path=path)
        self._pagination_rebuild = None
        self.back_button.setVisible(bool(self._back_stack))

    def gallery_back(self):
        if self._closing or not self._back_stack:
            return
        self._pending_query = None
        self._pending_library = None
        self._pending_similar = None
        if self.busy:
            self._pending_gallery_back = True
            self.status.setText('返回已排队，当前图片任务完成后恢复…')
            return
        self._pending_gallery_back = False
        self.flush_favorite_snapshot()
        self.cancel_preview_load()
        if self.preview_dialog is not None:
            self.preview_dialog.close()
        frame = self._back_stack.pop()
        self.generation += 1
        generation = self.generation
        for job in list(self.jobs):
            job.requestInterruption()
        self._query_revision += 1
        self._more_pending = False
        self._loading_more = False
        self._more_retry_at = 0
        self._restoring_cache = True
        self.source.setCurrentIndex(self.source.findData(frame['source']))
        self.search_input.setText(frame['query'])
        self.search_input.setPlaceholderText(frame['placeholder'])
        self._translation_pair = frame['translation']
        self._active_search = frame['active']
        self._page_context = frame['context']
        self._pagination_rebuild = frame['context']
        self._cached_page = bool(frame['context'])
        self.grid.blockSignals(True)
        try:
            self.display_results([row['entry'] for row in frame['rows']], cached_images={})
            for index, row in enumerate(frame['rows']):
                item = self.grid.item(index)
                item.setIcon(row['icon'])
                if row['error']:
                    item.setData(Qt.ItemDataRole.UserRole + 3, row['error'])
                    item.setToolTip('缩略图加载失败，点击中央按钮重试。\n' + row['error'])
                if row['path'] and Path(row['path']).is_file():
                    item.setData(PATH_ROLE, row['path'])
                    item.setData(SIZE_ROLE, row['size'])
            self.grid.setCurrentRow(frame['selected'])
        finally:
            self.grid.blockSignals(False)
        self._page_thumbnails.update(frame['thumbnails'])
        self._search_source = frame['search_source']
        self.has_more = frame['has_more'] and bool(frame['context'])
        self.back_button.setVisible(bool(self._back_stack))
        self.update_library_controls()

        self.status.clear()
        def restore_position():
            if generation == self.generation and not self._closing:
                self.grid.verticalScrollBar().setValue(frame['scroll'])
                self._restoring_cache = False
                self.schedule_snapshot()
        QTimer.singleShot(0, restore_position)

    def resume_gallery_back(self):
        if self._pending_gallery_back and not self.busy and not self._closing:
            self.gallery_back()

    def retry_thumbnail(self, item):
        error_role, request_role = Qt.ItemDataRole.UserRole + 3, Qt.ItemDataRole.UserRole + 4
        if self._closing or item is None or not item.data(error_role):
            return
        entry = dict(item.data(ENTRY_ROLE))
        key = (entry.get('source'), entry['thumbnail'])
        with self._cache_lock:
            previous = self._thumbnail_cache.pop(key, None)
            if previous is not None:
                self._thumbnail_bytes -= len(previous)
        revision = (item.data(request_role) or 0) + 1
        item.setData(request_role, revision)
        item.setData(error_role, '')
        item.setToolTip('正在重试缩略图…')
        generation, index = self.generation, self.grid.row(item)
        def loaded(data):
            self.set_thumbnail((generation, index, data, revision, ''))
        def failed(message):
            self.set_thumbnail((generation, index, b'', revision, message))
        self.run_job(lambda job: self.thumbnail_bytes(entry), loaded, background=True, on_failure=failed)

    def retry_preview(self):
        dialog = self.preview_dialog
        item = self.grid.currentItem()
        if self._closing or dialog is None or not dialog.isVisible() or item is None:
            return
        entry = item.data(ENTRY_ROLE)
        self._prepared_cache.pop((entry.get('source'), entry['thumbnail']), None)
        item.setData(PATH_ROLE, None)
        item.setData(SIZE_ROLE, None)
        self._pending_preview = (self.generation, item)
        dialog.set_loading()
        self.selection_changed(item)

    def stop_adjacent_prefetch(self):
        self._prefetch_timer.stop()
        if self._prefetch_job is not None and self._prefetch_job.isRunning():
            self._prefetch_job.requestInterruption()

    def schedule_adjacent_prefetch(self):
        dialog = self.preview_dialog
        if not self._closing and dialog is not None and dialog.isVisible() and not dialog.loading:
            self._prefetch_timer.start()

    def uses_adjacent_prefetch(self, item):
        if self._prefetch_job is None or not self._prefetch_job.isRunning() or self._prefetch_job.isInterruptionRequested():
            return False
        entry = item.data(ENTRY_ROLE)
        return self._prefetch_generation == self.generation and self._prefetch_key == (entry.get('source'), entry['thumbnail'])

    def prefetch_adjacent(self):
        dialog = self.preview_dialog
        if self._closing or self.busy or dialog is None or not dialog.isVisible() or dialog.loading:
            return
        if self._prefetch_job is not None and self._prefetch_job.isRunning():
            return
        index = self.grid.currentRow() + self._prefetch_direction
        if not 0 <= index < self.grid.count():
            return
        item = self.grid.item(index)
        if item.data(PATH_ROLE) and Path(item.data(PATH_ROLE)).is_file():
            return
        entry = dict(item.data(ENTRY_ROLE))
        key = (entry.get('source'), entry['thumbnail'])
        generation = self.generation
        cached = self._prepared_cache.get(key)
        if cached and Path(cached[0]).is_file():
            item.setData(PATH_ROLE, cached[0])
            item.setData(SIZE_ROLE, cached[1:])
            return
        # Never resolve a speculative asset through the shared Google/CDP session.
        url = entry.get('image_url')
        try:
            parsed = urlsplit(url) if isinstance(url, str) else None
            if entry.get('source') != 'pinterest' or parsed is None or parsed.scheme != 'https' or parsed.hostname != 'i.pinimg.com' or parsed.username or parsed.password:
                return
        except ValueError:
            return
        attempt = (generation, key)
        if attempt in self._prefetch_attempted:
            return
        self._prefetch_attempted = {previous for previous in self._prefetch_attempted if previous[0] == generation}
        self._prefetch_attempted.add(attempt)
        self._prefetch_key, self._prefetch_generation = key, generation
        def operation(worker):
            data = self.downloader(url, 'https://www.pinterest.com/')
            if worker.isInterruptionRequested():
                return None
            return self._prepare_adjacent_image(data, self.cache_dir, entry.get('title', 'image'))
        def loaded(prepared):
            if self._closing or generation != self.generation or prepared is None:
                return
            self._prepared_cache[key] = prepared
            self._prepared_cache.move_to_end(key)
            while len(self._prepared_cache) > 32:
                self._prepared_cache.popitem(last=False)
            item.setData(PATH_ROLE, prepared[0])
            item.setData(SIZE_ROLE, prepared[1:])
            if self.grid.currentItem() == item:
                self.selection_changed(item)
        def failed(message):
            if not self._closing and generation == self.generation and self._pending_preview == (generation, item):
                if self.preview_dialog is not None and self.preview_dialog.isVisible():
                    self.preview_dialog.set_error(message)
                self._pending_preview = None
        self._prefetch_job = self.run_job(operation, loaded, background=True, on_failure=failed)
