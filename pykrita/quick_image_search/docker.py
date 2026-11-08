from .qtcompat import (QMimeData, QUrl, QThread, pyqtSignal, Qt, QSize, QStandardPaths, QBuffer, QIODevice, QTimer, QPoint, QEvent, QRect, QRectF, QPointF, QImage, QImageReader, QPixmap, QIcon, QDrag, QDesktopServices, QPainter, QPen, QColor, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QComboBox, QListWidget, QListWidgetItem, QAbstractItemView, QListView, QLabel, QDialog, QScrollArea, QStyledItemDelegate, QStyleOptionViewItem, QStyle, QMenu, QPlainTextEdit, QSizePolicy, QToolButton, QDockWidget as _QDockWidget)
QDockWidget = _QDockWidget
"""Native Krita search panel; no external Qt or Python packages required."""
from pathlib import Path
import hashlib
import html
import json
import ipaddress
import urllib.parse
import urllib.request
import uuid
import threading
import re
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed

from krita import DockWidget, Krita
from .drop_router import DRAG_FORMAT, install_drop_router
from .search_library import SearchLibraryMixin, thumbnail_image, image_identity
from .gallery_experience import GalleryExperienceMixin
from .status_indicator import StatusIndicator

MAX_BYTES = 24 * 1024 * 1024
MAX_PIXELS = 32 * 1024 * 1024
ENTRY_ROLE = Qt.ItemDataRole.UserRole
PATH_ROLE = Qt.ItemDataRole.UserRole + 1
SIZE_ROLE = Qt.ItemDataRole.UserRole + 2
THUMB_ERROR_ROLE = Qt.ItemDataRole.UserRole + 3
THUMB_REQUEST_ROLE = Qt.ItemDataRole.UserRole + 4
_WORKERS = set()


def has_chinese(text):
    return bool(re.search(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f]', text))


def translate_to_english(text, proxy=''):
    text = text.strip()
    if not has_chinese(text):
        return text
    if len(text.encode('utf-8')) > 500:
        raise ValueError('关键词过长，请缩短（服务单次上限 500 字节）。')
    query = urllib.parse.urlencode({'q': text, 'langpair': 'zh-CN|en'})
    request = urllib.request.Request('https://api.mymemory.translated.net/get?' + query,
                                     headers={'Accept': 'application/json'})
    handlers = [urllib.request.ProxyHandler({'http': proxy, 'https': proxy})] if proxy else []
    with urllib.request.build_opener(*handlers).open(request, timeout=12) as response:
        data = response.read(65537)
    if len(data) > 65536:
        raise ValueError('翻译响应过大，请稍后重试。')
    try:
        payload = json.loads(data.decode('utf-8'))
    except ValueError as error:
        raise ValueError('未收到有效译文，请稍后重试。') from error
    if not isinstance(payload, dict):
        raise ValueError('未收到有效译文，请稍后重试。')
    if payload.get('quotaFinished') is True or str(payload.get('responseStatus')) == '429':
        raise ValueError('翻译服务今日免费额度已用完，请稍后再试。')
    if str(payload.get('responseStatus')) != '200':
        raise ValueError('翻译服务暂不可用，请稍后重试。')
    result = payload.get('responseData', {})
    result = result.get('translatedText') if isinstance(result, dict) else None
    if not isinstance(result, str) or not result.strip():
        raise ValueError('未收到有效译文，请稍后重试。')
    return html.unescape(result).strip()


def prepare_image(data, directory, title='image'):
    if len(data) > MAX_BYTES:
        raise ValueError('Image download exceeds the 24 MB limit')
    buffer = QBuffer()
    buffer.setData(data)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    size = reader.size()
    if size.isValid() and size.width() * size.height() > MAX_PIXELS:
        raise ValueError('Image exceeds the 32 megapixel limit')
    image = reader.read()
    if image.isNull():
        raise ValueError('The downloaded file is not a readable image')
    if image.width() * image.height() > MAX_PIXELS:
        raise ValueError('Image exceeds the 32 megapixel limit')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (hashlib.sha256(data).hexdigest()[:24] + '.png')
    if not image.save(str(path), 'PNG'):
        raise OSError('Cannot write the temporary image')
    return str(path.resolve()), image.width(), image.height()


def similarity_jpeg(data):
    if not data or len(data) > MAX_BYTES:
        raise ValueError('相似搜索图片为空或超过 24 MB。')
    buffer = QBuffer()
    buffer.setData(data)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > MAX_PIXELS:
        raise ValueError('相似搜索图片无法读取或超过 32 百万像素。')
    if max(size.width(), size.height()) > 1024:
        reader.setScaledSize(size.scaled(1024, 1024, Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        raise ValueError('无法解码相似搜索图片。')
    output = QBuffer()
    output.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(output, 'JPEG', 85):
        raise ValueError('无法准备相似搜索图片。')
    return bytes(output.data())


def file_drag_mime(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('Prepare the image before dragging')
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    mime.setData(DRAG_FORMAT, b'1')
    return mime


def image_label(entry):
    title = str(entry.get('image_name') or entry.get('title') or '').strip()
    title = re.sub(r'^其中包括图片[:：]\s*', '', title)
    title = title.splitlines()[0].strip() if title else ''
    title = re.split(r'\s+(?:\||—|–|-)\s+', title, maxsplit=1)[0]
    return title[:47] + '…' if len(title) > 48 else (title or 'Image')


def validate_remote_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Unsupported image URL')
    host = parsed.hostname.lower()
    if host == 'localhost' or host.endswith(('.localhost', '.local')):
        raise ValueError('Local image URLs are not allowed')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError('Private image URLs are not allowed')
    return url


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        validate_remote_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def download_image(url, referer='', proxy=''):
    validate_remote_url(url)
    headers = {'User-Agent': 'Mozilla/5.0'}
    if referer:
        headers['Referer'] = validate_remote_url(referer)
    handlers: list[urllib.request.BaseHandler] = [SafeRedirect()]
    if proxy:
        handlers.append(urllib.request.ProxyHandler({'http': proxy, 'https': proxy}))
    opener = urllib.request.build_opener(*handlers)
    with opener.open(urllib.request.Request(url, headers=headers), timeout=15) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Image download exceeds the 24 MB limit')
    return data


class Job(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    thumbnail = pyqtSignal(object)

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    def run(self):
        try:
            result = self.operation(self)
            if not self.isInterruptionRequested():
                self.done.emit(result)
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))


TransientStatus = StatusIndicator


def thumbnail_retry_rect(rect):
    return QRect(rect.center().x() - 16, rect.center().y() - 16, 32, 32)


class ImageTileDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(self.parent().tile_size, self.parent().tile_size)

    def paint(self, painter, option, index):
        style = QStyleOptionViewItem(option)
        self.initStyleOption(style, index)
        icon = QIcon(style.icon)
        style.text = ''
        style.icon = QIcon()
        widget_style = style.widget.style() if style.widget else QApplication.style()
        painter.save()
        widget_style.drawControl(QStyle.ControlElement.CE_ItemViewItem, style, painter, style.widget)
        box = option.rect.adjusted(6, 6, -6, -6)
        if not icon.isNull():
            pixmap = icon.pixmap(QSize(384, 384))
            pixmap = pixmap.scaled(box.size().boundedTo(pixmap.size()), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            target = QStyle.alignedRect(option.direction, Qt.AlignmentFlag.AlignCenter, pixmap.size(), box)
            painter.drawPixmap(target, pixmap)
        if index.data(THUMB_ERROR_ROLE):
            retry = thumbnail_retry_rect(option.rect)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(30, 30, 30, 210 if option.state & QStyle.StateFlag.State_MouseOver else 110))
            painter.drawRoundedRect(retry, 4, 4)
            painter.setPen(QPen(QColor('#dddddd'), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(retry.adjusted(8, 8, -8, -8), 40 * 16, 285 * 16)
            painter.drawLine(retry.right() - 7, retry.top() + 7, retry.right() - 7, retry.top() + 13)
            painter.drawLine(retry.right() - 7, retry.top() + 13, retry.right() - 13, retry.top() + 13)
        painter.restore()


class ImageGrid(QListWidget):
    needs_image = pyqtSignal()
    more_requested = pyqtSignal()
    retry_requested = pyqtSignal(object)
    tile_size_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setMouseTracking(True)
        self._retry_press = False
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.tile_size = 144
        self.resizing_tiles = False
        self._zoom_remainder = 0
        self.setItemDelegate(ImageTileDelegate(self))
        self.setIconSize(QSize(192, 192))
        self.setGridSize(QSize(144, 144))
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setSpacing(4)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if event.button() == Qt.MouseButton.LeftButton and item is not None and item.data(THUMB_ERROR_ROLE):
            if thumbnail_retry_rect(self.visualItemRect(item)).contains(event.pos()):
                self._retry_press = True
                self.retry_requested.emit(item)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._retry_press and event.button() == Qt.MouseButton.LeftButton:
            self._retry_press = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._zoom_remainder += event.angleDelta().y()
            steps = int(self._zoom_remainder / 120)
            self._zoom_remainder -= steps * 120
            if steps:
                self.set_tile_size(self.tile_size + steps * 16)
                self.tile_size_changed.emit(self.tile_size)
            event.accept()
            return
        super().wheelEvent(event)
        scrollbar = self.verticalScrollBar()
        if event.angleDelta().y() < 0 and scrollbar.value() >= scrollbar.maximum() - 80:
            self.more_requested.emit()

    def set_tile_size(self, size):
        size = max(80, min(320, int(size)))
        if size == self.tile_size:
            return
        anchor = self.itemAt(QPoint(8, 8))
        self.resizing_tiles = True
        try:
            self.tile_size = size
            self.setGridSize(QSize(size, size))
            self.setIconSize(QSize(size - 12, size - 12))
            for index in range(self.count()):
                self.item(index).setSizeHint(QSize(size, size))
            self.doItemsLayout()
            if anchor is not None:
                self.scrollToItem(anchor, QAbstractItemView.ScrollHint.PositionAtTop)
        finally:
            self.resizing_tiles = False
        self.viewport().update()

    def startDrag(self, supported_actions):
        item = self.currentItem()
        if item is None:
            return
        path = item.data(PATH_ROLE)
        if not path:
            self.needs_image.emit()
            return
        try:
            drag = QDrag(self)
            drag.setMimeData(file_drag_mime(path))
            drag.setPixmap(QPixmap(path).scaled(120, 90, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            drag.exec(Qt.DropAction.CopyAction)
        except Exception as error:
            self.setToolTip(str(error))


class LoadingSpinner(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(36, 36)
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.advance)

    def advance(self):
        self.angle = (self.angle + 30) % 360
        self.update()

    def showEvent(self, event):
        self.timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#aaaaaa'), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(4, 4, 28, 28, -self.angle * 16, 270 * 16)


def restored_preview_geometry(value, default, screens):
    try:
        values = json.loads(value)
        if not isinstance(values, list) or len(values) != 4 or not all(type(v) is int and abs(v) < 2 ** 30 for v in values):
            return QRect(default)
        x, y, width, height = values
        if width <= 0 or height <= 0:
            return QRect(default)
        center = QPoint(x + width // 2, y + height // 2)
        containing = [screen for screen in screens if screen.contains(center)]
        bounds = containing[0] if containing else min(screens, key=lambda screen: (screen.center() - center).manhattanLength())
        width = min(max(96, width), bounds.width())
        height = min(max(128, height), bounds.height())
        x = max(bounds.left(), min(x, bounds.right() - width + 1))
        y = max(bounds.top(), min(y, bounds.bottom() - height + 1))
        return QRect(x, y, width, height)
    except (ValueError, TypeError):
        return QRect(default)


class PreviewCanvas(QLabel):
    def paintEvent(self, event):
        preview = self.parentWidget()
        if preview._image.isNull():
            return super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(preview.image_rect(), preview._image, QRectF(preview._image.rect()))


class ImagePreview(QDialog):
    navigate = pyqtSignal(int)
    retry_requested = pyqtSignal()
    context_requested = pyqtSignal(QPoint)

    def __init__(self, path=None, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay, True)
        self._drag_origin = None
        self.zoom = 1.0
        self._image_pan = QPointF()
        self._pan_origin = None
        self._settings = Krita.instance()
        self._geometry_ready = False
        self._context_menu = None
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda point: self.context_requested.emit(self.mapToGlobal(point)))
        image = QPixmap(str(path)) if path else QPixmap()
        if path and image.isNull():
            raise ValueError('预览图片无法读取，请重新选择图片。')
        screen = QApplication.screenAt(parent.mapToGlobal(parent.rect().center())) if parent else None
        screen = screen or QApplication.primaryScreen()
        available = screen.availableGeometry()
        limit = QSize(max(1, available.width() - 64), max(1, available.height() - 64))
        self.loading = not bool(path)
        self._image = image
        size = image.size().boundedTo(limit) if path else QSize(640, 480).boundedTo(limit)
        self.setMinimumSize(96, 128)
        self.resize(size)
        self.image_label = PreviewCanvas(self)
        self.image_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.image_label.customContextMenuRequested.connect(lambda point: self.context_requested.emit(self.image_label.mapToGlobal(point)))
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if path:
            self.image_label.setPixmap(image.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.image_label.setGeometry(self.rect())
        self.spinner = LoadingSpinner(self)
        self.spinner.move(self.rect().center() - self.spinner.rect().center())
        self.spinner.setVisible(self.loading)
        self.error_label = QLabel(self)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setWordWrap(True)
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label.hide()
        self.retry_button = QPushButton('重试', self)
        self.retry_button.setToolTip('只重新获取当前图片，不刷新结果页')
        self.retry_button.clicked.connect(self.retry_requested.emit)
        self.retry_button.hide()
        self.close_button = QToolButton(self)
        self.close_button.setText('×')
        self.close_button.setToolTip('关闭预览（Esc）')
        self.close_button.setAccessibleName('关闭预览')
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        edge = min(32, size.width(), size.height())
        inset = min(8, max(0, (min(size.width(), size.height()) - edge) // 2))
        self.close_button.setGeometry(size.width() - edge - inset, inset, edge, edge)
        self.close_button.setStyleSheet('QToolButton { color: white; background: rgba(20,20,20,190); border: none; border-radius: 4px; font-size: 20px; } QToolButton:hover { background: rgba(50,50,50,230); }')
        self.close_button.clicked.connect(self.close)
        self.previous_button = QToolButton(self)
        self.next_button = QToolButton(self)
        for button, text, step, tooltip in ((self.previous_button, '‹', -1, '上一张（←）'),
                                           (self.next_button, '›', 1, '下一张（→）')):
            button.setText(text)
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet('QToolButton { color: #dddddd; background: rgba(20,20,20,100); border: none; border-radius: 4px; font-size: 24px; } QToolButton:hover { color: white; background: rgba(40,40,40,220); } QToolButton:disabled { color: #777777; background: rgba(20,20,20,50); }')
            button.setEnabled(False)
            button.clicked.connect(lambda checked=False, direction=step: self.navigate.emit(direction))
        default = QRect(available.center() - self.rect().center(), self.size())
        try:
            saved = self._settings.readSetting('quick_image_search', 'preview_geometry', '')
        except AttributeError:
            saved = ''
        self.setGeometry(restored_preview_geometry(saved, default, [s.availableGeometry() for s in QApplication.screens()]))
        self._geometry_ready = True
        for widget in (self, self.image_label, self.spinner, self.error_label):
            widget.setMouseTracking(True)
        self.update_content_geometry()

    def update_content_geometry(self):
        self.image_label.setGeometry(self.rect())
        if not self._image.isNull():
            self.image_label.setPixmap(self._image.scaled(self.size().boundedTo(self._image.size()), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.spinner.move(self.rect().center() - self.spinner.rect().center())
        error_height = min(80, max(32, self.height() - 96))
        error_top = (self.height() - error_height - 40) // 2
        self.error_label.setGeometry(20, error_top, max(0, self.width() - 40), error_height)
        self.retry_button.setGeometry((self.width() - 80) // 2, error_top + error_height + 8, 80, 32)
        self.close_button.setGeometry(self.width() - 40, 8, 32, 32)
        if hasattr(self, 'previous_button'):
            self.previous_button.setGeometry(8, (self.height() - 32) // 2, 32, 32)
            self.next_button.setGeometry(self.width() - 40, (self.height() - 32) // 2, 32, 32)

    def set_navigation(self, previous, following):
        self.previous_button.setEnabled(bool(previous))
        self.next_button.setEnabled(bool(following))

    def resizeEvent(self, event):
        if hasattr(self, 'close_button'):
            self.update_content_geometry()
        super().resizeEvent(event)

    def resize_edges(self, position):
        point = self.mapFromGlobal(position)
        return (point.x() < 8, point.x() >= self.width() - 8,
                point.y() < 8, point.y() >= self.height() - 8)

    def image_rect(self):
        if self._image.isNull():
            return QRectF()
        scale = min(1.0, self.width() / self._image.width(), self.height() / self._image.height()) * self.zoom
        width, height = self._image.width() * scale, self._image.height() * scale
        return QRectF((self.width() - width) / 2 + self._image_pan.x(),
                      (self.height() - height) / 2 + self._image_pan.y(), width, height)

    def zoom_at(self, position, steps):
        if self._image.isNull() or self.loading:
            return
        old_zoom = self.zoom
        old_rect = self.image_rect()
        self.zoom = max(0.1, min(16.0, old_zoom * (1.2 ** max(-20, min(20, steps)))))
        new_rect = self.image_rect()
        desired = position - (position - old_rect.topLeft()) * (self.zoom / old_zoom)
        self._image_pan += desired - new_rect.topLeft()
        self.image_label.update()

    def fit_image(self):
        self.zoom = 1.0
        self._image_pan = QPointF()
        self._pan_origin = None
        self.image_label.update()

    def update_resize_cursor(self, position):
        left, right, top, bottom = self.resize_edges(position)
        if (left and top) or (right and bottom):
            cursor = Qt.CursorShape.SizeFDiagCursor
        elif (right and top) or (left and bottom):
            cursor = Qt.CursorShape.SizeBDiagCursor
        elif left or right:
            cursor = Qt.CursorShape.SizeHorCursor
        elif top or bottom:
            cursor = Qt.CursorShape.SizeVerCursor
        else:
            cursor = Qt.CursorShape.OpenHandCursor
        self.setCursor(cursor)

    def set_image(self, path):
        image = QPixmap(str(path))
        if image.isNull():
            raise ValueError('预览图片无法读取，请重新选择图片。')
        self._image = image
        self.fit_image()
        self.loading = False
        self.spinner.hide()
        self.error_label.hide()
        self.retry_button.hide()
        self.image_label.setPixmap(image.scaled(self.size().boundedTo(image.size()), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def set_loading(self):
        self._image = QPixmap()
        self.fit_image()
        self._drag_origin = None
        self.loading = True
        self.image_label.clear()
        self.error_label.hide()
        self.retry_button.hide()
        self.spinner.show()

    def set_error(self, message):
        self.loading = False
        self.spinner.hide()
        self.error_label.setText('加载失败：' + message)
        self.error_label.setToolTip(message)
        self.error_label.show()
        self.retry_button.show()

    def showEvent(self, event):
        QApplication.instance().installEventFilter(self)
        super().showEvent(event)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self._drag_origin = None
        self._pan_origin = None
        self.save_geometry()
        super().hideEvent(event)

    def save_geometry(self):
        if not self._geometry_ready:
            return
        geometry = self.geometry()
        value = json.dumps([geometry.x(), geometry.y(), geometry.width(), geometry.height()])
        try:
            self._settings.writeSetting('quick_image_search', 'preview_geometry', value)
        except AttributeError:
            pass
        except (OSError, RuntimeError):
            parent = self.parentWidget()
            if parent is not None and hasattr(parent, 'status'):
                parent.status.setText('预览位置与尺寸保存失败。')

    def eventFilter(self, watched, event):
        image_widgets = (self, self.image_label, self.spinner, self.error_label)
        if self._context_menu is not None and isinstance(watched, QWidget) and (watched is self._context_menu or self._context_menu.isAncestorOf(watched)):
            return False
        if self.isVisible() and watched in image_widgets + (self.close_button, self.previous_button, self.next_button, self.retry_button) and event.type() == QEvent.Type.KeyPress:
            if event.modifiers() == Qt.KeyboardModifier.NoModifier and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                self.navigate.emit(-1 if event.key() == Qt.Key.Key_Left else 1)
                event.accept()
                return True
        if self.isVisible() and watched in image_widgets and event.type() == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = None
            self.fit_image()
            return True
        if self.isVisible() and self._pan_origin is not None:
            if event.type() == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.MiddleButton:
                origin, offset = self._pan_origin
                self._image_pan = offset + QPointF((event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()) - origin)
                self.image_label.update()
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.MiddleButton:
                self._pan_origin = None
                return True
        if self.isVisible() and event.type() == QEvent.Type.Wheel and watched in (self, self.image_label):
            position = self.mapFromGlobal((event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()))
            if self.rect().contains(position):
                self.zoom_at(QPointF(position), event.angleDelta().y() / 120)
                event.accept()
                return True
        if self.isVisible() and event.type() == QEvent.Type.MouseButtonPress:
            if not self.frameGeometry().contains((event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos())):
                self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay, True)
                self.close()
                return True
            if event.button() == Qt.MouseButton.MiddleButton and watched in image_widgets and not self._image.isNull():
                self._pan_origin = ((event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()), QPointF(self._image_pan))
                return True
            if event.button() == Qt.MouseButton.LeftButton and watched in (self, self.image_label, self.spinner, self.error_label):
                self._drag_origin = ((event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()), self.geometry(), self.resize_edges((event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos())))
                return True
        if self.isVisible() and self._drag_origin is not None:
            if event.type() == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.LeftButton:
                origin, geometry, edges = self._drag_origin
                delta = (event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()) - origin
                result = QRect(geometry)
                left, right, top, bottom = edges
                if not any(edges):
                    result.translate(delta)
                else:
                    if left:
                        result.setLeft(min(geometry.left() + delta.x(), geometry.right() - self.minimumWidth() + 1))
                    if right:
                        result.setRight(max(geometry.right() + delta.x(), geometry.left() + self.minimumWidth() - 1))
                    if top:
                        result.setTop(min(geometry.top() + delta.y(), geometry.bottom() - self.minimumHeight() + 1))
                    if bottom:
                        result.setBottom(max(geometry.bottom() + delta.y(), geometry.top() + self.minimumHeight() - 1))
                self.setGeometry(result)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                self._drag_origin = None
                return True
        if self.isVisible() and event.type() == QEvent.Type.MouseMove and watched in (self, self.image_label, self.spinner, self.error_label):
            self.update_resize_cursor((event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()))
        return super().eventFilter(watched, event)

    def event(self, event):
        if event.type() == QEvent.Type.WindowDeactivate and self.isVisible() and self._context_menu is None:
            self.close()
        return super().event(event)


class ImageSearchDocker(DockWidget, SearchLibraryMixin, GalleryExperienceMixin):
    def __init__(self, browser=None, cache_dir=None, downloader=None, user_data_dir=None):
        super().__init__()
        self.setObjectName('quick_image_search')
        self.setWindowTitle('快速搜图')
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
        self.search_input.setPlaceholderText('搜索照片素材…')
        self.init_library(user_data_dir, cache_dir)
        self.translate_button = QPushButton('翻译')
        self.translate_button.setEnabled(False)
        self.translate_button.setToolTip('将当前中文关键词在线译成英文（MyMemory，匿名免费额度 5000 字符/天）；只发送关键词，不自动搜索。')
        self.search_button = QPushButton('搜索')
        for button in (self.translate_button, self.search_button):
            button.setMaximumWidth(button.fontMetrics().horizontalAdvance(button.text()) + 24)
        self.init_gallery_experience(row, prepare_image)
        row.addWidget(self.source)
        row.addWidget(self.search_input, 1)
        row.addWidget(self.translate_button)
        row.addWidget(self.search_button)
        layout.addLayout(row)
        self.grid = ImageGrid()
        self.grid.set_tile_size(self._grid_settings.tile_size)
        self.grid.tile_size_changed.connect(self.remember_grid_size)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self.context_menu)
        layout.addWidget(self.grid, 1)
        buttons = QHBoxLayout()
        self.source.currentIndexChanged.connect(self.update_source_controls)
        self.init_favorite_tabs(buttons)
        self.status = TransientStatus()
        self.status.details_requested.connect(self.show_status_menu)
        buttons.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(buttons)
        self.setWidget(widget)
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
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        self.update_source_controls()
        if self.search_store.last_error:
            self.status.setText('历史/收藏存储提示：' + self.search_store.last_error)
        elif self._grid_settings.last_error:
            self.status.setText('网格尺寸设置无法读取：' + self._grid_settings.last_error)

    def canvasChanged(self, canvas):
        pass

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
        if self.status.text().startswith('翻译失败：'):
            self.status.clear()
        if not self.busy and not self.status.text():
            self.status.setText('正在翻译…')
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
                self.status.setText('翻译失败：' + message)
        def release():
            self.jobs.discard(job)
            _WORKERS.discard(job)
            self._translation_job = None
            if not self._closing:
                if self.status.text() == '正在翻译…':
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
        menu.addAction('图片详细信息').triggered.connect(lambda: self.show_details(entry, dimensions))
        menu.addAction('打开原网址').triggered.connect(lambda: self.open_original(entry))
        similar = menu.addAction('查找相似图片')

        similar.triggered.connect(lambda: self.find_similar(entry, path))
        return menu

    def show_details(self, entry, dimensions=None):
        if self.details_dialog is not None:
            self.details_dialog.close()
            self.details_dialog.deleteLater()
        dialog = QDialog(self)
        dialog.setWindowTitle('图片详细信息')
        dialog.resize(520, 340)
        text = QPlainTextEdit(dialog)
        text.setReadOnly(True)
        width, height = dimensions or (entry.get('width'), entry.get('height'))
        size = f'{width} × {height}' if width and height else '未提供'
        fields = [('图片名', entry.get('title') or '未提供'), ('来源', entry.get('source') or '未提供'), ('尺寸', size), ('原始网站', entry.get('website_url') or entry.get('source_url') or '未提供'), ('来源页面', entry.get('detail_url') or '未提供'), ('图片地址', entry.get('image_url') or '未解析'), ('说明', entry.get('description') or '未提供')]
        text.setPlainText('\n\n'.join(name + '：' + str(value) for name, value in fields))
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
                self.status.setText('无法打开来源网址。')
            return
        self.status.setText('这张图片没有可用的来源网址。')

    def similar_results(self, browser, entry, path=None):
        if path and Path(path).is_file():
            with open(path, 'rb') as image_file:
                data = image_file.read(MAX_BYTES + 1)
        else:
            resolved = browser.resolve(entry)
            if not isinstance(resolved, dict) or not resolved.get('url'):
                raise ValueError('无法取得这张图片的内容。')
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
            self.status.setText('相似搜索已排队，当前图片任务完成后执行…')
            return
        cached = self._prepared_cache.get((entry.get('source'), entry.get('thumbnail')))
        if not path and cached and Path(cached[0]).is_file():
            path = cached[0]
        frame = self.capture_gallery()
        self.has_more = False
        self._more_pending = False
        self.status.setText('正在查找相似图片…')
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
            self.search_input.setPlaceholderText('相似结果 · 输入关键词可重新搜索')
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

    def run_job(self, operation, success, background=False, lock_grid=True, on_failure=None):
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
                self.search_button.setEnabled(True)
                self.update_source_controls()
                self.grid.setEnabled(True)

        def completed(result):
            release()
            success(result)
            self.resume_pending_search()
            self.resume_gallery_back()
            self.resume_library()
            self.resume_similarity()
            self.resume_paging()
        def failed(message):
            release()
            if not background:
                self.status.setText('失败：' + message)
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
            self.status.setText('搜索已排队，当前任务完成后执行最后一次提交…')
            return
        self._pending_query = None
        self.flush_favorite_snapshot()
        self.cancel_preview_load()
        self.generation += 1
        for job in list(self.jobs):
            job.requestInterruption()
        self.status.setText('正在搜索…')
        self.search_input.setPlaceholderText('搜索照片素材…')
        previous_source, previous_more = self._search_source, self.has_more
        history_error = ''
        try:
            self.search_store.record_search(source, query, original_query)
        except (OSError, ValueError) as error:
            history_error = '历史未保存：' + str(error)
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
                self.status.setText('失败：' + message + '；' + history_error)
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
            self.status.setText('没有可用结果；可以打开登录 / 验证窗口检查。')
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
            pool = ThreadPoolExecutor(max_workers=4)
            futures = [pool.submit(fetch, base_index + index, entry) for index, entry in enumerate(fresh)]
            try:
                for future in as_completed(futures):
                    if job.isInterruptionRequested():
                        break
                    try:
                        result = future.result()
                        if result is not None:
                            job.thumbnail.emit(result)
                    except Exception:
                        continue
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
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
        self.status.setText('正在加载更多…')
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
                self.status.setText('暂未加载到更多图片；稍后下滑可重试。' if self.has_more else '已到当前搜索结果末尾。')
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
                item.setData(THUMB_ERROR_ROLE, error or '缩略图无法解码')
                item.setToolTip('缩略图加载失败，点击中央按钮重试。\n' + (error or '无法解码图片'))
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
        self.status.setText('正在获取大图…')
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
                self.status.setText('失败：' + str(error))
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
        self.status.setText('大图准备中；完成后再拖入画布。')

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
        target, reason = None, '请先准备图片并打开文档'
        try:
            target = self.drop_router.current_import_target()
        except (AttributeError, ValueError, RuntimeError) as error:
            reason = str(error)
        ready = bool(target is not None and path and dialog and not dialog.loading and dialog.error_label.isHidden() and not self.busy)
        for text, mode in (('插入为图层', 'layer'), ('插入为参考图', 'reference')):
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

    def show_browser(self):
        if self.busy or self.source.currentData() != 'google':
            return
        self.run_job(lambda job: self.get_browser().show(), lambda result: self.status.setText('完成 Google 验证后回来重新搜索；验证窗口将关闭并恢复后台运行。'))

    def build_status_menu(self):
        menu = QMenu(self.status)
        if self.source.currentData() == 'google' and self.status.state == 'error':
            action = menu.addAction('打开 Google 验证窗口')
            action.setEnabled(not self.busy and not self._closing)
            action.triggered.connect(self.show_browser)
        return menu

    def show_status_menu(self, position):
        menu = self.build_status_menu()
        try:
            if menu.actions():
                menu.exec(position)
        finally:
            menu.deleteLater()

    def shutdown(self):
        if self._closing:
            return
        self.flush_grid_size()
        self.flush_favorite_snapshot()
        self._closing = True
        self._snapshot_timer.stop()
        self._cache_status_timer.stop()
        self.stop_adjacent_prefetch()
        self._pending_preview = None
        if self.preview_dialog is not None:
            self.preview_dialog.close()
        self._pending_similar = None
        self._pending_library = None
        self._back_stack.clear()
        self._pending_query = None
        jobs = list(self.jobs)
        for job in jobs:
            job.requestInterruption()
        for job in jobs:
            job.wait(45000)
        if not any(job.isRunning() for job in jobs) and self.browser is not None and hasattr(self.browser, 'close'):
            self.browser.close()
        self._cache_executor.shutdown(wait=True)
