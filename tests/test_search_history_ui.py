import time
from qt_test_binding import QBuffer, QIODevice, Qt, QPoint
from qt_test_binding import QImage
from qt_test_binding import QTest

import test_docker as fixture

M = fixture.MODULE


def image_bytes():
    image = QImage(48, 32, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    return bytes(buffer.data())


class Backend:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.page = 0

    def search(self, source, query, limit=24):
        self.calls.append(('search', source, query))
        if self.fail:
            raise OSError('offline')
        self.page = 0
        return [dict(source=source, id='1', title=query, thumbnail='https://example.com/thumb1')]

    def has_more(self, source):
        return self.page < 2

    def more(self, source, limit=24):
        self.calls.append(('more', source))
        self.page += 1
        return [dict(source=source, id=str(self.page + 1), thumbnail=f'https://example.com/thumb{self.page + 1}')]

    def resolve(self, entry):
        raise AssertionError('Restoring a selection must not fetch originals')


def panel(tmp_path, backend=None, downloader=None):
    p = M.ImageSearchDocker(browser=backend or Backend(), cache_dir=tmp_path / 'images',
                            user_data_dir=tmp_path / 'data', downloader=downloader or (lambda *args: image_bytes()))
    p.resize(420, 360)
    p.show()
    fixture.APP.processEvents()
    return p


def wait(p):
    deadline = time.monotonic() + 5
    while (p.busy or p.jobs) and time.monotonic() < deadline:
        QTest.qWait(10)
    assert not p.busy and not p.jobs
    fixture.APP.processEvents()


def finish(p):
    p.shutdown()
    p.close()
    fixture.APP.processEvents()


def test_typing_opening_menu_and_starring_do_not_search(tmp_path):
    p = panel(tmp_path)
    try:
        p.search_input.setText('  cat  ')
        assert not p.search_store.recent()
        assert p.favorite_action.isEnabled()
        p.favorite_action.trigger()
        record = p.search_store.favorites()[0]
        assert record['query'] == 'cat' and record['last_used'] is None
        menu = p.build_history_menu()
        assert any(action.data() == record['id'] for action in menu.actions())
        assert p.browser.calls == []
        assert len(p.search_input.actions()) == 2
        p.search_input.clear()
        assert not p.favorite_action.isEnabled()
    finally:
        finish(p)


def test_search_history_and_new_input_cannot_capture_old_gallery(tmp_path):
    p = panel(tmp_path)
    try:
        p.search_input.setText('cat')
        p.search()
        wait(p)
        assert p.search_store.recent()[0]['query'] == 'cat'
        p.search_input.setText('unsubmitted')
        p.favorite_action.trigger()
        record = p.search_store.favorites()[0]
        p.flush_favorite_snapshot()
        p._cache_executor.submit(lambda: None).result(5)
        assert p.favorite_cache.load(p.favorite_key(record)) is None
        p.search_store.clear_recent()
        assert p.search_store.favorites()[0]['query'] == 'unsubmitted'
    finally:
        finish(p)


def test_favorite_cache_restores_thumbnails_without_any_network_and_refresh_failure_preserves_it(tmp_path):
    p = panel(tmp_path)
    p.search_input.setText('cat')
    p.search()
    wait(p)
    p.favorite_action.trigger()
    record = p.search_store.favorites()[0]
    p.flush_favorite_snapshot()
    finish(p)
    backend = Backend()
    def forbidden(*args):
        raise AssertionError('No thumbnail network on cache hit')
    q = panel(tmp_path, backend, forbidden)
    try:
        q.activate_record(record['id'])
        wait(q)
        assert q.grid.count() == 1 and not q.grid.item(0).icon().isNull()
        assert backend.calls == [] and q._cached_page
        assert q.source.currentData() == 'pinterest' and q.search_input.text() == 'cat'
        backend.fail = True
        q.activate_record(record['id'], refresh=True)
        wait(q)
        assert q.grid.count() == 1 and q.grid.item(0).data(M.ENTRY_ROLE)['id'] == '1'
        assert q.favorite_cache.load(q.favorite_key(record))['entries'][0]['id'] == '1'
        backend.fail = False
        q.load_more()
        wait(q)
        assert [q.grid.item(i).data(M.ENTRY_ROLE)['id'] for i in range(q.grid.count())] == ['1', '2']
        assert backend.calls[-2:] == [('search', 'pinterest', 'cat'), ('more', 'pinterest')]
    finally:
        finish(q)


def test_busy_queue_keeps_only_latest_record_without_partial_restore(tmp_path):
    p = panel(tmp_path)
    try:
        a = p.search_store.record_search('google', 'first')
        b = p.search_store.record_search('pinterest', 'last')
        p.search_input.setText('current')
        p.busy = True
        p.activate_record(a['id'])
        p.activate_record(b['id'])
        assert p.search_input.text() == 'current' and p.source.currentData() == 'pinterest'
        p.busy = False
        p.resume_library()
        wait(p)
        assert p.browser.calls == [('search', 'pinterest', 'last')]
    finally:
        p.busy = False
        finish(p)


def test_record_restore_reuses_real_translation_only_until_user_edits(tmp_path):
    p = panel(tmp_path)
    try:
        record = p.search_store.record_search('pinterest', 'old wall', '旧墙')
        p.activate_record(record['id'])
        wait(p)
        assert p.original_query() == '旧墙'
        p.search_input.setText('new wall')
        assert p.original_query() == ''
        p.search()
        wait(p)
        assert p.search_store.lookup('pinterest', 'new wall')['original_query'] == ''
    finally:
        finish(p)


def test_ephemeral_pin_ids_do_not_duplicate_the_same_cached_image(tmp_path):
    p = panel(tmp_path)
    try:
        entry = dict(source='pinterest', id='e1_first', thumbnail='https://i.pinimg.com/236x/aa/bb/image.jpg',
                     image_url='https://i.pinimg.com/originals/aa/bb/image.jpg')
        p.append_results([entry])
        p.append_results([dict(entry, id='e1_changed', thumbnail='https://i.pinimg.com/474x/aa/bb/image.jpg')])
        wait(p)
        assert p.grid.count() == 1
        assert p.grid.item(0).data(M.ENTRY_ROLE)['id'] == 'e1_first'
    finally:
        finish(p)


def test_menu_star_cancels_only_that_favorite_without_search_or_dismissal(tmp_path):
    p = panel(tmp_path)
    menu = None
    try:
        first = p.search_store.toggle_favorite('pinterest', 'tank')
        second = p.search_store.toggle_favorite('pinterest', '苹果')
        p.search_input.setText('unchanged draft')
        menu = p.build_history_menu()
        menu.popup(QPoint(80, 80))
        fixture.APP.processEvents()
        action = next(action for action in menu.actions() if action.data() == first['id'])
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.star_rect(action).center())
        fixture.APP.processEvents()
        assert menu.isVisible() and p.browser.calls == []
        assert p.search_store.get(first['id']) is None
        assert p.search_store.get(second['id'])['favorite']
        assert p.search_input.text() == 'unchanged draft'
        assert not any(action.data() == first['id'] for action in menu.actions())
        remaining = next(action for action in menu.actions() if action.data() == second['id'])
        assert not menu.star_rect(remaining).isEmpty()
    finally:
        if menu:
            menu.close()
        finish(p)


def test_clicking_favorite_records_opens_each_once_but_keeps_menu_visible(tmp_path):
    p = panel(tmp_path)
    menu = None
    try:
        records = [p.search_store.toggle_favorite('pinterest', word) for word in ('tank', '苹果')]
        menu = p.build_history_menu()
        menu.popup(QPoint(80, 80))
        fixture.APP.processEvents()
        for record in records:
            action = next(action for action in menu.actions() if action.data() == record['id'])
            QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
            wait(p)
            assert menu.isVisible()
            assert p.search_input.text() == record['query']
        assert p.browser.calls == [('search', 'pinterest', 'tank'), ('search', 'pinterest', '苹果')]
        QTest.keyClick(menu, Qt.Key.Key_Escape)
        assert not menu.isVisible()
    finally:
        if menu:
            menu.close()
        finish(p)
