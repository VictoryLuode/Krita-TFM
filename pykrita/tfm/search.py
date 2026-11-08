"""Quick Image Search, registered as a TFM tool rather than its own plugin."""

from krita import DockWidget, DockWidgetFactory, DockWidgetFactoryBase

from .menus.qtcompat import QTimer

_BoundDocker = None


def _bound_docker():
    global _BoundDocker
    if _BoundDocker is not None:
        return _BoundDocker
    from quick_image_search.docker import ImageSearchDocker as _Real

    class BoundDocker(_Real):
        def __init__(self, browser=None, cache_dir=None, downloader=None, user_data_dir=None):
            super().__init__(browser, cache_dir, downloader, user_data_dir)
            QTimer.singleShot(0, self._hide_when_disabled)

        def canvasChanged(self, canvas):
            super().canvasChanged(canvas)
            QTimer.singleShot(0, self._hide_when_disabled)

        def showEvent(self, event):
            super().showEvent(event)
            QTimer.singleShot(0, self._hide_when_disabled)

        def _hide_when_disabled(self):
            from .manager import search_enabled

            if search_enabled():
                return
            toggle = self.toggleViewAction()
            if toggle is not None:
                toggle.setVisible(False)
                toggle.setEnabled(False)
            if self.isVisible():
                self.hide()

    _BoundDocker = BoundDocker
    return _BoundDocker


class QuickImageSearchDocker(DockWidget):
    """Proxy that loads quick_image_search on first construction."""

    def __init__(self, *args, **kwargs):
        real = _bound_docker()
        self.__class__ = real
        real.__init__(self, *args, **kwargs)


def register_image_search(app):
    try:
        import importlib.util

        if importlib.util.find_spec("quick_image_search") is None:
            return False
    except Exception:
        return False

    app.addDockWidgetFactory(
        DockWidgetFactory(
            "tfm_quick_image_search",
            DockWidgetFactoryBase.DockRight,
            QuickImageSearchDocker,
        )
    )
    return True
