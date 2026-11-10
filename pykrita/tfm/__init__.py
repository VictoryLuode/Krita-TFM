"""Krita TFM plugin registration."""

from krita import Krita
from .menus.extension import TfmExtension

_app = Krita.instance()
_app.addExtension(TfmExtension(_app))

if hasattr(_app, "addDockWidgetFactory"):
    # Heavy docker UIs import on first panel open, not at plugin load.
    from .assets.register import register_assets
    from .search import register_image_search

    register_assets(_app)
    register_image_search(_app)
