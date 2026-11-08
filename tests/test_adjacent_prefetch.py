import threading
from pathlib import Path
from qt_test_binding import Qt
from qt_test_binding import QTest
from test_preview import prepared_panel, wait_for
from test_grid_menu import entry, finish
from test_search_history_ui import image_bytes
import test_docker as fixture

M = fixture.MODULE


def target(number):
    return dict(entry(number), image_url='https://i.pinimg.com/originals/example-' + str(number) + '.png')


def test_prefetch_only_next_known_public_original_and_reuses_it_on_navigation(tmp_path):
    p = prepared_panel(tmp_path)
    wait_for(lambda: not p.jobs)
    calls = []
    class NoResolve:
        def resolve(self, asset):
            raise AssertionError('Known Pinterest original prefetch must not touch a shared browser session')
    p.browser = NoResolve()
    p.downloader = lambda url, *args: calls.append(url) or image_bytes()
    p.append_results([target(2), target(3)], cached_images={})
    try:
        p.preview()
        p.prefetch_adjacent()
        wait_for(lambda: not p.jobs)
        assert calls == [target(2)['image_url']]
        assert not p.busy and p.grid.currentRow() == 0
        assert Path(p.grid.item(1).data(M.PATH_ROLE)).is_file()
        popup = p.preview_dialog
        QTest.keyClick(popup, Qt.Key.Key_Right)
        assert p.preview_dialog is popup and not popup.loading and p.grid.currentRow() == 1
        assert calls == [target(2)['image_url']]
    finally:
        finish(p)


def test_prefetch_failure_is_quiet_and_does_not_loop(tmp_path):
    p = prepared_panel(tmp_path)
    wait_for(lambda: not p.jobs)
    calls = []
    def download(url, *args):
        calls.append(url)
        raise OSError('background unavailable')
    p.downloader = download
    p.append_results([target(2)], cached_images={})
    try:
        p.preview()
        before = p.status.text()
        p.prefetch_adjacent()
        wait_for(lambda: not p.jobs)
        p.prefetch_adjacent()
        assert calls == [target(2)['image_url']]
        assert p.status.text() == before and not p.busy
        assert p.grid.currentRow() == 0 and not p.preview_dialog.loading
    finally:
        finish(p)


def test_old_prefetch_does_not_touch_new_gallery(tmp_path):
    p = prepared_panel(tmp_path)
    wait_for(lambda: not p.jobs)
    gate = threading.Event()
    started = threading.Event()
    def download(url, *args):
        started.set()
        gate.wait(2)
        return image_bytes()
    p.downloader = download
    p.append_results([target(2)], cached_images={})
    try:
        p.preview()
        p.prefetch_adjacent()
        assert started.wait(2)
        p.generation += 1
        p.grid.clear()
        gate.set()
        wait_for(lambda: not p.jobs)
        assert not p._prepared_cache
    finally:
        gate.set()
        finish(p)


def test_navigation_reuses_an_inflight_prefetch_instead_of_downloading_twice(tmp_path):
    p = prepared_panel(tmp_path)
    wait_for(lambda: not p.jobs)
    gate = threading.Event()
    started = threading.Event()
    calls = []
    def download(url, *args):
        calls.append(url)
        started.set()
        gate.wait(2)
        return image_bytes()
    p.downloader = download
    p.append_results([target(2)], cached_images={})
    try:
        p.preview()
        popup = p.preview_dialog
        p.prefetch_adjacent()
        assert started.wait(2)
        QTest.keyClick(popup, Qt.Key.Key_Right)
        assert popup.loading and p.grid.currentRow() == 1
        gate.set()
        wait_for(lambda: not p.jobs)
        assert calls == [target(2)['image_url']]
        assert not popup.loading and not popup._image.isNull()
    finally:
        gate.set()
        finish(p)
