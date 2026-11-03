"""Quick Image Search, registered as a TFM tool rather than its own plugin."""

from krita import DockWidgetFactory, DockWidgetFactoryBase

from .menus.qtcompat import QTimer


def register_image_search(app):
    try:
        from quick_image_search.docker import ImageSearchDocker
    except Exception:
        return False

    class QuickImageSearchDocker(ImageSearchDocker):
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

    app.addDockWidgetFactory(
        DockWidgetFactory(
            "tfm_quick_image_search",
            DockWidgetFactoryBase.DockRight,
            QuickImageSearchDocker,
        )
    )
    return True
