"""Search result grid, preview window, and download helpers."""

from .qtcompat import (QMimeData, QUrl, QThread, pyqtSignal, Qt, QSize, QStandardPaths, QBuffer, QIODevice, QTimer, QPoint, QEvent, QRect, QRectF, QPointF, QImage, QImageReader, QPixmap, QIcon, QDrag, QDesktopServices, QPainter, QPen, QColor, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QComboBox, QListWidget, QListWidgetItem, QAbstractItemView, QListView, QLabel, QDialog, QScrollArea, QStyledItemDelegate, QStyleOptionViewItem, QStyle, QMenu, QPlainTextEdit, QSizePolicy, QToolButton, QDockWidget as _QDockWidget)
QDockWidget = _QDockWidget
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

from krita import Krita

from .drop_router import DRAG_FORMAT
from quick_image_search.task_runtime import Token, task_scope, Cancelled
from quick_image_search.network import request_bytes
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
    data = request_bytes(request, timeout=12, limit=65536, proxy=proxy)
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
    data = request_bytes(urllib.request.Request(url, headers=headers), timeout=15,
                         limit=MAX_BYTES, proxy=proxy, validate=validate_remote_url)
    return data


class Job(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    thumbnail = pyqtSignal(object)

    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.token = Token()

    def requestInterruption(self):
        self.token.cancel()
        super().requestInterruption()

    def run(self):
        try:
            with task_scope(self.token):
                result = self.operation(self)
                self.token.check()
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

__all__ = [name for name in list(globals()) if not name.startswith("__")]
