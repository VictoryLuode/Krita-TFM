"""Shared dark palette for TFM popup / pie menus (palette only — keep icons)."""

from .qtcompat import QColor, QPalette


def apply_dark_theme(menu):
    """Apply the Blender-like dark palette without stylesheets.

    Any setStyleSheet on a QMenu switches it to QStyleSheetStyle, which stops
    drawing item icons — so theming must use the palette alone
    (separator = QPalette.ColorRole.Mid) to keep icons.
    """
    pal = menu.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(33, 33, 33))
    pal.setColor(QPalette.ColorRole.Base, QColor(33, 33, 33))
    pal.setColor(QPalette.ColorRole.Text, QColor(232, 232, 232))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(232, 232, 232))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(232, 232, 232))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(61, 61, 61))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    pal.setColor(QPalette.ColorRole.Mid, QColor(58, 58, 58))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(154, 154, 154))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(154, 154, 154))
    menu.setPalette(pal)
