"""Krita TFM plugin registration."""

from krita import Krita
from .menus.menubelt import MenuBeltExtension

_app = Krita.instance()
_app.addExtension(MenuBeltExtension(_app))

if hasattr(_app, "addDockWidgetFactory"):
    from .assets.docker import register_assets
    from .search import register_image_search
    register_assets(_app)
    register_image_search(_app)
