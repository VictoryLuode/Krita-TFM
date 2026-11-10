from qt_test_binding import Qt, QPoint
from qt_test_binding import QTest
from qt_test_binding import QPushButton
from test_search_history_ui import panel, finish, wait
import test_docker as fixture


def test_favorites_are_source_free_tabs_with_close_and_persistent_reorder_alias(tmp_path):
    p = panel(tmp_path)
    try:
        a = p.search_store.toggle_favorite('pinterest', 'first')
        b = p.search_store.toggle_favorite('google', 'second')
        p.update_library_controls()
        tabs = p.favorite_tabs
        assert [tabs.tabText(i) for i in range(tabs.count())] == ['first', 'second']
        assert tabs.tabsClosable() and tabs.isMovable()
        p.set_favorite_alias(a['id'], '墙面')
        assert tabs.tabText(0) == '墙面'
        tabs.moveTab(0, 1)
        assert [r['id'] for r in p.search_store.favorites()] == [b['id'], a['id']]
        assert not p.browser.calls, 'Sorting must not activate another search'
        q = panel(tmp_path)
        try:
            assert [q.favorite_tabs.tabText(i) for i in range(2)] == ['second', '墙面']
        finally:
            finish(q)
        tabs.tabCloseRequested.emit(0)
        assert tabs.count() == 1
        assert not p.search_store.get(b['id'])
        assert not p.browser.calls, 'Closing a favorite must not search its neighbor'
    finally:
        finish(p)


def test_repeated_tab_clicks_activate_and_history_has_no_provider_names(tmp_path):
    p = panel(tmp_path)
    try:
        p.toggle_record_favorite('google', 'same query')
        p.search_store.record_search('pinterest', 'recent query')
        menu = p.build_history_menu()
        records = [action for action in menu.actions() if isinstance(action.data(), str)]
        assert all('Google' not in action.text() and 'Pinterest' not in action.text() for action in records)
        tabs = p.favorite_tabs
        QTest.mouseClick(tabs, Qt.MouseButton.LeftButton, pos=tabs.tabRect(0).center())
        wait(p)
        assert p._active_search == ('google', 'same query')
        assert p.source.currentData() == 'google'
        assert not any(button.text() in ('大图预览', 'Google 验证窗口') for button in p.findChildren(QPushButton))
        menu.deleteLater()
    finally:
        finish(p)


def test_status_icon_keeps_full_detail_and_google_verification_is_explicit(tmp_path):
    p = panel(tmp_path)
    try:
        text = '失败：Provider requires verification or login'
        p.status.setText(text)
        assert p.status.isVisible()
        assert p.status.width() == 22 and p.status.toolTip() == text
        menu = p.build_status_menu()
        assert len(menu.actions()) == 1, 'Only profile reset is available for Pinterest'
        assert not p.verify_button.isEnabled()
        menu.deleteLater()
        p.source.setCurrentIndex(p.source.findData('google'))
        menu = p.build_status_menu()
        assert len(menu.actions()) == 2
        assert menu.actions()[0].text() == fixture.MODULE.tr('Open Google verification window', '打开 Google 验证窗口')
        assert p.verify_button.isEnabled()
        assert not p.browser.calls
        menu.deleteLater()
        p.status.clear()
        assert p.status.isHidden()
    finally:
        finish(p)
