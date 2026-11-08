from pathlib import Path
import threading
from qt_test_binding import Qt
from qt_test_binding import QTest
from test_search_history_ui import panel, wait, finish, Backend, image_bytes
import test_docker as fixture

M = fixture.MODULE


def test_emitting_a_result_does_not_release_the_still_running_thread(tmp_path, monkeypatch):
    gate = threading.Event()
    class LateFinishJob(M.Job):
        def run(self):
            self.done.emit('result')
            gate.wait(2)
    monkeypatch.setattr(M, 'Job', LateFinishJob)
    p = panel(tmp_path)
    results = []
    job = p.run_job(lambda worker: None, results.append)
    try:
        for attempt in range(100):
            if results:
                break
            QTest.qWait(5)
        assert results == ['result'] and job.isRunning()
        assert job in M._WORKERS and job in p.jobs, 'A delivered result is not a finished QThread'
    finally:
        gate.set()
        job.wait(3000)
        finish(p)


class VisualBackend(Backend):
    def __init__(self):
        super().__init__()
        self.visual_count = 0
        self.fail_similar = False

    def resolve(self, entry):
        return {'url': 'https://example.com/original/' + entry['id']}

    def similar(self, data, limit=24):
        self.calls.append(('similar',))
        if self.fail_similar:
            raise OSError('failed similar')
        self.visual_count += 1
        return [dict(source='pinterest', id='visual-' + str(self.visual_count),
                     thumbnail='https://example.com/visual/' + str(self.visual_count))]


def test_back_restores_gallery_without_network_and_rebuilds_keyword_paging(tmp_path):
    backend = VisualBackend()
    p = panel(tmp_path, backend)
    try:
        p.search_input.setText('original query')
        p.search()
        wait(p)
        p.grid.setCurrentRow(0)
        wait(p)
        original = p.grid.item(0).data(M.ENTRY_ROLE)
        prepared = p.grid.item(0).data(M.PATH_ROLE)
        p.find_similar(original, prepared)
        wait(p)
        assert not p.back_button.isHidden()
        calls = list(backend.calls)
        QTest.mouseClick(p.back_button, Qt.MouseButton.LeftButton)
        wait(p)
        assert backend.calls == calls, 'Back must restore local state without calling any provider'
        assert p.search_input.text() == 'original query'
        assert p.grid.item(0).data(M.ENTRY_ROLE) == original
        assert p.grid.currentRow() == 0 and p.grid.item(0).data(M.PATH_ROLE) == prepared
        assert p.back_button.isHidden()
        p.load_more()
        wait(p)
        assert backend.calls[-2:] == [('search', 'pinterest', 'original query'), ('more', 'pinterest')]
    finally:
        finish(p)


def test_failed_similarity_does_not_create_back_entry_and_new_search_clears_it(tmp_path):
    backend = VisualBackend()
    p = panel(tmp_path, backend)
    try:
        p.search_input.setText('original')
        p.search()
        wait(p)
        seed = tmp_path / 'seed.png'
        seed.write_bytes(image_bytes())
        backend.fail_similar = True
        p.find_similar(p.grid.item(0).data(M.ENTRY_ROLE), str(seed))
        wait(p)
        assert hasattr(p, 'back_button') and p.back_button.isHidden()
        backend.fail_similar = False
        p.find_similar(p.grid.item(0).data(M.ENTRY_ROLE), str(seed))
        wait(p)
        assert not p.back_button.isHidden()
        p.search_input.setText('new')
        p.search()
        wait(p)
        assert p.back_button.isHidden() and not p._back_stack
    finally:
        finish(p)


def test_failed_source_switch_rebuilds_the_old_gallery_session_before_more(tmp_path):
    for kind in ('similar', 'keyword'):
        backend = VisualBackend()
        p = panel(tmp_path / kind, backend)
        try:
            p.search_input.setText('original')
            p.search()
            wait(p)
            if kind == 'similar':
                seed = tmp_path / 'seed.png'
                seed.write_bytes(image_bytes())
                backend.fail_similar = True
                p.find_similar(p.grid.item(0).data(M.ENTRY_ROLE), str(seed))
            else:
                backend.fail = True
                p.search_input.setText('failing new query')
                p.search()
            wait(p)
            backend.fail = False
            p.load_more()
            wait(p)
            assert backend.calls[-2:] == [('search', 'pinterest', 'original'), ('more', 'pinterest')]
            assert p.grid.item(0).data(M.ENTRY_ROLE)['title'] == 'original'
        finally:
            finish(p)


def test_nested_similarity_returns_stepwise_and_rebuilds_the_correct_visual_context(tmp_path):
    backend = VisualBackend()
    p = panel(tmp_path, backend)
    seed = tmp_path / 'seed.png'
    seed.write_bytes(image_bytes())
    try:
        p.search_input.setText('original')
        p.search()
        wait(p)
        p.find_similar(p.grid.item(0).data(M.ENTRY_ROLE), str(seed))
        wait(p)
        first_visual = p.grid.item(0).data(M.ENTRY_ROLE)
        p.find_similar(first_visual, str(seed))
        wait(p)
        assert len(p._back_stack) == 2
        p.gallery_back()
        wait(p)
        assert p.grid.item(0).data(M.ENTRY_ROLE) == first_visual
        assert p._page_context['mode'] == 'similar' and p._page_context['entry']['id'] == '1'
        p.load_more()
        wait(p)
        assert backend.calls[-1] == ('similar',)
        assert p.grid.item(0).data(M.ENTRY_ROLE) == first_visual
        p.gallery_back()
        wait(p)
        assert p.search_input.text() == 'original' and p.grid.item(0).data(M.ENTRY_ROLE)['id'] == '1'
        assert not p._back_stack
    finally:
        finish(p)
