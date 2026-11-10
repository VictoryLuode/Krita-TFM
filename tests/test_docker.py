import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from qt_test_binding import QByteArray, QBuffer, QIODevice, Qt
from qt_test_binding import QColor, QImage
from qt_test_binding import QApplication, QDockWidget

APP = QApplication.instance() or QApplication([])
FAKE = types.ModuleType('krita')
FAKE.DockWidget = QDockWidget
FAKE.Krita = type('Krita', (), {'instance': staticmethod(lambda: types.SimpleNamespace(activeDocument=lambda: None))})
PATH = Path(__file__).resolve().parents[1] / 'pykrita' / 'quick_image_search' / 'docker.py'
MODULE = None
if PATH.exists():
    package = types.ModuleType('_quick_image_search_test')
    package.__path__ = [str(PATH.parent)]
    sys.modules[package.__name__] = package
    spec = importlib.util.spec_from_file_location(package.__name__ + '.docker', PATH)
    MODULE = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = MODULE
    previous_krita = sys.modules.get('krita')
    sys.modules['krita'] = FAKE
    try:
        spec.loader.exec_module(MODULE)
    finally:
        if previous_krita is None:
            sys.modules.pop('krita', None)
        else:
            sys.modules['krita'] = previous_krita

class ImageSearchTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(MODULE, 'The runnable image search docker is missing')

    def png(self):
        image = QImage(48, 32, QImage.Format.Format_ARGB32)
        image.fill(QColor('#557799'))
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        self.assertTrue(image.save(buffer, 'PNG'))
        return bytes(buffer.data())

    def test_prepare_image_produces_native_file_drag(self):
        with tempfile.TemporaryDirectory() as directory:
            path, width, height = MODULE.prepare_image(self.png(), Path(directory), 'sample')
            self.assertTrue(Path(path).is_file())
            self.assertEqual((width, height), (48, 32))
            mime = MODULE.file_drag_mime(path)
            self.assertTrue(mime.hasUrls())
            self.assertFalse(mime.hasImage())
            self.assertEqual(Path(mime.urls()[0].toLocalFile()).resolve(), Path(path).resolve())
            self.assertEqual(QImage(path).size(), QImage(48, 32, QImage.Format.Format_ARGB32).size())

    def test_search_grid_prepares_selected_large_image(self):
        from qt_test_binding import QTest
        import time
        class Browser:
            def search(self, source, query, limit=24):
                self.last_query = (source, query)
                return [{'id': '1', 'title': 'Concrete', 'thumbnail': 'https://example.org/thumb.png', 'detail_url': 'https://example.org/detail', 'source': 'google'}]
            def resolve(self, entry):
                return {'url': 'https://example.org/large.png', 'referer': entry['detail_url'], 'title': entry['title']}
            def show(self):
                return None
        browser = Browser()
        with tempfile.TemporaryDirectory() as directory:
            panel = MODULE.ImageSearchDocker(browser=browser, cache_dir=directory, downloader=lambda *args: self.png())
            panel.resize(360, 600)
            panel.show()
            panel.source.setCurrentIndex(panel.source.findData('google'))
            panel.search_input.setText('concrete texture')
            panel.search_button.click()
            deadline = time.monotonic() + 5
            while panel.grid.count() != 1 and time.monotonic() < deadline:
                QTest.qWait(20)
            self.assertEqual(panel.grid.count(), 1)
            self.assertEqual(browser.last_query, ('google', 'concrete texture'))
            panel.grid.setCurrentRow(0)
            deadline = time.monotonic() + 5
            while not panel.grid.item(0).data(MODULE.PATH_ROLE) and time.monotonic() < deadline:
                QTest.qWait(20)
            self.assertTrue(Path(panel.grid.item(0).data(MODULE.PATH_ROLE)).is_file())
            self.assertEqual(panel.grid.item(0).data(MODULE.SIZE_ROLE), (48, 32))
            self.assertTrue(panel.status.isHidden())
            panel.grid.itemDoubleClicked.emit(panel.grid.item(0))
            QTest.qWait(30)
            self.assertTrue(panel.preview_dialog.isVisible())
            panel.preview_dialog.close()
            panel.shutdown()
            panel.close()

    def test_invalid_image_is_not_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                MODULE.prepare_image(b'<html>login</html>', Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])

if __name__ == '__main__':
    unittest.main(verbosity=2)
