"""Native Krita search panel; no external Qt or Python packages required."""

from .qtcompat import (QMimeData, QUrl, QThread, pyqtSignal, Qt, QSize, QStandardPaths, QBuffer, QIODevice, QTimer, QPoint, QEvent, QRect, QRectF, QPointF, QImage, QImageReader, QPixmap, QIcon, QDrag, QDesktopServices, QPainter, QPen, QColor, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QComboBox, QListWidget, QListWidgetItem, QAbstractItemView, QListView, QLabel, QDialog, QScrollArea, QStyledItemDelegate, QStyleOptionViewItem, QStyle, QMenu, QPlainTextEdit, QSizePolicy, QToolButton, QDockWidget as _QDockWidget)
QDockWidget = _QDockWidget
from pathlib import Path
import hashlib
import html
import json
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import wait, FIRST_COMPLETED
from quick_image_search.task_runtime import BoundedExecutor, register_owner

from krita import DockWidget, Krita
try:
    from i18n import tr
except ImportError:  # standalone / unit-test load without pykrita on path
    def tr(english, chinese=None):
        return english
try:
    from ui_chrome import (
        apply_muted_label,
        icon_tool_button,
        make_empty_state,
        position_empty_state,
        standard_icon,
        sync_empty_state,
    )
except ImportError:
    def apply_muted_label(label):
        label.setWordWrap(True)

    def icon_tool_button(parent, text, tip, icon_name, slot=None):
        button = QToolButton(parent)
        button.setAutoRaise(True)
        button.setText(text)
        button.setToolTip(tip or text)
        if slot is not None:
            button.clicked.connect(slot)
        return button

    def make_empty_state(parent, text):
        label = QLabel(text, parent)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        return label

    def position_empty_state(label, host):
        if label is not None and host is not None:
            label.setGeometry(host.rect())
            label.raise_()

    def standard_icon(widget, name):
        return QIcon()

    def sync_empty_state(label, visible, text=None):
        if text is not None:
            label.setText(text)
        label.setVisible(bool(visible))
from .drop_router import DRAG_FORMAT, install_drop_router
from .search_library import SearchLibraryMixin, thumbnail_image, image_identity
from .gallery_experience import GalleryExperienceMixin
from .docker_preview import PreviewExperienceMixin
from .status_indicator import StatusIndicator
from .panel_widgets import *  # noqa: F403

class ImageSearchDocker(DockWidget, SearchLibraryMixin, GalleryExperienceMixin, PreviewExperienceMixin):
    def __init__(self, browser=None, cache_dir=None, downloader=None, user_data_dir=None):
        super().__init__()
        self.setObjectName('tfm_quick_image_search')
        self.setWindowTitle(tr('Quick Image Search', '快速搜图'))
        self.setMinimumWidth(332)
        self.browser = browser
        default_profile = str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)) / 'quick-image-search' / 'browser')
        try:
            settings = Krita.instance()
            self.browser_profile = settings.readSetting('quick_image_search', 'browser_profile', default_profile)
            self.browser_proxy = settings.readSetting('quick_image_search', 'browser_proxy', '')
        except AttributeError:
            self.browser_profile, self.browser_proxy = default_profile, ''
        self.downloader = downloader or (lambda url, referer='': download_image(url, referer, self.browser_proxy))
        self.cache_dir = Path(cache_dir or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation))
        if cache_dir is None:
            self.cache_dir = self.cache_dir / 'quick-image-search' / uuid.uuid4().hex
        self.busy = False
        self.generation = 0
        self.jobs = set()
        self._shutdown_done = threading.Event()
        self._cleanup_started = False
        self._thumbnail_executor = BoundedExecutor(max_workers=4, thread_name_prefix="search-thumbnail")
        self.preview_dialog = None
        self._pending_preview = None
        self._preview_navigation = False
        self.details_dialog = None
        self.last_size = None
        self._thumbnail_cache = OrderedDict()
        self._thumbnail_bytes = 0
        self._cache_lock = threading.Lock()
        self._prepared_cache = OrderedDict()
        self.has_more = False
        self._loading_more = False
        self._more_retry_at = 0.0
        self._search_source = 'pinterest'
        self._gallery_ids = set()
        self._more_pending = False
        self._pending_similar = None
        self._closing = False
        self._pending_query = None
        self._translation_job = None
        self._query_revision = 0
        self.drop_router = install_drop_router()
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.source = QComboBox()
        self.source.addItem('Google', 'google')
        self.source.addItem('Pinterest', 'pinterest')
        self.source.setCurrentIndex(1)
        self.search_input = QLineEdit()
        self.search_input.setMaxLength(4096)
        self.search_input.setMinimumWidth(100)
        self.search_input.setPlaceholderText(tr('Search photo references…', '搜索照片素材…'))
        self.init_library(user_data_dir, cache_dir)
        self.translate_button = QPushButton(tr('Translate', '翻译'))
        self.translate_button.setEnabled(False)
        self.translate_button.setToolTip(tr(
            'Translate the current Chinese keywords to English online (MyMemory anonymous quota). Does not search automatically.',
            '将当前中文关键词在线译成英文（MyMemory，匿名免费额度）；只发送关键词，不自动搜索。',
        ))
        self.search_button = QPushButton(tr('Search', '搜索'))
        for button in (self.translate_button, self.search_button):
            button.setMaximumWidth(button.fontMetrics().horizontalAdvance(button.text()) + 24)
        self.init_gallery_experience(row, prepare_image)
        row.addWidget(self.source)
        row.addWidget(self.search_input, 1)
        row.addWidget(self.translate_button)
        row.addWidget(self.search_button)
        layout.addLayout(row)
        grid_host = QWidget(self)
        grid_host_layout = QVBoxLayout(grid_host)
        grid_host_layout.setContentsMargins(0, 0, 0, 0)
        grid_host_layout.setSpacing(0)
        self.grid = ImageGrid()
        self.grid.set_tile_size(self._grid_settings.tile_size)
        self.grid.tile_size_changed.connect(self.remember_grid_size)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self.context_menu)
        grid_host_layout.addWidget(self.grid)
        self.grid_empty = make_empty_state(
            grid_host,
            tr('Search Google or Pinterest for photo references.\nGoogle may ask you to verify in a browser window.',
               '搜索 Google 或 Pinterest 找照片素材。\nGoogle 可能需要在浏览器窗口中完成验证。'),
        )
        self.grid.installEventFilter(self)
        layout.addWidget(grid_host, 1)
        buttons = QHBoxLayout()
        self.source.currentIndexChanged.connect(self.update_source_controls)
        self.init_favorite_tabs(buttons)
        self.status = TransientStatus()
        self.status_text = QLabel('')
        apply_muted_label(self.status_text)
        self.status_text.setWordWrap(False)
        self.status_text.setMinimumWidth(0)
        self.status_text.setFixedHeight(max(22, self.status_text.fontMetrics().lineSpacing()))
        self.status_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.status.details_requested.connect(self.show_status_menu)
        _set_status = self.status.setText

        def set_status_with_text(message):
            _set_status(message)
            text = str(message or '')
            metrics = self.status_text.fontMetrics()
            self.status_text.setText(
                metrics.elidedText(text, Qt.TextElideMode.ElideRight, 320) if text else '')
            self._sync_grid_empty_state()

        self.status.setText = set_status_with_text
        self.verify_button = icon_tool_button(
            self, tr('Verify…', '验证…'),
            tr('Open a visible browser window to complete Google verification or login.',
               '打开可见浏览器窗口，完成 Google 验证或登录。'),
            'SP_DialogApplyButton', self.show_browser)
        self.reset_profile_button = icon_tool_button(
            self, tr('Reset profile', '重置配置'),
            tr('Close the search browser and delete its local profile folder, then start fresh.',
               '关闭搜图浏览器并删除本地配置目录，然后重新开始。'),
            'SP_BrowserReload', self.reset_browser_profile)
        buttons.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        buttons.addWidget(self.status_text, 1)
        buttons.addWidget(self.verify_button, 0, Qt.AlignmentFlag.AlignVCenter)
        buttons.addWidget(self.reset_profile_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(buttons)
        self.setWidget(widget)
        set_status_with_text('')
        self.search_button.clicked.connect(self.search)
        self.translate_button.clicked.connect(self.translate_query)
        self.search_input.textChanged.connect(self.query_edited)
        self.search_input.returnPressed.connect(self.search)

        self.grid.currentItemChanged.connect(self.selection_changed)
        self.grid.itemDoubleClicked.connect(lambda item: self.preview())
        self.grid.needs_image.connect(self.drag_not_ready)
        self.grid.more_requested.connect(self.load_more)
        self.grid.retry_requested.connect(self.retry_thumbnail)
        self.grid.verticalScrollBar().valueChanged.connect(self.scroll_changed)
        register_owner(self, QApplication.instance())
        self.destroyed.connect(lambda: self._begin_cleanup())
        self.update_source_controls()
        self._sync_grid_empty_state()
        if self.search_store.last_error:
            self.status.setText(tr('History/favorites store notice: ', '历史/收藏存储提示：') + self.search_store.last_error)
        elif self._grid_settings.last_error:
            self.status.setText(tr('Could not read grid size setting: ', '网格尺寸设置无法读取：') + self._grid_settings.last_error)

    def canvasChanged(self, canvas):
        pass

    def _sync_grid_empty_state(self):
        empty = getattr(self, 'grid_empty', None)
        if empty is None:
            return
        sync_empty_state(empty, self.grid.count() == 0)
        position_empty_state(empty, self.grid)

    def eventFilter(self, obj, event):
        if obj is getattr(self, 'grid', None) and event.type() == QEvent.Type.Resize:
            position_empty_state(getattr(self, 'grid_empty', None), self.grid)
        return super().eventFilter(obj, event)

    def query_edited(self, text):
        self.cancel_preview_load()
        self._query_revision += 1
        self._translation_pair = None
        self.update_library_controls()
        self.update_translation_controls()

    def update_translation_controls(self):
        self.translate_button.setEnabled(not self._closing and self._translation_job is None
                                         and has_chinese(self.search_input.text()))

    def translate_query(self):
        text = self.search_input.text()
        if self._closing or self._translation_job is not None or not has_chinese(text):
            return
        revision = self._query_revision
        translating = tr('Translating…', '正在翻译…')
        failed_prefix = tr('Translation failed: ', '翻译失败：')
        if self.status.text().startswith(failed_prefix) or self.status.text().startswith('翻译失败：'):
            self.status.clear()
        if not self.busy and not self.status.text():
            self.status.setText(translating)
        job = Job(lambda worker: translate_to_english(text, self.browser_proxy))
        self._translation_job = job
        self.jobs.add(job)
        _WORKERS.add(job)
        self.update_translation_controls()
        def translated(result):
            if not self._closing and revision == self._query_revision:
                self.search_input.selectAll()
                self.search_input.insert(result)
                self._translation_pair = (text.strip(), result.strip())
        def failed(message):
            if not self._closing and revision == self._query_revision:
                self.status.setText(failed_prefix + message)
        def release():
            self.jobs.discard(job)
            _WORKERS.discard(job)
            self._translation_job = None
            if not self._closing:
                if self.status.text() in (translating, '正在翻译…'):
                    self.status.clear()
                self.update_translation_controls()
        job.done.connect(translated)
        job.failed.connect(failed)
        job.finished.connect(release)
        job.start()

    def context_menu(self, position):
        menu = self.build_context_menu(self.grid.itemAt(position))
        if menu is not None:
            try:
                menu.exec(self.grid.viewport().mapToGlobal(position))
            finally:
                menu.deleteLater()

    def build_context_menu(self, item):
        if item is None or not item.data(ENTRY_ROLE):
            return None
        entry = dict(item.data(ENTRY_ROLE))
        path, dimensions = item.data(PATH_ROLE), item.data(SIZE_ROLE)
        menu = QMenu(self.grid)
        menu.addAction(tr('Image details', '图片详细信息')).triggered.connect(
            lambda: self.show_details(entry, dimensions))
        menu.addAction(tr('Open source page', '打开原网址')).triggered.connect(
            lambda: self.open_original(entry))
        similar = menu.addAction(tr('Find similar images', '查找相似图片'))

        similar.triggered.connect(lambda: self.find_similar(entry, path))
        return menu

    def show_details(self, entry, dimensions=None):
        if self.details_dialog is not None:
            self.details_dialog.close()
            self.details_dialog.deleteLater()
        dialog = QDialog(self)
        dialog.setWindowTitle(tr('Image details', '图片详细信息'))
        dialog.resize(520, 340)
        text = QPlainTextEdit(dialog)
        text.setReadOnly(True)
        width, height = dimensions or (entry.get('width'), entry.get('height'))
        missing = tr('Not provided', '未提供')
        size = f'{width} × {height}' if width and height else missing
        fields = [
            (tr('Title', '图片名'), entry.get('title') or missing),
            (tr('Source', '来源'), entry.get('source') or missing),
            (tr('Size', '尺寸'), size),
            (tr('Website', '原始网站'), entry.get('website_url') or entry.get('source_url') or missing),
            (tr('Source page', '来源页面'), entry.get('detail_url') or missing),
            (tr('Image URL', '图片地址'), entry.get('image_url') or tr('Unresolved', '未解析')),
            (tr('Description', '说明'), entry.get('description') or missing),
        ]
        text.setPlainText('\n\n'.join(name + ': ' + str(value) for name, value in fields))
        layout = QVBoxLayout(dialog)
        layout.addWidget(text)
        self.details_dialog = dialog
        dialog.show()

    def open_original(self, entry):
        for key in ('website_url', 'source_url', 'detail_url'):
            url = entry.get(key)
            if not isinstance(url, str) or not url:
                continue
            try:
                validate_remote_url(url)
            except ValueError:
                continue
            if not QDesktopServices.openUrl(QUrl(url)):
                self.status.setText(tr('Could not open the source URL.', '无法打开来源网址。'))
            return
        self.status.setText(tr('This image has no usable source URL.', '这张图片没有可用的来源网址。'))

    def similar_results(self, browser, entry, path=None):
        if path and Path(path).is_file():
            with open(path, 'rb') as image_file:
                data = image_file.read(MAX_BYTES + 1)
        else:
            resolved = browser.resolve(entry)
            if not isinstance(resolved, dict) or not resolved.get('url'):
                raise ValueError(tr('Could not fetch this image.', '无法取得这张图片的内容。'))
            data = self.downloader(resolved['url'], resolved.get('referer', ''))
        return browser.similar(similarity_jpeg(data), limit=24)

    def find_similar(self, entry, path=None):
        if self._closing:
            return
        self._pending_query = None
        self._pending_library = None
        self._pending_gallery_back = False
        self.flush_favorite_snapshot()
        self.cancel_preview_load()
        if self.busy:
            self._pending_similar = (dict(entry), path)
            self.status.setText(tr(
                'Similar search queued; it will run after the current image job…',
                '相似搜索已排队，当前图片任务完成后执行…',
            ))
            return
        cached = self._prepared_cache.get((entry.get('source'), entry.get('thumbnail')))
        if not path and cached and Path(cached[0]).is_file():
            path = cached[0]
        frame = self.capture_gallery()
        self.has_more = False
        self._more_pending = False
        self.status.setText(tr('Finding similar images…', '正在查找相似图片…'))
        def operation(job):
            return self.similar_results(self.get_browser(), entry, path)
        def loaded(entries):
            self._active_search = None
            self._cached_page = False
            self.generation += 1
            for job in list(self.jobs):
                job.requestInterruption()
            self._search_source = 'pinterest'
            self.source.setCurrentIndex(self.source.findData('pinterest'))
            self.search_input.clear()
            self.search_input.setPlaceholderText(tr(
                'Similar results · type keywords to search again',
                '相似结果 · 输入关键词可重新搜索',
            ))
            self._more_retry_at = 0
            self.display_results(entries)
            self.remember_similar_parent(frame, entry, path)
            self.status.clear()
        def failed(message):
            self.has_more = frame['has_more']
            self._pagination_rebuild = frame['context']
            self._cached_page = bool(frame['context'])
        self.run_job(operation, loaded, on_failure=failed)

    def resume_similarity(self):
        if self._pending_similar is not None and not self.busy and not self._closing:
            entry, path = self._pending_similar
            self._pending_similar = None
            self.find_similar(entry, path)

    def get_browser(self):
        if self.browser is None:
            from .backend import Backend
            self.browser = Backend()
        if hasattr(self.browser, 'start'):
            self.browser.start(self.browser_profile, self.browser_proxy)
        return self.browser

    def update_source_controls(self):
        self.update_library_controls()
        google = self.source.currentData() == 'google'
        if hasattr(self, 'verify_button'):
            self.verify_button.setEnabled(google and not self.busy and not self._closing)
            self.verify_button.setVisible(google)
        if hasattr(self, 'reset_profile_button'):
            self.reset_profile_button.setEnabled(not self.busy and not self._closing)

    def run_job(self, operation, success, background=False, lock_grid=True, on_failure=None):
        if self._closing:
            return None
        generation = self.generation
        if not background:
            self.busy = True
            self.search_button.setEnabled(True)

            if lock_grid:
                self.grid.setEnabled(False)
        job = Job(operation)
        self.jobs.add(job)
        _WORKERS.add(job)
        released = False
        def release():
            nonlocal released
            if released:
                return
            released = True
            if not background:
                self.busy = False
                if self._closing:
                    return
                self.search_button.setEnabled(True)
                self.update_source_controls()
                self.grid.setEnabled(True)

        def completed(result):
            release()
            if self._closing or generation != self.generation or job.isInterruptionRequested():
                return
            success(result)
            self.resume_pending_search()
            self.resume_gallery_back()
            self.resume_library()
            self.resume_similarity()
            self.resume_paging()
        def failed(message):
            release()
            if self._closing or generation != self.generation or job.isInterruptionRequested():
                return
            if not background:
                self.status.setText(tr('Failed: ', '失败：') + message)
            if on_failure is not None:
                on_failure(message)
            self.resume_pending_search()
            self.resume_gallery_back()
            self.resume_library()
            self.resume_similarity()
            self.resume_paging()
        job.done.connect(completed)
        job.failed.connect(failed)
        def finished():
            release()
            self.jobs.discard(job)
            _WORKERS.discard(job)
            if not self._closing:
                self.resume_pending_search()
                self.resume_gallery_back()
                self.resume_library()
                self.resume_similarity()
                self.resume_paging()
        job.finished.connect(finished)
        job.start()
        return job

    def resume_pending_search(self):
        if self._pending_query is not None and not self.busy and not self._closing:
            request = self._pending_query
            self._pending_query = None
            self.search(request)

    def search(self, request=None):
        if not isinstance(request, tuple):
            request = (self.source.currentData(), self.search_input.text().strip(), self.original_query())
        source, query, original_query = request
        if self._closing or not query:
            return
        self._pending_library = None
        self._pending_similar = None
        self._pending_gallery_back = False
        if self.busy:
            self._pending_query = request
            self.generation += 1
            for job in list(self.jobs):
                job.requestInterruption()
            self.status.setText(tr(
                'Search queued; the latest request will run after the current job…',
                '搜索已排队，当前任务完成后执行最后一次提交…',
            ))
            return
        self._pending_query = None
        self.flush_favorite_snapshot()
        self.cancel_preview_load()
        self.generation += 1
        for job in list(self.jobs):
            job.requestInterruption()
        self.status.setText(tr('Searching…', '正在搜索…'))
        self.search_input.setPlaceholderText(tr('Search photo references…', '搜索照片素材…'))
        previous_source, previous_more = self._search_source, self.has_more
        history_error = ''
        try:
            self.search_store.record_search(source, query, original_query)
        except (OSError, ValueError) as error:
            history_error = tr('History not saved: ', '历史未保存：') + str(error)
        self.update_library_controls()
        self._search_source = source
        self.has_more = False
        self._more_pending = False
        def loaded(entries):
            self.reset_gallery_navigation(dict(mode='keyword', source=source, query=query))
            self._active_search = (source, query)
            self._cached_page = False
            self.display_results(entries)
            self.schedule_snapshot(reset=True)
            if history_error:
                self.status.setText(history_error)
        def failed(message):
            self._search_source, self.has_more = previous_source, previous_more
            self._pagination_rebuild = self._page_context
            self._cached_page = bool(self._page_context)
            if history_error:
                self.status.setText(tr('Failed: ', '失败：') + message + '; ' + history_error)
        self.run_job(lambda job: self.get_browser().search(source, query, limit=24), loaded, on_failure=failed)

    def thumbnail_bytes(self, entry):
        url = entry['thumbnail']
        with self._cache_lock:
            if url in self._thumbnail_cache:
                self._thumbnail_cache.move_to_end(url)
                return self._thumbnail_cache[url]
        data = self.downloader(url, entry.get('detail_url', ''))
        if len(data) <= 16 * 1024 * 1024:
            with self._cache_lock:
                previous = self._thumbnail_cache.pop(url, None)
                if previous is not None:
                    self._thumbnail_bytes -= len(previous)
                self._thumbnail_cache[url] = data
                self._thumbnail_bytes += len(data)
                while len(self._thumbnail_cache) > 128 or self._thumbnail_bytes > 16 * 1024 * 1024:
                    _, removed = self._thumbnail_cache.popitem(last=False)
                    self._thumbnail_bytes -= len(removed)
        return data

    def display_results(self, entries, cached_images=None):
        self.cancel_preview_load()
        self._page_thumbnails.clear()
        self.grid.clear()
        self._gallery_ids.clear()

        if entries:
            self._search_source = entries[0].get('source') or self._search_source
        self.has_more = bool(hasattr(self.browser, 'more'))
        if self.has_more and hasattr(self.browser, 'has_more'):
            self.has_more = self.browser.has_more(self._search_source)
        self.append_results(entries, cached_images=cached_images)
        self._sync_grid_empty_state()

    def append_results(self, entries, cached_images=None):
        fresh = []
        for entry in entries:
            identity = image_identity(entry)
            if identity in self._gallery_ids:
                continue
            self._gallery_ids.add(identity)
            fresh.append(entry)
        base_index = self.grid.count()
        for entry in fresh:
            item = QListWidgetItem()
            item.setData(ENTRY_ROLE, dict(entry))
            item.setData(Qt.ItemDataRole.AccessibleTextRole, image_label(entry))
            item.setSizeHint(QSize(self.grid.tile_size, self.grid.tile_size))
            if cached_images is not None:
                image = cached_images.get(entry['thumbnail'])
                if image is not None and not image.isNull():
                    item.setIcon(QIcon(QPixmap.fromImage(image)))
            self.grid.addItem(item)
        self.update_preview_navigation()
        if self.grid.count():
            self.status.clear()
        else:
            self.status.setText(tr(
                'No results; open the login / verification window to check.',
                '没有可用结果；可以打开登录 / 验证窗口检查。',
            ))
        self._sync_grid_empty_state()
        if not fresh:
            return 0
        if cached_images is not None:
            return len(fresh)
        generation = self.generation
        def thumbnails(job):
            def fetch(index, entry):
                if job.isInterruptionRequested():
                    return None
                try:
                    return generation, index, self.thumbnail_bytes(entry), 0, ''
                except Exception as error:
                    return generation, index, b'', 0, str(error)
            futures = set()
            entries = iter(enumerate(fresh))
            def submit_next():
                if job.isInterruptionRequested():
                    return
                pair = next(entries, None)
                if pair is not None:
                    index, entry = pair
                    futures.add(self._thumbnail_executor.submit(fetch, base_index+index, entry))
            for _ in range(4):
                submit_next()
            try:
                while futures and not job.isInterruptionRequested():
                    done, _ = wait(futures, timeout=.05, return_when=FIRST_COMPLETED)
                    for future in done:
                        futures.remove(future)
                        if job.isInterruptionRequested():
                            break
                        try:
                            result = future.result()
                            if result is not None:
                                job.thumbnail.emit(result)
                        except Exception:
                            pass
                        submit_next()
            finally:
                for future in futures:
                    future.cancel()
        job = Job(thumbnails)
        self.jobs.add(job)
        _WORKERS.add(job)
        job.thumbnail.connect(self.set_thumbnail)
        job.finished.connect(lambda: self.jobs.discard(job))
        job.finished.connect(lambda: _WORKERS.discard(job))
        job.start()
        return len(fresh)

    def scroll_changed(self, value):
        if self.grid.resizing_tiles or self._restoring_cache:
            return
        self.schedule_snapshot()
        scrollbar = self.grid.verticalScrollBar()
        if scrollbar.maximum() > 0 and value >= scrollbar.maximum() - 80:
            self.load_more()

    def resume_paging(self):
        if self._more_pending and not self.busy and not self._loading_more:
            self._more_pending = False
            QTimer.singleShot(0, self.load_more)

    def load_more(self):
        if self._restoring_cache or not self.has_more or self._loading_more or time.monotonic() < self._more_retry_at:
            return
        if self.busy:
            self._more_pending = True
            return
        self._loading_more = True
        self.status.setText(tr('Loading more…', '正在加载更多…'))
        source = self._search_source
        generation = self.generation
        cached_query = self._active_search[1] if self._cached_page and self._active_search else None
        rebuild = self._pagination_rebuild or (dict(mode='keyword', source=source, query=cached_query) if cached_query is not None else None)
        known = set(self._gallery_ids)
        def operation(job):
            browser = self.get_browser()
            if rebuild is not None:
                entries = (browser.search(source, rebuild['query'], limit=24) if rebuild['mode'] == 'keyword'
                           else self.similar_results(browser, rebuild['entry'], rebuild['path']))
                for attempt in range(3):
                    fresh = [entry for entry in entries if image_identity(entry) not in known]
                    if fresh or not browser.has_more(source) or job.isInterruptionRequested():
                        break
                    entries = browser.more(source, limit=24)
            else:
                entries = browser.more(source, limit=24)
            return entries, browser.has_more(source)
        def loaded(result):
            self._loading_more = False
            if generation != self.generation:
                return
            entries, self.has_more = result
            self._cached_page = False
            self._pagination_rebuild = None
            added = self.append_results(entries)
            self.schedule_snapshot(reset=True)
            if not added:
                self._more_retry_at = time.monotonic() + 1
                self.status.setText(
                    tr('No more images yet; scroll again later to retry.', '暂未加载到更多图片；稍后下滑可重试。')
                    if self.has_more else
                    tr('Reached the end of these search results.', '已到当前搜索结果末尾。'))
            if rebuild is None:
                self.selection_changed(self.grid.currentItem())
        def failed(message):
            self._loading_more = False
            self._more_retry_at = time.monotonic() + 1
            if rebuild is None:
                self.selection_changed(self.grid.currentItem())
        self.run_job(operation, loaded, lock_grid=False, on_failure=failed)

    def set_thumbnail(self, result):
        generation, index, data = result[:3]
        if generation != self.generation or index >= self.grid.count():
            return
        item = self.grid.item(index)
        revision, error = result[3:] if len(result) == 5 else (None, '')
        if revision is not None and revision != (item.data(THUMB_REQUEST_ROLE) or 0):
            return
        image = thumbnail_image(data) if not error else QImage()
        if image.isNull():
            if item.icon().isNull():
                item.setData(THUMB_ERROR_ROLE, error or tr('Could not decode thumbnail', '缩略图无法解码'))
                item.setToolTip(
                    tr('Thumbnail failed to load. Click the center button to retry.\n',
                       '缩略图加载失败，点击中央按钮重试。\n')
                    + (error or tr('Could not decode image', '无法解码图片')))
            return
        item.setData(THUMB_ERROR_ROLE, '')
        item.setToolTip('')
        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            self.grid.item(index).setIcon(QIcon(pixmap))
            url = self.grid.item(index).data(ENTRY_ROLE)['thumbnail']
            self._page_thumbnails[url] = data
            while sum(len(value) for value in self._page_thumbnails.values()) > 16 * 1024 * 1024:
                self._page_thumbnails.popitem(last=False)
            self.schedule_snapshot()

    def selection_changed(self, item, previous=None):
        self.update_preview_navigation()
        self.schedule_snapshot()
        if self._pending_preview != (self.generation, item):
            if self._preview_navigation:
                self._pending_preview = None
            else:
                self.cancel_preview_load()
        if self._pending_similar is not None:
            return
        if item is not None and not item.data(PATH_ROLE):
            entry = item.data(ENTRY_ROLE)
            if entry:
                key = (entry.get('source'), entry['thumbnail'])
                cached = self._prepared_cache.get(key)
                if cached and Path(cached[0]).is_file():
                    item.setData(PATH_ROLE, cached[0])
                    item.setData(SIZE_ROLE, cached[1:])
                    self._prepared_cache.move_to_end(key)

        if item is None:
            return
        if item.data(PATH_ROLE):
            dimensions = item.data(SIZE_ROLE)
            self.last_size = dimensions
            self.status.clear()
            self.resume_preview(item)
            self.schedule_adjacent_prefetch()
            return
        if self.uses_adjacent_prefetch(item):
            return
        if self.busy:
            return
        entry = item.data(ENTRY_ROLE)
        generation = self.generation
        self.status.setText(tr('Fetching full image…', '正在获取大图…'))
        def operation(job):
            result = self.get_browser().resolve(entry)
            return self.downloader(result['url'], result.get('referer', ''))
        def prepared(data):
            if generation != self.generation:
                return
            try:
                path, width, height = prepare_image(data, self.cache_dir, entry.get('title', 'image'))
                item.setData(PATH_ROLE, path)
                item.setData(SIZE_ROLE, (width, height))
                item.setData(THUMB_ERROR_ROLE, '')
                item.setToolTip('')
                key = (entry.get('source'), entry['thumbnail'])
                self._prepared_cache[key] = (path, width, height)
                self._prepared_cache.move_to_end(key)
                while len(self._prepared_cache) > 32:
                    self._prepared_cache.popitem(last=False)
                self.last_size = (width, height)
                original = QPixmap(path)
                item.setIcon(QIcon(original.scaled(QSize(384, 384).boundedTo(original.size()), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))

                if self.grid.currentItem() == item:
                    self.status.clear()
                    self.resume_preview(item)
                else:
                    self.resume_current_image(item)
            except Exception as error:
                self.status.setText(tr('Failed: ', '失败：') + str(error))
                failed(str(error))
        def failed(message):
            if self._pending_preview == (generation, item):
                if self.preview_dialog is not None and self.preview_dialog.isVisible():
                    self.preview_dialog.set_error(message)
                self._pending_preview = None
            self.resume_current_image(item)
        self.run_job(operation, prepared, lock_grid=False, on_failure=failed)

    def resume_current_image(self, completed_item):
        current = self.grid.currentItem()
        if current is not None and current != completed_item:
            self.selection_changed(current)

    def drag_not_ready(self):
        if not self.busy:
            self.selection_changed(self.grid.currentItem())
        self.status.setText(tr(
            'Preparing the full image; drag onto the canvas when ready.',
            '大图准备中；完成后再拖入画布。',
        ))

    def show_browser(self):
        if self.busy or self.source.currentData() != 'google' or self._closing:
            return
        self.run_job(
            lambda job: self.get_browser().show(),
            lambda result: self.status.setText(tr(
                'Finish Google verification, then search again. The window will close and return to the background.',
                '完成 Google 验证后回来重新搜索；验证窗口将关闭并恢复后台运行。',
            )))

    def reset_browser_profile(self):
        if self.busy or self._closing:
            return
        from .qtcompat import QMessageBox
        answer = QMessageBox.question(
            self,
            tr('Reset browser profile', '重置浏览器配置'),
            tr(
                'Delete the Quick Image Search browser profile on disk?\n\n'
                'This clears login / verification cookies for Google and Pinterest. '
                'You will need to verify again next time.',
                '删除快速搜图的浏览器本地配置？\n\n'
                '这会清除 Google / Pinterest 的登录与验证 Cookie，下次需要重新验证。',
            ),
        )
        yes = getattr(QMessageBox.StandardButton, 'Yes', None) or QMessageBox.Yes
        if answer != yes:
            return
        try:
            browser = self.browser
            if browser is not None and hasattr(browser, 'close'):
                browser.close()
        except Exception:
            pass
        self.browser = None
        profile = Path(self.browser_profile)
        removed = False
        try:
            import shutil
            if profile.exists():
                shutil.rmtree(profile, ignore_errors=False)
                removed = True
            sibling = profile.with_name(profile.name + '-background')
            if sibling.exists():
                shutil.rmtree(sibling, ignore_errors=False)
                removed = True
        except OSError as error:
            self.status.setText(tr('Could not reset profile: ', '无法重置配置：') + str(error))
            return
        self.status.setText(
            tr('Browser profile reset. Search again when ready.', '浏览器配置已重置。准备好后请重新搜索。')
            if removed else
            tr('No browser profile folder was present.', '没有找到浏览器配置目录。'))

    def build_status_menu(self):
        menu = QMenu(self.status)
        if self.source.currentData() == 'google':
            action = menu.addAction(tr('Open Google verification window', '打开 Google 验证窗口'))
            action.setEnabled(not self.busy and not self._closing)
            action.triggered.connect(self.show_browser)
        reset = menu.addAction(tr('Reset browser profile…', '重置浏览器配置…'))
        reset.setEnabled(not self.busy and not self._closing)
        reset.triggered.connect(self.reset_browser_profile)
        return menu

    def show_status_menu(self, position):
        menu = self.build_status_menu()
        try:
            if menu.actions():
                menu.exec(position)
        finally:
            menu.deleteLater()

    def closeEvent(self, event):
        # Closing a dock hides it; it may be reopened. Cancel its current work
        # and discard queued deliveries, but keep reusable services alive.
        self.flush_grid_size()
        self.flush_favorite_snapshot()
        self.generation += 1
        self._pending_query = self._pending_similar = self._pending_library = None
        self.stop_adjacent_prefetch()
        for job in list(self.jobs):
            job.requestInterruption()
        super().closeEvent(event)

    def shutdown(self, deadline=None):
        if self._closing:
            return
        self.flush_grid_size()
        self.flush_favorite_snapshot()
        self._closing = True
        self.generation += 1
        self._snapshot_timer.stop()
        self._cache_status_timer.stop()
        self._grid_save_timer.stop()
        self.stop_adjacent_prefetch()
        self._pending_preview = None
        if self.preview_dialog is not None:
            self.preview_dialog.close()
        self._pending_similar = self._pending_library = self._pending_query = None
        self._back_stack.clear()
        self._begin_cleanup(deadline)

    def _begin_cleanup(self, deadline=None):
        # Also safe from QObject.destroyed: never access a child widget here.
        if self._cleanup_started:
            return
        self._cleanup_started = True
        self._closing = True
        self.generation += 1
        jobs = list(self.jobs)
        for job in jobs:
            job.requestInterruption()
        self._thumbnail_executor.shutdown(wait=False)
        self._cache_executor.shutdown(wait=False)
        end = deadline if deadline is not None else time.monotonic()+3
        browser = self.browser
        done = self._shutdown_done
        def cleanup():
            try:
                # This wait is outside the GUI thread and shares one deadline.
                for job in jobs:
                    job.wait(max(0, int((end-time.monotonic())*1000)))
                if browser is not None and hasattr(browser, 'close'):
                    from .backend import Backend
                    if isinstance(browser, Backend):
                        browser.close(deadline=end)
                    elif not any(job.isRunning() for job in jobs):
                        browser.close()
                self._thumbnail_executor.shutdown(wait=True, deadline=end)
                self._cache_executor.shutdown(wait=True, deadline=end)
            finally:
                done.set()
        threading.Thread(target=cleanup, name='search-shutdown', daemon=True).start()
