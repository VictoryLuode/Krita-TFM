from pathlib import Path
from .qtcompat import (QObject, QEvent, QPointF, QTimer, Qt, QUrl, QKeyEvent, QDragEnterEvent, QDropEvent, QApplication, QWidget, QMenu, QMdiArea, QMimeData)
"""Route only this plugin's drags through Krita's native import operations."""
import time
import os

DRAG_FORMAT = 'application/x-krita-quick-image-search'
_ROUTER = None


def drop_mode(view, canvas_widget, global_position):
    """Classify in image space, including pan, zoom, rotation and mirroring."""
    local = canvas_widget.mapFromGlobal(global_position)
    if not canvas_widget.rect().contains(local):
        return None
    inverse, valid = view.flakeToCanvasTransform().inverted()
    if not valid:
        return None
    image_point = view.flakeToImageTransform().map(inverse.map(QPointF(local)))
    document = view.document()
    if document is None:
        return None
    if view.canvas().wrapAroundMode():
        return 'layer'
    inside = 0 <= image_point.x() < document.width() and 0 <= image_point.y() < document.height()
    return 'layer' if inside else 'reference'


class DropRouter(QObject):
    def __init__(self, application):
        super().__init__()
        self.application = application
        self.pending_mode = None
        self.deadline = 0.0
        self.last_error = ''
        self.last_choice = ''
        self._explicit_import = None

    @staticmethod
    def _visible_native_views(qwindow):
        return [w for w in qwindow.findChildren(QWidget)
                if w.metaObject().className() == 'KisView' and w.isVisible()]

    def current_import_target(self):
        app = self.application()
        if app is None or not hasattr(app, 'activeWindow'):
            raise ValueError('No active Krita window/document target')
        window = app.activeWindow()
        if window is None:
            raise ValueError('No active Krita window/document target')
        view = window.activeView()
        if view is None or view.document() is None:
            raise ValueError('No active Krita document target')
        qwindow = window.qwindow()
        candidates = self._visible_native_views(qwindow)
        mdi_areas = qwindow.findChildren(QMdiArea)
        active = []
        for area in mdi_areas:
            if not hasattr(area, 'activeSubWindow'):
                continue
            sub = area.activeSubWindow()
            if sub is not None:
                active.extend(w for w in candidates if w is sub or sub.isAncestorOf(w))
        if active:
            candidates = active
        if len(candidates) != 1:
            raise ValueError('Krita native view target is ambiguous or unavailable')
        native = candidates[0]
        canvas = next((w for w in native.findChildren(QWidget)
                       if w.inherits('KisOpenGLCanvas2') or w.inherits('KisQPainterCanvas')), None)
        if canvas is None:
            raise ValueError('Krita canvas target is unavailable')
        return window, view, view.document(), native, canvas

    def import_file(self, path, mode, target=None):
        self._explicit_import = None
        self.pending_mode = None
        self.last_choice = ''
        self.last_error = ''
        if mode not in ('layer', 'reference'):
            raise ValueError('Unknown image drop mode')
        path = os.path.abspath(os.fspath(path))
        if not os.path.isfile(path) or os.path.splitext(path)[1].lower() not in {
                '.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tif', '.tiff', '.webp', '.ora', '.psd'}:
            raise ValueError('Import path must be an existing local image file')
        self.last_choice = ''
        self.last_error = ''
        try:
            resolved = self.current_import_target() if target is None else target
            window, view, document, native, canvas = resolved
            if window.activeView() != view or view.document() != document or not native.isVisible():
                raise ValueError('Krita import target changed; refusing to import')
            inverse, valid = view.flakeToImageTransform().inverted()
            if not valid:
                raise ValueError('Krita view transform is unavailable')
            center = inverse.map(QPointF(document.width()/2, document.height()/2))
            point = canvas.mapTo(native, view.flakeToCanvasTransform().map(center).toPoint())
            mime = QMimeData()
            mime.setData(DRAG_FORMAT, b'1')
            mime.setUrls([QUrl.fromLocalFile(path)])
            self._explicit_import = (native, mode)
            enter = QDragEnterEvent(point, Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            drop = QDropEvent(QPointF(point), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(native, enter)
            QApplication.sendEvent(native, drop)
            if self.last_error:
                raise RuntimeError(self.last_error)
            return self.last_choice == mode
        finally:
            self._explicit_import = None
            self.pending_mode = None

    def arm(self, mode):
        if mode not in ('layer', 'reference'):
            raise ValueError('Unknown image drop mode')
        self.pending_mode = mode
        self.deadline = time.monotonic() + 5

    def _mode_for_event(self, watched, event):
        if self._explicit_import is not None and watched is self._explicit_import[0]:
            return self._explicit_import[1]
        app = self.application()
        window = next((w for w in app.windows() if w.qwindow() == watched.window()), None)
        if window is None or window.activeView() is None:
            return None
        canvas = next((w for w in watched.findChildren(QWidget) if w.inherits('KisOpenGLCanvas2') or w.inherits('KisQPainterCanvas')), None)
        if canvas is None:
            return None
        return drop_mode(window.activeView(), canvas, watched.mapToGlobal(event.pos()))

    def _choose(self, menu, mode):
        try:
            # Native KisCanvasDrop defines these stable, distinct operations.
            index = 0 if mode == 'layer' else 3
            actions = menu.actions()
            if len(actions) <= index or not actions[index].isEnabled():
                menu.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, False)
                self.last_error = 'The required native import operation is unavailable'
                if self._explicit_import is not None:
                    menu.close()
                return
            action = actions[index]
            self.last_choice = mode
            menu.setActiveAction(action)
            QApplication.sendEvent(menu, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
            QApplication.sendEvent(menu, QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
        except RuntimeError:
            self.last_error = 'The native import menu closed before selection'

    def eventFilter(self, watched, event):
        try:
            if event.type() == QEvent.Type.Drop:
                self.pending_mode = None
                if watched.metaObject().className() != 'KisView' or not event.mimeData().hasFormat(DRAG_FORMAT):
                    return False
                if self._explicit_import is not None and watched is self._explicit_import[0]:
                    self.last_choice = ''
                mode = self._mode_for_event(watched, event)
                if mode is not None:
                    self.arm(mode)
            elif event.type() == QEvent.Type.Show and isinstance(watched, QMenu):
                if watched.objectName() != 'drop_popup' or self.pending_mode is None:
                    return False
                if time.monotonic() > self.deadline:
                    self.pending_mode = None
                    return False
                mode = self.pending_mode
                self.pending_mode = None
                watched.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
                QTimer.singleShot(0, lambda: self._choose(watched, mode))
        except Exception as error:
            self.last_error = str(error)
            self.pending_mode = None
        return False


def install_drop_router():
    global _ROUTER
    if _ROUTER is None:
        from krita import Krita
        _ROUTER = DropRouter(Krita.instance)
        QApplication.instance().installEventFilter(_ROUTER)
    return _ROUTER
