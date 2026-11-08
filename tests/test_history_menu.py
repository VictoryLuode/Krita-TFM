import importlib.util
import sys
import types
from pathlib import Path

from qt_test_binding import QPoint, Qt
from qt_test_binding import QImage, QPainter
from qt_test_binding import QTest
from qt_test_binding import QAction

from test_docker import APP

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'pykrita' / 'quick_image_search' / 'history_menu.py'
PACKAGE = '_quick_image_search_history_test'
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(PATH.parent)]
    sys.modules[PACKAGE] = package
spec = importlib.util.spec_from_file_location(PACKAGE + '.history_menu', PATH)
MODULE = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = MODULE
spec.loader.exec_module(MODULE)


def make_menu(records):
    menu = MODULE.HistoryMenu()
    actions = []
    for record_id, title, favorite in records:
        action = QAction(title, menu)
        action.setData(record_id)
        action.setProperty('favorite', favorite)
        menu.addAction(action)
        actions.append(action)
    return menu, actions


def click_action(menu, action, local_point=None):
    menu.popup(QPoint(80, 80))
    APP.processEvents()
    rect = menu.actionGeometry(action)
    point = local_point or rect.center()
    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=point)
    APP.processEvents()
    return rect, point


def test_record_click_keeps_menu_open_and_repeated_rows_trigger_once_each():
    menu, actions = make_menu([('a', 'Alpha', True), ('b', 'Beta', True)])
    triggered = []
    menu.record_requested.connect(triggered.append)
    click_action(menu, actions[0])
    assert menu.isVisible()
    click_action(menu, actions[1])
    assert menu.isVisible()
    assert triggered == ['a', 'b']
    menu.hide()


def test_star_hit_emits_only_that_record_without_triggering_or_closing():
    menu, actions = make_menu([('a', 'Alpha', True), ('b', 'Beta', True)])
    triggered, requested = [], []
    menu.record_requested.connect(triggered.append)
    menu.unfavorite_requested.connect(requested.append)
    menu.popup(QPoint(80, 80))
    APP.processEvents()
    rect = menu.actionGeometry(actions[1])
    star = menu.star_rect(actions[1])
    assert not star.isEmpty() and rect.contains(star) and not star.intersects(menu.fontMetrics().boundingRect(rect, Qt.AlignmentFlag.AlignLeft, actions[1].text()))
    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=star.center())
    APP.processEvents()
    assert requested == ['b']
    assert triggered == []
    assert menu.isVisible()
    menu.hide()


def test_keyboard_enter_and_space_trigger_active_record_without_closing_and_escape_closes():
    menu, actions = make_menu([('a', 'Alpha', True)])
    triggered = []
    menu.record_requested.connect(triggered.append)
    menu.popup(QPoint(80, 80))
    APP.processEvents()
    menu.setActiveAction(actions[0])
    QTest.keyClick(menu, Qt.Key.Key_Return)
    assert menu.isVisible() and triggered == ['a']
    QTest.keyClick(menu, Qt.Key.Key_Space)
    assert menu.isVisible() and triggered == ['a', 'a']
    QTest.keyClick(menu, Qt.Key.Key_Escape)
    APP.processEvents()
    assert not menu.isVisible()


def test_empty_area_and_disabled_action_do_not_trigger_or_cancel():
    menu, actions = make_menu([('a', 'Alpha', True), ('b', 'Disabled', True)])
    actions[1].setEnabled(False)
    triggered = []
    menu.record_requested.connect(triggered.append)
    menu.popup(QPoint(80, 80))
    APP.processEvents()
    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=QPoint(2, menu.height() - 2))
    APP.processEvents()
    assert menu.isVisible() and not triggered
    rect = menu.actionGeometry(actions[1])
    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=rect.center())
    APP.processEvents()
    assert menu.isVisible() and not triggered
    menu.hide()


def test_long_text_has_separate_star_geometry_and_paint_renders_star():
    title = 'A very long history entry ' * 20
    menu, actions = make_menu([('long', title, True), ('plain', 'Not favorite', False)])
    menu.setMinimumWidth(240)
    menu.popup(QPoint(80, 80))
    APP.processEvents()
    rect = menu.actionGeometry(actions[0])
    star = menu.star_rect(actions[0])
    assert not star.isEmpty() and rect.contains(star)
    text_rect = menu.text_rect(actions[0])
    assert not star.intersects(text_rect)
    assert menu.rect().contains(star), 'Star was painted outside a screen-clamped menu'
    image = QImage(menu.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    menu.render(painter)
    painter.end()
    actions[0].setProperty('favorite', False)
    menu.update()
    APP.processEvents()
    without_star = menu.grab().toImage()
    # Compare pixels against the same menu with the star omitted, not its opaque background alpha.
    assert any(image.pixelColor(x, y) != without_star.pixelColor(x, y)
               for y in range(star.top(), star.bottom() + 1) for x in range(star.left(), star.right() + 1))
    assert menu.star_rect(actions[1]).isEmpty()
    menu.hide()
