"""Krita TFM plugin registration."""

from krita import Krita
from .menus.menubelt import MenuBeltExtension

_app = Krita.instance()
_app.addExtension(MenuBeltExtension(_app))
