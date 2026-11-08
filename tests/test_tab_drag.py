from qt_test_binding import Qt, QPoint, QPointF, QEvent
from qt_test_binding import QMouseEvent
from qt_test_binding import QTest
from test_search_history_ui import panel, finish
import test_docker as fixture


def test_dragging_a_favorite_reorders_without_submitting_a_search(tmp_path):
    p = panel(tmp_path)
    try:
        a = p.search_store.toggle_favorite('pinterest', 'first')
        b = p.search_store.toggle_favorite('google', 'second')
        p.update_library_controls()
        fixture.APP.processEvents()
        tabs = p.favorite_tabs
        start = tabs.tabRect(0).center()
        end = tabs.tabRect(1).center()
        def event(kind, point, button, buttons):
            fixture.APP.sendEvent(tabs, QMouseEvent(kind, QPointF(point), QPointF(tabs.mapToGlobal(point)), button, buttons, Qt.KeyboardModifier.NoModifier))
        event(QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        for step in range(1, 9):
            point = start + QPoint((end.x() - start.x()) * step // 8, 0)
            event(QEvent.Type.MouseMove, point, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
            QTest.qWait(30)
        event(QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
        QTest.qWait(200)
        assert [r['id'] for r in p.search_store.favorites()] == [b['id'], a['id']]
        assert not p.browser.calls, 'Dragging a tab must not launch a search'
    finally:
        finish(p)
