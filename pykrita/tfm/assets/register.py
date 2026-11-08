"""Register the Asset Library docker without importing its UI until first open."""

from krita import DockWidget, DockWidgetFactory, DockWidgetFactoryBase


class AssetLibraryDocker(DockWidget):
    """Proxy that loads ``assets.docker`` on first construction."""

    def __init__(self, *args, **kwargs):
        from .docker import AssetLibraryDocker as _Real

        self.__class__ = _Real
        _Real.__init__(self, *args, **kwargs)


def register_assets(app):
    app.addDockWidgetFactory(
        DockWidgetFactory("tfm_assets", DockWidgetFactoryBase.DockRight, AssetLibraryDocker)
    )
