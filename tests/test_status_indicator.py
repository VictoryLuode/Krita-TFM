import importlib.util
import os
from pathlib import Path
import sys
import unittest
import test_docker as fixture

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from qt_test_binding import Qt
from qt_test_binding import QImage, QPainter
from qt_test_binding import QApplication

APP = QApplication.instance() or QApplication([])
PATH = Path(__file__).resolve().parents[1] / 'pykrita' / 'quick_image_search' / 'status_indicator.py'
spec = importlib.util.spec_from_file_location('_quick_image_search_test.status_indicator', PATH)
MODULE = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = MODULE
spec.loader.exec_module(MODULE)
StatusIndicator = MODULE.StatusIndicator

class StatusIndicatorTests(unittest.TestCase):
    def render(self, widget):
        image = QImage(widget.size(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        widget.render(image)
        return bytes(image.bits().asstring(image.sizeInBytes()))

    def test_message_is_accessible_but_never_changes_icon_geometry(self):
        indicator = StatusIndicator()
        indicator.setText('正在处理')
        self.assertEqual(indicator.text(), '正在处理')
        self.assertEqual(indicator.toolTip(), '正在处理')
        self.assertEqual(indicator.accessibleName(), '正在处理')
        self.assertEqual(indicator.state, 'busy')
        self.assertFalse(indicator.wordWrap())
        original = indicator.sizeHint()
        indicator.setText('失败：' + '非常长的详细错误信息' * 80)
        self.assertEqual(indicator.text(), '失败：' + '非常长的详细错误信息' * 80)
        self.assertEqual(indicator.state, 'error')
        self.assertEqual(indicator.sizeHint(), original)
        self.assertEqual((original.width(), original.height()), (22, 22))

    def test_states_render_different_icon_pixels_without_text(self):
        indicator = StatusIndicator()
        images = []
        for message in ('正在处理', '失败', '已完成'):
            indicator.setText(message)
            images.append(self.render(indicator))
        self.assertEqual(len(set(images)), 3)

    def test_timer_only_runs_for_visible_busy_state_and_stops_on_clear_or_hide(self):
        indicator = StatusIndicator()
        indicator.setText('正在处理')
        indicator.show()
        APP.processEvents()
        self.assertTrue(indicator._timer.isActive())
        indicator.setText('失败')
        self.assertFalse(indicator._timer.isActive())
        indicator.setText('处理中')
        indicator.hide()
        self.assertFalse(indicator._timer.isActive())
        indicator.show()
        APP.processEvents()
        self.assertTrue(indicator._timer.isActive())
        indicator.clear()
        self.assertFalse(indicator._timer.isActive())

    def test_click_emits_global_position_only(self):
        from qt_test_binding import QTest
        from qt_test_binding import QPoint
        indicator = StatusIndicator()
        indicator.show()
        APP.processEvents()
        received = []
        indicator.details_requested.connect(received.append)
        QTest.mouseClick(indicator, Qt.MouseButton.LeftButton)
        QTest.mouseClick(indicator, Qt.MouseButton.RightButton)
        self.assertEqual(len(received), 2)
        self.assertTrue(all(isinstance(point, QPoint) for point in received))

if __name__ == '__main__':
    unittest.main()
