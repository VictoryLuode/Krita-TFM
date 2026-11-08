import threading
from qt_test_binding import QTest
from test_search_history_ui import panel, wait, finish, Backend, image_bytes
import test_docker as fixture

M = fixture.MODULE


class DelayedBackend(Backend):
    def __init__(self, gate):
        super().__init__()
        self.gate = gate
        self.started = threading.Event()

    def search(self, source, query, limit=24):
        if query == 'first':
            self.calls.append(('search', source, query))
            self.started.set()
            self.gate.wait(3)
            return [dict(id='first', source=source, title=query, thumbnail='https://example.com/first')]
        return super().search(source, query, limit)


def test_latest_manual_search_is_queued_and_only_executed_searches_enter_history(tmp_path):
    gate = threading.Event()
    browser = DelayedBackend(gate)
    p = panel(tmp_path, browser)
    try:
        p.search_input.setText('first')
        p.search_button.click()
        assert browser.started.wait(2) and p.busy
        assert p.search_button.isEnabled(), 'New searches must remain submit-able while busy'
        p.search_input.setText('discarded')
        p.search_button.click()
        p.source.setCurrentIndex(p.source.findData('google'))
        p.search_input.setText('last')
        p.search_button.click()
        assert browser.calls == [('search', 'pinterest', 'first')]
        gate.set()
        wait(p)
        assert browser.calls == [('search', 'pinterest', 'first'), ('search', 'google', 'last')]
        assert p._active_search == ('google', 'last')
        assert {r['query'] for r in p.search_store.recent()} == {'first', 'last'}
    finally:
        gate.set()
        finish(p)


def test_queued_request_keeps_its_query_but_does_not_overwrite_a_new_unsubmitted_draft(tmp_path):
    gate = threading.Event()
    browser = DelayedBackend(gate)
    p = panel(tmp_path, browser)
    try:
        p.search_input.setText('first')
        p.search()
        assert browser.started.wait(2)
        p.search_input.setText('queued')
        p.search()
        p.search_input.setText('new unsubmitted draft')
        gate.set()
        wait(p)
        assert browser.calls[-1] == ('search', 'pinterest', 'queued')
        assert p.search_input.text() == 'new unsubmitted draft'
        assert p._active_search == ('pinterest', 'queued')
    finally:
        gate.set()
        finish(p)
