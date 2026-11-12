"""Interactive sampled-color selection for Krita."""
from krita import Krita
from .menus.qtcompat import (
    QObject, QRunnable, pyqtSignal,
    QApplication, QMessageBox, QImage,
)
from .i18n import tr

TOOL_TITLE = lambda: tr('Advanced Selection', '高级选区')

_MODE_GROUPS = (
    ((('Sampled Color', '取样颜色'), 'color'),),
    (
        (('Reds', '红色'), 'hue_red'),
        (('Yellows', '黄色'), 'hue_yellow'),
        (('Greens', '绿色'), 'hue_green'),
        (('Cyans', '青色'), 'hue_cyan'),
        (('Blues', '蓝色'), 'hue_blue'),
        (('Magentas', '品红'), 'hue_magenta'),
        (('Skin Tones', '肤色'), 'skin'),
    ),
    (
        (('Highlights', '高光'), 'highlights'),
        (('Midtones', '中间调'), 'midtones'),
        (('Shadows', '阴影'), 'shadows'),
        (('Brightness', '亮度'), 'luminance'),
    ),
    (
        (('Red Channel', '红色通道'), 'red'),
        (('Green Channel', '绿色通道'), 'green'),
        (('Blue Channel', '蓝色通道'), 'blue'),
    ),
)


def _enum(group, name):
    direct = getattr(group, name, None)
    if direct is not None:
        return direct
    for scope in ('Format', 'Shape', 'StandardButton', 'Orientation',
                  'AspectRatioMode', 'TransformationMode', 'MouseButton',
                  'KeyboardModifier', 'CursorShape'):
        scoped = getattr(group, scope, None)
        if scoped is not None and hasattr(scoped, name):
            return getattr(scoped, name)
    raise AttributeError(name)


def _image_format(name):
    return _enum(QImage.Format, name)


def _luminance_bytes(source):
    """Pack grayscale8 pixels without row padding; safe on a worker thread."""
    gray = source.convertToFormat(QImage.Format.Format_Grayscale8)
    ptr = gray.constBits()
    ptr.setsize(gray.sizeInBytes())
    raw = bytes(ptr)
    width, height = source.width(), source.height()
    stride = gray.bytesPerLine()
    if stride == width:
        return bytearray(raw[: width * height])
    luminance = bytearray(width * height)
    for y in range(height):
        start = y * stride
        luminance[y * width:(y + 1) * width] = raw[start:start + width]
    return luminance


class _CaptureSignals(QObject):
    finished = pyqtSignal(object)


class _LuminanceJob(QRunnable):
    def __init__(self, generation, source, signals):
        super().__init__()
        self.generation = generation
        self.source = source
        self.signals = signals

    def run(self):
        try:
            result = (self.generation, self.source, _luminance_bytes(self.source), None)
        except Exception as error:  # noqa: BLE001 — surface any decode failure to the dialog
            result = (self.generation, None, None, error)
        self.signals.finished.emit(result)


_open_dialogs = []


def __getattr__(name):
    if name == "ColorRangeDialog":
        from .color_range_dialog import ColorRangeDialog
        return ColorRangeDialog
    raise AttributeError(name)


def open_color_range():
    from .color_range_dialog import ColorRangeDialog
    document = Krita.instance().activeDocument()
    if document is None:
        QMessageBox.information(
            QApplication.activeWindow(),
            TOOL_TITLE(),
            tr('Open a document first.', '请先打开文档。'),
        )
        return
    try:
        window = QApplication.activeWindow()
        dialog = ColorRangeDialog(document, window)
        dialog.setModal(False)
        # Keep the live panel reachable while Krita continues drawing the canvas.
        dialog.finished.connect(lambda *_: _open_dialogs.remove(dialog) if dialog in _open_dialogs else None)
        _open_dialogs.append(dialog)
        dialog.show()
    except (RuntimeError, ValueError) as error:
        QMessageBox.warning(QApplication.activeWindow(), TOOL_TITLE(), str(error))
