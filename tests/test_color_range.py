"""Offline regression for the TFM color-range dialog and apply path."""
import os
import sys
import types
import math
from pathlib import Path
from unittest import mock
import hashlib

ROOT = Path(__file__).resolve().parents[1]
KRITA = Path(os.environ.get('KRITA_ROOT') or Path(__import__('shutil').which('krita') or '').resolve().parents[1])
os.add_dll_directory(str(KRITA / 'bin'))
os.environ['QT_PLUGIN_PATH'] = str(KRITA / 'bin')
sys.path.insert(0, str(KRITA / 'lib' / 'site-packages'))
sys.path.insert(0, str(ROOT / 'pykrita'))
from PyQt5.QtWidgets import QApplication
app = QApplication([])

host = types.ModuleType('krita')
class Extension:
    def __init__(self, parent):
        pass
class FakeKrita:
    def __init__(self):
        self.document = None
        self.extensions = []
    def activeDocument(self): return self.document
    def addExtension(self, extension): self.extensions.append(extension)
    def activeWindow(self): return None
    def actions(self): return []
    def action(self, ident): return None
    def readSetting(self, group, key, default): return default
class Krita:
    _instance = FakeKrita()
    @classmethod
    def instance(cls):
        return cls._instance
class FakeSelection:
    def __init__(self, data=b''):
        self.data = data
    def setPixelData(self, data, x, y, width, height):
        self.data = bytes(data)
        self.width, self.height = width, height
    def invert(self):
        self.data = bytes(255 - value for value in self.data)
    def select(self, x, y, width, height, value):
        self.rectangles = getattr(self, 'rectangles', [])
        self.rectangles.append((x, y, width, height, value))
    def pixelData(self, x, y, width, height):
        if hasattr(self, 'rectangles'):
            result = bytearray(width * height)
            for rx, ry, rw, rh, value in self.rectangles:
                for row in range(ry, ry + rh):
                    for col in range(rx, rx + rw):
                        if x <= col < x + width and y <= row < y + height:
                            result[(row - y) * width + col - x] = value
            return bytes(result)
        return self.data
class FakeDocument:
    def __init__(self, image):
        self.image = image
        self.result = None
        self.current_selection = None
    def waitForDone(self): pass
    def refreshProjection(self): pass
    def width(self): return self.image.width()
    def height(self): return self.image.height()
    def projection(self, x, y, width, height): return self.image
    def selection(self): return self.current_selection
    def createSelectionMask(self, name):
        return types.SimpleNamespace(setSelection=lambda selection: None)
    def setSelection(self, selection):
        self.result = selection
        self.current_selection = selection
host.Extension = Extension
host.Krita = Krita
host.Selection = FakeSelection
host.Palette = type('Palette', (), {})
sys.modules['krita'] = host

import tfm
from tfm.color_range import ColorRangeDialog
from tfm.menus.menubelt import MenuBeltExtension
from PyQt5.QtGui import QImage, QColor
from PyQt5.QtCore import Qt

# Odd width exercises grayscale row padding; alpha is part of the selection.
image = QImage(5, 1, QImage.Format_ARGB32)
for x, value in enumerate((0, 64, 128, 192, 255)):
    image.setPixelColor(x, 0, QColor(value, value, value, 255 if x < 4 else 0))
doc = FakeDocument(image)
Krita._instance.document = doc
dialog = ColorRangeDialog(doc)
assert dialog.mask() == bytes((0, 0, 255, 255, 0))
assert [dialog.preview_image().pixelColor(x, 0).red() for x in range(5)] == list(dialog.mask())
from PyQt5.QtCore import QTimer, QEventLoop
def wait_refresh():
    loop = QEventLoop()
    QTimer.singleShot(100, loop.quit)
    loop.exec_()
with mock.patch.object(doc, 'setSelection', side_effect=AssertionError('preview wrote selection')):
    dialog.slider.setValue(200)
    wait_refresh()
    assert dialog.threshold.value() == 200
    assert dialog.mask() == bytes(5)
    assert dialog.preview.pixmap().toImage().pixelColor(10, 10).red() == 0
    dialog.threshold.setValue(64)
    wait_refresh()
    assert dialog.slider.value() == 64
    assert dialog.mask() == bytes((0, 255, 255, 255, 0))
    dialog.invert.setChecked(True)
    wait_refresh()
    assert dialog.mask() == bytes((255, 0, 0, 0, 0))
dialog.invert.setChecked(False)
dialog.threshold.setValue(128)
assert dialog.select_button.text() == 'Select'
assert dialog.deselect_button.text() == 'Deselect'
old = bytes((255, 0, 255, 0, 0))
doc.current_selection = FakeSelection(old)
for mode, expected in [('replace', (0, 0, 255, 255, 0)),
                       ('add', (255, 0, 255, 255, 0)),
                       ('subtract', (255, 0, 0, 0, 0)),
                       ('intersect', (0, 0, 255, 0, 0))]:
    assert dialog.combined_mask(mode) == bytes(expected)
with mock.patch.object(doc, 'setSelection') as commit:
    dialog.reject()
    commit.assert_not_called()
dialog = ColorRangeDialog(doc)
expected = dialog.combined_mask()
with mock.patch.object(doc, 'setSelection', wraps=doc.setSelection) as commit:
    dialog.apply()
    commit.assert_called_once()
    assert doc.result.pixelData(0, 0, 5, 1) == expected
# Buttons apply repeatedly and keep the dialog open.
Krita._instance.document = doc
doc.current_selection = FakeSelection(old)
repeat = ColorRangeDialog(doc)
repeat.show()
repeat.clean_button.click()
assert repeat.isVisible() and doc.selection() is None
repeat.clean_button.click()
assert doc.selection() is None
doc.current_selection = FakeSelection(old)
repeat.select_button.click()
assert repeat.isVisible() and doc.result.data == bytes((255, 0, 255, 255, 0))
repeat.threshold.setValue(192)
repeat.deselect_button.click()
assert repeat.isVisible() and doc.result.data == bytes((255, 0, 255, 0, 0))
repeat.reselect_button.click()
assert repeat.isVisible() and doc.result.data == bytes((0, 0, 0, 255, 0))
repeat.close()
# Endpoints and partial transparency.
image.setPixelColor(4, 0, QColor(255, 255, 255, 100))
dialog = ColorRangeDialog(doc)
dialog.threshold.setValue(0)
assert dialog.mask() == bytes((255, 255, 255, 255, 100))
dialog.threshold.setValue(255)
assert dialog.mask() == bytes((0, 0, 0, 0, 100))
# RGB channels and color-distance mode use the same preview path.
color_image = QImage(6, 1, QImage.Format_ARGB32)
colors = (QColor(255, 0, 0), QColor(255, 255, 0), QColor(0, 255, 0),
          QColor(0, 255, 255), QColor(0, 0, 255), QColor(255, 0, 255))
for x, color in enumerate(colors):
    color_image.setPixelColor(x, 0, color)
color_doc = FakeDocument(color_image)
color_dialog = ColorRangeDialog(color_doc)
expected_modes = ('hue_red', 'hue_yellow', 'hue_green', 'hue_cyan', 'hue_blue', 'hue_magenta')
for index, mode in enumerate(expected_modes):
    color_dialog.mask_mode.setCurrentIndex(color_dialog.mask_mode.findData(mode))
    mask = color_dialog.mask()
    assert len(mask) == 6 and mask[index] >= 250, (mode, list(mask))
# Hue selection wraps through red and excludes neutral gray.
red_wrap = QImage(3, 1, QImage.Format_ARGB32)
for x, color in enumerate((QColor(255, 0, 12), QColor(128, 128, 128), QColor(255, 10, 0))):
    red_wrap.setPixelColor(x, 0, color)
red_dialog = ColorRangeDialog(FakeDocument(red_wrap))
red_dialog.mask_mode.setCurrentIndex(red_dialog.mask_mode.findData('hue_red'))
red_mask = bytes(red_dialog.mask())
assert red_mask[0] > 0 and red_mask[2] > 0 and red_mask[1] == 0, list(red_mask)
# Brightness modes have distinct peak regions and preserve alpha.
tones = QImage(5, 1, QImage.Format_ARGB32)
for x, value in enumerate((0, 64, 128, 192, 255)):
    tones.setPixelColor(x, 0, QColor(value, value, value, 128 if x == 4 else 255))
tone_dialog = ColorRangeDialog(FakeDocument(tones))
for mode in ('highlights', 'midtones', 'shadows'):
    tone_dialog.mask_mode.setCurrentIndex(tone_dialog.mask_mode.findData(mode))
    assert len(tone_dialog.mask()) == 5
    assert tone_dialog.mask()[-1] <= 128
skin = QImage(3, 1, QImage.Format_ARGB32)
for x, color in enumerate((QColor(220, 150, 110), QColor(60, 120, 230), QColor(128, 128, 128))):
    skin.setPixelColor(x, 0, color)
skin_dialog = ColorRangeDialog(FakeDocument(skin))
skin_dialog.mask_mode.setCurrentIndex(skin_dialog.mask_mode.findData('skin'))
skin_mask = bytes(skin_dialog.mask())
assert skin_mask[0] > skin_mask[1] and skin_mask[0] > skin_mask[2], list(skin_mask)
# Preview mode contract: only selection outline or quick mask are offered.
assert [dialog.preview_mode.itemData(i) for i in range(dialog.preview_mode.count())] == ['selection', 'black_white', 'quick_mask']
# Threshold off keeps soft color matching active, independent of the slider value.
color_image = QImage(5, 1, QImage.Format_ARGB32)
for x, value in enumerate((80, 110, 140, 170, 200)):
    color_image.setPixelColor(x, 0, QColor(value, 30, 30))
soft_dialog = ColorRangeDialog(FakeDocument(color_image))
soft_dialog.mask_mode.setCurrentIndex(soft_dialog.mask_mode.findData('hue_red'))
soft_dialog.threshold.setValue(0)
soft_dialog.threshold_enabled.setChecked(False)
soft_a = bytes(soft_dialog.mask())
soft_dialog.threshold.setValue(255)
soft_b = bytes(soft_dialog.mask())
assert soft_a == soft_b and len(set(soft_a)) > 1, list(soft_a)
soft_dialog.threshold_enabled.setChecked(True)
hard_mask = bytes(soft_dialog.mask())
assert hard_mask != soft_b, (list(hard_mask), list(soft_b))
soft_dialog.mask_mode.setCurrentIndex(soft_dialog.mask_mode.findData('luminance'))
soft_dialog.invert.setChecked(False)
soft_dialog.threshold_enabled.setChecked(False)
normal = bytes(soft_dialog.mask())
soft_dialog.invert.setChecked(True)
inverted = bytes(soft_dialog.mask())
assert all(a + b == 255 for a, b in zip(normal, inverted)), (list(normal), list(inverted))
# RGB channels and color-distance mode continue to use the same preview path.
color_image = QImage(3, 1, QImage.Format_ARGB32)
for x, color in enumerate((QColor(255, 0, 0), QColor(0, 255, 0), QColor(0, 0, 255))):
    color_image.setPixelColor(x, 0, color)
color_doc = FakeDocument(color_image)
color_dialog = ColorRangeDialog(color_doc)
for channel, expected in [('red', (255, 0, 0)), ('green', (0, 255, 0)), ('blue', (0, 0, 255))]:
    color_dialog.mask_mode.setCurrentIndex(color_dialog.mask_mode.findData(channel))
    assert color_dialog.mask() == bytes(expected), channel
color_dialog.target_color = QColor(255, 0, 0)
color_dialog.threshold.setValue(10)
color_dialog.mask_mode.setCurrentIndex(color_dialog.mask_mode.findData('color'))
assert color_dialog.mask() == bytes((255, 0, 0))
color_dialog.invert.setChecked(True)
assert color_dialog.mask() == bytes((0, 255, 255))
# Independent threshold / tolerance / softness controls affect each mask family.
controls = ColorRangeDialog(FakeDocument(tones))
assert controls.windowTitle() == 'Advance Selection'
assert controls.tolerance_slider.value() == controls.tolerance.value() == 32
assert controls.softness_slider.value() == controls.softness.value() == 12
controls.tolerance_enabled.setChecked(True)
controls.tolerance_slider.setValue(73)
assert controls.tolerance.value() == 73
controls.tolerance.setValue(91)
assert controls.tolerance_slider.value() == 91
controls.softness_enabled.setChecked(True)
controls.softness_slider.setValue(44)
assert controls.softness.value() == 44
controls.softness.setValue(57)
assert controls.softness_slider.value() == 57
controls.tolerance_enabled.setChecked(False)
controls.softness_enabled.setChecked(False)
assert not controls.tolerance_slider.isEnabled() and not controls.tolerance.isEnabled()
assert not controls.softness_slider.isEnabled() and not controls.softness.isEnabled()
controls.mask_mode.setCurrentIndex(controls.mask_mode.findData('luminance'))
controls.threshold.setValue(128)
controls.threshold_enabled.setChecked(True)
controls.tolerance_enabled.setChecked(False)
controls.softness_enabled.setChecked(False)
base = bytes(controls.mask())
controls.tolerance_enabled.setChecked(True)
controls.tolerance.setValue(120)
wide = bytes(controls.mask())
assert wide != base, ('luminance tolerance ignored', list(base), list(wide))
controls.tolerance_enabled.setChecked(False)
controls.softness_enabled.setChecked(True)
controls.softness.setValue(48)
feathered = bytes(controls.mask())
assert feathered != base, ('luminance softness ignored', list(base), list(feathered))
controls.mask_mode.setCurrentIndex(controls.mask_mode.findData('red'))
controls.threshold.setValue(128)
controls.tolerance_enabled.setChecked(False)
controls.softness_enabled.setChecked(False)
channel_base = bytes(controls.mask())
controls.tolerance_enabled.setChecked(True)
controls.tolerance.setValue(64)
channel_wide = bytes(controls.mask())
assert channel_wide != channel_base, ('RGB tolerance ignored', list(channel_base), list(channel_wide))
controls.tolerance_enabled.setChecked(False)
controls.softness_enabled.setChecked(True)
controls.softness.setValue(40)
channel_soft = bytes(controls.mask())
assert channel_soft != channel_base, ('RGB softness ignored', list(channel_base), list(channel_soft))
controls.mask_mode.setCurrentIndex(controls.mask_mode.findData('skin'))
skin_image = QImage(5, 1, QImage.Format_ARGB32)
for x, color in enumerate((QColor(220, 150, 110), QColor(230, 170, 130), QColor(200, 120, 80),
                            QColor(180, 100, 60), QColor(240, 190, 150))):
    skin_image.setPixelColor(x, 0, color)
controls = ColorRangeDialog(FakeDocument(skin_image))
controls.mask_mode.setCurrentIndex(controls.mask_mode.findData('skin'))
skin_base = bytes(controls.mask())
controls.tolerance_enabled.setChecked(True)
controls.tolerance.setValue(120)
skin_wide = bytes(controls.mask())
assert skin_wide != skin_base, ('skin tolerance ignored', list(skin_base), list(skin_wide))
controls.tolerance_enabled.setChecked(False)
controls.softness_enabled.setChecked(True)
controls.softness.setValue(48)
skin_soft = bytes(controls.mask())
assert skin_soft != skin_base, ('skin softness ignored', list(skin_base), list(skin_soft))
# A zero softness override gives hard edges in the native tonal curve.
from tfm.color_range_native import perceptual as native_perceptual
hard = native_perceptual(tones, bytes((0, 64, 128, 192, 255)), 'highlights', 128, False,
                         tolerance=60, softness=0)
assert set(hard[:4]) <= {0, 255} and hard[-1] == 128, list(hard)
# RGB channel controls combine independently with threshold and softness.
controls.threshold_enabled.setChecked(False)
controls.tolerance_enabled.setChecked(False)
controls.softness_enabled.setChecked(False)
raw_channel = bytes(controls.mask())
controls.tolerance_enabled.setChecked(True)
controls.softness_enabled.setChecked(True)
combined_channel = bytes(controls.mask())
assert combined_channel != raw_channel, ('combined RGB controls ignored', list(raw_channel), list(combined_channel))
# Noisy mask
noise = QImage(65, 65, QImage.Format_ARGB32)
noise.fill(QColor(128, 128, 128))
noise_doc = FakeDocument(noise)
Krita._instance.document = noise_doc
noisy = ColorRangeDialog(noise_doc)
noisy_mask = bytes(255 if (x + y) % 2 else 0 for y in range(65) for x in range(65))
with mock.patch.object(noisy, 'combined_mask', return_value=noisy_mask), \
     mock.patch('tfm.color_range.QMessageBox.warning') as warning, \
     mock.patch.object(noise_doc, 'setSelection') as commit:
    noisy.apply()
    commit.assert_called_once()
    assert bytes(commit.call_args.args[0].data) == noisy_mask
    warning.assert_not_called()
from PyQt5 import sip
for widget in app.topLevelWidgets():
    if not sip.isdeleted(widget):
        sip.delete(widget)
app.processEvents()
print('PASS: threshold preview, slider/input sync, inversion, alpha, four selection modes, cancel and single commit; normal cleanup', flush=True)
