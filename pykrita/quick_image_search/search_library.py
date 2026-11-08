from .qtcompat import (Qt, QPoint, QSize, QTimer, QBuffer, QIODevice, QStandardPaths, QIcon, QPixmap, QPainter, QImage, QImageReader, QAction, QApplication, QLineEdit, QMenu, QStyle, QInputDialog)
"""Compact native search-history UI and asynchronous favorite-page persistence."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from .favorite_tabs import FavoriteTabs

from .search_store import SearchStore
from .favorite_cache import FavoriteCache, cache_key
from .history_menu import HistoryMenu
from .ui_preferences import UIPreferences


def thumbnail_image(data):
    if not isinstance(data, bytes) or len(data) > 24 * 1024 * 1024:
        return QImage()
    buffer = QBuffer()
    buffer.setData(data)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > 32 * 1024 * 1024:
        return QImage()
    reader.setScaledSize(size.boundedTo(QSize(384, 384)))
    return reader.read()


def image_identity(entry):
    source = entry.get('source')
    if source == 'pinterest':
        try:
            parsed = urlsplit(entry.get('image_url') or entry.get('thumbnail') or '')
            filename = parsed.path.rsplit('/', 1)[-1]
            if parsed.scheme == 'https' and parsed.hostname == 'i.pinimg.com' and filename:
                return ('pinterest:image', filename)
        except ValueError:
            pass
    return (source, entry.get('id') or entry['thumbnail'])


def restore_entry(entry):
    entry = dict(entry)
    url = entry.get('image_url')
    if entry.get('source') == 'pinterest' and isinstance(url, str):
        try:
            parsed = urlsplit(url)
            if parsed.scheme == 'https' and parsed.hostname == 'i.pinimg.com' and not parsed.username and not parsed.password:
                entry['_pin'] = {'images': {'orig': {'url': url}}}
        except ValueError:
            pass
    return entry


def history_icon():
    pixmap = QPixmap(22, 22)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = painter.pen()
    pen.setColor(QApplication.palette().text().color())
    pen.setWidth(2)
    painter.setPen(pen)
    painter.drawLine(QPoint(6, 9), QPoint(11, 14))
    painter.drawLine(QPoint(11, 14), QPoint(16, 9))
    painter.end()
    return QIcon(pixmap)


def star_icon(favorite):
    pixmap = QPixmap(22, 22)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setPen(QApplication.palette().text().color())
    font = QApplication.font()
    font.setPixelSize(19)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, '★' if favorite else '☆')
    painter.end()
    return QIcon(pixmap)


class SearchLibraryMixin:
    def init_library(self, user_data_dir=None, cache_dir=None):
        root = Path(user_data_dir) if user_data_dir is not None else (
            Path(cache_dir) / 'search-data' if cache_dir is not None else
            Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)) / 'quick-image-search' / 'library')
        self.search_store = SearchStore(root / 'searches.json')
        self._grid_settings = UIPreferences(root / 'ui.json')
        self._grid_pending_size = None
        self._grid_save_timer = QTimer(self)
        self._grid_save_timer.setSingleShot(True)
        self._grid_save_timer.setInterval(250)
        self._grid_save_timer.timeout.connect(self.flush_grid_size)
        self.favorite_cache = FavoriteCache(root / 'pages')
        self._cache_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='search-page-cache')
        self._cache_error = ''
        self._cache_suppressed = set()
        self._page_thumbnails = OrderedDict()
        self._active_search = None
        self._cached_page = False
        self._restoring_cache = False
        self._pending_library = None
        self._translation_pair = None
        self._snapshot_timer = QTimer(self)
        self._snapshot_timer.setSingleShot(True)
        self._snapshot_timer.setInterval(600)
        self._snapshot_timer.timeout.connect(self.flush_favorite_snapshot)
        self._cache_status_timer = QTimer(self)
        self._cache_status_timer.setInterval(500)
        self._cache_status_timer.timeout.connect(self.report_cache_error)
        self._cache_status_timer.start()
        self.history_action = QAction(history_icon(), '历史与收藏', self.search_input)
        self.history_action.setToolTip('历史与收藏；右键条目可管理或刷新缓存')
        self.history_action.triggered.connect(self.show_history_menu)
        self.favorite_action = QAction(star_icon(False), '收藏当前关键词', self.search_input)
        self.favorite_action.setCheckable(True)
        self.favorite_action.triggered.connect(self.toggle_current_favorite)
        self.search_input.addAction(self.history_action, QLineEdit.ActionPosition.TrailingPosition)
        self.search_input.addAction(self.favorite_action, QLineEdit.ActionPosition.TrailingPosition)
        self.update_library_controls()

    def original_query(self):
        pair = self._translation_pair
        return pair[0] if pair and pair[1] == self.search_input.text().strip() else ''

    def remember_grid_size(self, size):
        self._grid_pending_size = size
        self._grid_save_timer.start()

    def flush_grid_size(self):
        self._grid_save_timer.stop()
        if self._grid_pending_size is not None:
            size, self._grid_pending_size = self._grid_pending_size, None
            try:
                self._grid_settings.save(size)
            except (OSError, ValueError) as error:
                self.status.setText('网格尺寸未保存：' + str(error))

    def update_library_controls(self):
        if not hasattr(self, 'favorite_action'):
            return
        query = self.search_input.text().strip()
        record = self.search_store.lookup(self.source.currentData(), query)
        favorite = bool(record and record['favorite'])
        self.favorite_action.setEnabled(bool(query) and not self._closing)
        self.favorite_action.setChecked(favorite)
        self.favorite_action.setIcon(star_icon(favorite))
        self.favorite_action.setToolTip('取消收藏当前关键词' if favorite else '收藏当前关键词（不执行搜索）')
        self.update_favorite_tabs()

    @staticmethod
    def record_label(record):
        return record.get('alias') or record['original_query'] or record['query']

    def init_favorite_tabs(self, row):
        self.favorite_tabs = FavoriteTabs(self)
        self.favorite_tabs.record_requested.connect(self.activate_record)
        self.favorite_tabs.tabCloseRequested.connect(self.close_favorite_tab)
        self.favorite_tabs.tabMoved.connect(self.favorite_tab_moved)
        self.favorite_tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.favorite_tabs.customContextMenuRequested.connect(self.favorite_tab_menu)
        row.addWidget(self.favorite_tabs, 1)
        self.update_favorite_tabs()

    def update_favorite_tabs(self):
        if not hasattr(self, 'favorite_tabs'):
            return
        tabs = self.favorite_tabs
        records = self.search_store.favorites()
        ids = [record['id'] for record in records]
        tabs.blockSignals(True)
        try:
            if ids != [tabs.tabData(i) for i in range(tabs.count())]:
                while tabs.count():
                    tabs.removeTab(0)
                for record in records:
                    index = tabs.addTab(self.record_label(record))
                    tabs.setTabData(index, record['id'])
                    tabs.install_close_button(index, record['id'])
            for index, record in enumerate(records):
                tabs.setTabText(index, self.record_label(record).replace('&', '&&'))
                tabs.setTabToolTip(index, self.record_label(record) + '\n搜索：' + record['query'] + '\n右键改名；× 取消收藏')
            record = self.search_store.lookup(*self._active_search) if self._active_search else None
            tabs.active_id = record['id'] if record and record['favorite'] else None
            if tabs.active_id in ids:
                tabs.setCurrentIndex(ids.index(tabs.active_id))
        finally:
            tabs.blockSignals(False)
        tabs.update()

    def close_favorite_tab(self, index):
        record = self.search_store.get(self.favorite_tabs.tabData(index))
        if record and record['favorite']:
            self.toggle_record_favorite(record['source'], record['query'], record['original_query'])

    def favorite_tab_moved(self, old_index, new_index):
        tabs = self.favorite_tabs
        try:
            self.search_store.reorder_favorites([tabs.tabData(i) for i in range(tabs.count())])
        except (OSError, ValueError) as error:
            self.status.setText('收藏顺序未保存：' + str(error))
        self.update_favorite_tabs()

    def set_favorite_alias(self, identity, alias):
        try:
            self.search_store.set_alias(identity, alias)
        except (OSError, ValueError) as error:
            self.status.setText('收藏名称未保存：' + str(error))
        self.update_library_controls()

    def rename_favorite(self, record):
        text, accepted = QInputDialog.getText(self, '收藏别名', '显示名称（留空恢复关键词）：', text=record.get('alias', ''))
        if accepted:
            self.set_favorite_alias(record['id'], text)

    def favorite_tab_menu(self, position):
        tabs = self.favorite_tabs
        index = tabs.tabAt(position)
        if index < 0:
            return
        record = self.search_store.get(tabs.tabData(index))
        if not record:
            return
        menu = QMenu(tabs)
        menu.addAction('修改别名').triggered.connect(lambda: self.rename_favorite(record))
        menu.addAction('刷新结果').triggered.connect(lambda: self.activate_record(record['id'], refresh=True))
        menu.addAction('清除此项缓存').triggered.connect(lambda: self.clear_record_cache(record))
        menu.addAction('取消收藏').triggered.connect(lambda: self.toggle_record_favorite(record['source'], record['query'], record['original_query']))
        try:
            menu.exec(tabs.mapToGlobal(position))
        finally:
            menu.deleteLater()

    @staticmethod
    def favorite_key(record):
        return cache_key(record['id'], record['source'], record['query'])

    def toggle_current_favorite(self, checked=False):
        self.toggle_record_favorite(self.source.currentData(), self.search_input.text(), self.original_query())

    def toggle_record_favorite(self, source, query, original_query=''):
        old = self.search_store.lookup(source, query)
        try:
            record = self.search_store.toggle_favorite(source, query, original_query)
            if old and old['favorite']:
                self._cache_executor.submit(self.favorite_cache.clear, self.favorite_key(old))
            elif record:
                self._cache_suppressed.discard(self.favorite_key(record))
                self.flush_favorite_snapshot()
        except (OSError, ValueError) as error:
            self.status.setText('收藏未保存：' + str(error))
        self.update_library_controls()

    def build_history_menu(self):
        menu = HistoryMenu(self.search_input)
        menu.record_requested.connect(self.activate_record)
        menu.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        menu.customContextMenuRequested.connect(lambda position: self.history_context_menu(menu, position))
        menu.unfavorite_requested.connect(lambda identity: self.unfavorite_menu_record(menu, identity))
        self.populate_history_menu(menu)
        return menu

    def populate_history_menu(self, menu):
        active = menu.activeAction()
        selected_id = active.data() if active else None
        menu.clear()
        for title, records in (('收藏搜索', self.search_store.favorites()), ('最近搜索', self.search_store.recent())):
            menu.addSection(title)
            if not records:
                menu.addAction('暂无记录').setEnabled(False)
            for record in records:
                full = self.record_label(record)
                width = max(180, min(480, self.width() - 32))
                text = menu.fontMetrics().elidedText(full, Qt.TextElideMode.ElideRight, width)
                action = menu.addAction(text.replace('&', '&&'))
                action.setToolTip(full + '\n搜索：' + record['query'] + '\n右键可管理此条目')
                action.setData(record['id'])
                action.setProperty('favorite', record['favorite'])
                action.triggered.connect(lambda checked=False, identity=record['id']: self.activate_record(identity))
                if record['id'] == selected_id:
                    menu.setActiveAction(action)
        menu.addSeparator()
        clear = menu.addAction('清空最近搜索（保留收藏）')
        clear.setEnabled(bool(self.search_store.recent()))
        clear.triggered.connect(self.clear_recent_searches)
        menu.setToolTipsVisible(True)
        if menu.isVisible():
            menu.adjustSize()

    def unfavorite_menu_record(self, menu, identity):
        record = self.search_store.get(identity)
        if record and record['favorite']:
            self.toggle_record_favorite(record['source'], record['query'], record['original_query'])
            self.populate_history_menu(menu)

    def show_history_menu(self):
        menu = self.build_history_menu()
        try:
            menu.exec(self.search_input.mapToGlobal(QPoint(0, self.search_input.height())))
        finally:
            menu.deleteLater()

    def clear_recent_searches(self):
        try:
            self.search_store.clear_recent()
        except (OSError, ValueError) as error:
            self.status.setText('历史未更新：' + str(error))

    def history_context_menu(self, parent, position):
        action = parent.actionAt(position)
        record = self.search_store.get(action.data()) if action and isinstance(action.data(), str) else None
        if not record:
            return
        context = QMenu(parent)
        context.addAction('取消收藏' if record['favorite'] else '收藏此搜索').triggered.connect(
            lambda: self.toggle_record_favorite(record['source'], record['query'], record['original_query']))
        if record['favorite']:
            context.addAction('修改别名').triggered.connect(lambda: self.rename_favorite(record))
            context.addAction('刷新结果').triggered.connect(lambda: self.activate_record(record['id'], refresh=True))
            context.addAction('清除此项缓存').triggered.connect(lambda: self.clear_record_cache(record))
        else:
            context.addAction('删除此条记录').triggered.connect(lambda: self.remove_recent_record(record['id']))
        try:
            context.exec(parent.mapToGlobal(position))
        finally:
            if parent.isVisible():
                self.populate_history_menu(parent)
            context.deleteLater()

    def remove_recent_record(self, identity):
        try:
            self.search_store.remove_history(identity)
        except (OSError, ValueError) as error:
            self.status.setText('历史未更新：' + str(error))

    def clear_record_cache(self, record):
        key = self.favorite_key(record)
        self._cache_suppressed.add(key)
        self._cache_executor.submit(self.favorite_cache.clear, key)
        self.status.setText('已安排清除此项缓存，收藏保留。')

    def activate_record(self, identity, refresh=False):
        if self._closing:
            return
        record = self.search_store.get(identity)
        if not record:
            return
        self._pending_query = None
        self._pending_gallery_back = False
        self._pending_similar = None
        if self.busy:
            self._pending_library = (identity, refresh)
            self.status.setText('搜索方案已排队，当前图片任务完成后打开…')
            return
        self._pending_library = None
        self.flush_favorite_snapshot()
        self._query_revision += 1
        self.source.setCurrentIndex(self.source.findData(record['source']))
        self.search_input.setText(record['query'])
        self._translation_pair = (record['original_query'], record['query']) if record['original_query'] else None
        self.update_library_controls()
        if refresh or not record['favorite']:
            self.search()
            return
        self.cancel_preview_load()
        self.generation += 1
        generation = self.generation
        for job in list(self.jobs):
            job.requestInterruption()
        self._more_pending = False
        self.status.setText('正在打开收藏缓存…')
        def operation(job):
            snapshot = self._cache_executor.submit(self.favorite_cache.load, self.favorite_key(record)).result()
            if snapshot is None:
                return None
            images = {url: thumbnail_image(data) for url, data in snapshot['thumbnails'].items()}
            return snapshot, images
        def loaded(result):
            if generation != self.generation or self._closing:
                return
            if self._pending_query is not None:
                return
            if result is None:
                self.search()
                return
            snapshot, images = result
            entries = [restore_entry(entry) for entry in snapshot['entries'] if isinstance(entry, dict)
                       and entry.get('source') == record['source'] and isinstance(entry.get('thumbnail'), str)]
            if not entries:
                self.search()
                return
            self._restoring_cache = True
            self.reset_gallery_navigation(dict(mode='keyword', source=record['source'], query=record['query']))
            self._active_search = (record['source'], record['query'])
            self._cached_page = True
            self.grid.blockSignals(True)
            try:
                self.display_results(entries, cached_images=images)
                self.has_more = snapshot['has_more']
                for index, entry in enumerate(entries):
                    if (str(entry.get('id') or entry['thumbnail'])) == snapshot['selected_id']:
                        self.grid.setCurrentRow(index)
                        break
            finally:
                self.grid.blockSignals(False)
            def restore_position():
                if generation == self.generation and not self._closing:
                    self.grid.verticalScrollBar().setValue(snapshot['scroll'])
                    self._restoring_cache = False
            QTimer.singleShot(0, restore_position)
            missing = sum(1 for entry in entries if entry['thumbnail'] not in images or images[entry['thumbnail']].isNull())
            self.status.setText('已恢复收藏缓存' + ('，部分缩略图缺失；可右键刷新。' if missing else '；右键收藏可刷新。'))
        self.run_job(operation, loaded, lock_grid=False)

    def resume_library(self):
        if self._pending_library is not None and not self.busy and not self._closing:
            identity, refresh = self._pending_library
            self._pending_library = None
            self.activate_record(identity, refresh)

    def schedule_snapshot(self, reset=False):
        self.report_cache_error()
        if reset and self._active_search:
            record = self.search_store.lookup(*self._active_search)
            if record:
                self._cache_suppressed.discard(self.favorite_key(record))
        if not self._closing and not self._restoring_cache:
            self._snapshot_timer.start()

    def flush_favorite_snapshot(self):
        self._snapshot_timer.stop()
        if self._closing or self._restoring_cache or not self._active_search or not self.grid.count():
            return
        record = self.search_store.lookup(*self._active_search)
        if not record or not record['favorite'] or self.favorite_key(record) in self._cache_suppressed:
            return
        entries = [dict(self.grid.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(self.grid.count())]
        current = self.grid.currentItem()
        entry = current.data(Qt.ItemDataRole.UserRole) if current else {}
        payload = (self.favorite_key(record), entries, dict(self._page_thumbnails), self.grid.verticalScrollBar().value(),
                   str(entry.get('id') or entry.get('thumbnail') or ''), self.has_more, self.grid.tile_size)
        self._cache_executor.submit(self._write_snapshot, payload)

    def report_cache_error(self):
        if self._cache_error and not self._closing:
            self.status.setText('收藏缓存未保存：' + self._cache_error)
            self._cache_error = ''

    def _write_snapshot(self, payload):
        key, entries, thumbnails, scroll, selected, has_more, tile_size = payload
        previous = self.favorite_cache.load(key)
        urls = {entry['thumbnail'] for entry in entries}
        merged = {url: data for url, data in (previous['thumbnails'].items() if previous else []) if url in urls}
        merged.update(thumbnails)
        if not self.favorite_cache.save(key, entries, merged, scroll, selected, has_more, tile_size):
            self._cache_error = self.favorite_cache.last_error or '缓存已超出容量限制。'
