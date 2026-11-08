"""Small UI helpers so TFM / QIS chrome follows the host Krita / Qt palette."""

from __future__ import annotations


def style_of(widget):
    style = widget.style() if widget is not None else None
    if style is None:
        try:
            from qtcompat import QApplication
            app = QApplication.instance()
            if app is not None:
                style = app.style()
        except Exception:
            style = None
    return style


def standard_icon(widget, name):
    """Return a QStyle standard icon by enum name, or an empty QIcon."""
    from qtcompat import QIcon, QStyle

    style = style_of(widget)
    if style is None:
        return QIcon()
    sp = getattr(QStyle, "StandardPixmap", None)
    key = getattr(sp, name, None) if sp is not None else getattr(QStyle, name, None)
    if key is None:
        return QIcon()
    try:
        return style.standardIcon(key)
    except Exception:
        return QIcon()


def apply_muted_label(label):
    """Tone down helper / empty-state copy using the host palette."""
    try:
        from qtcompat import QPalette
        palette = label.palette()
        color = palette.color(QPalette.ColorRole.PlaceholderText)
        if not color.isValid() or color.alpha() == 0:
            color = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText)
        palette.setColor(QPalette.ColorRole.WindowText, color)
        label.setPalette(palette)
    except Exception:
        pass
    label.setWordWrap(True)


def apply_warning_label(label):
    """Colour a warning line from the host palette, never a hardcoded hex."""
    try:
        from qtcompat import QPalette, QColor
        palette = label.palette()
        color = palette.color(QPalette.ColorRole.Link)
        if not color.isValid() or color.alpha() == 0:
            color = palette.color(QPalette.ColorRole.Highlight)
        if color.lightness() > 180:
            color = QColor(color.darker(140))
        palette.setColor(QPalette.ColorRole.WindowText, color)
        label.setPalette(palette)
        label.setStyleSheet("")
    except Exception:
        pass
    label.setWordWrap(True)


def make_empty_state(parent, text):
    """Centered muted label for empty lists / grids."""
    from qtcompat import QLabel, Qt

    label = QLabel(text, parent)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    apply_muted_label(label)
    label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    return label


def sync_empty_state(label, visible, text=None):
    if text is not None:
        label.setText(text)
    label.setVisible(bool(visible))


def icon_tool_button(parent, text, tip, icon_name, slot=None):
    """Auto-raising tool button with a standard icon and tooltip."""
    from qtcompat import QToolButton, Qt

    button = QToolButton(parent)
    button.setAutoRaise(True)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    icon = standard_icon(parent, icon_name)
    if not icon.isNull():
        button.setIcon(icon)
    button.setText(text)
    button.setToolTip(tip or text)
    if slot is not None:
        button.clicked.connect(slot)
    return button


def position_empty_state(label, host):
    """Keep an empty-state label centered over *host*."""
    if label is None or host is None:
        return
    label.setGeometry(host.rect())
    label.raise_()
