from qt_test_binding import Qt
from qt_test_binding import QTest
from test_search_history_ui import panel, wait, finish, Backend, image_bytes
import test_docker as fixture

M = fixture.MODULE


def test_failed_thumbnail_click_retries_only_that_asset_without_selecting_it(tmp_path):
    calls = []
    def download(url, *args):
        calls.append(url)
        if len(calls) == 1:
            raise OSError('temporary image failure')
        return image_bytes()
    p = panel(tmp_path, downloader=download)
    try:
        p.search_input.setText('cat')
        p.search()
        wait(p)
        item = p.grid.item(0)
        assert item.data(M.THUMB_ERROR_ROLE)
        assert p.grid.currentRow() == -1
        rect = p.grid.visualItemRect(item)
        QTest.mouseClick(p.grid.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
        wait(p)
        assert len(calls) == 2 and calls[0] == calls[1]
        assert not item.icon().isNull() and not item.data(M.THUMB_ERROR_ROLE)
        assert p.grid.currentRow() == -1, 'A retry click must not start downloading the original'
        p.set_thumbnail((p.generation, 0, b'', 0, 'late old failure'))
        assert not item.data(M.THUMB_ERROR_ROLE), 'A stale request overwrote a newer retry'
    finally:
        finish(p)


def test_preview_retry_reuses_popup_and_geometry_after_a_decode_failure(tmp_path):
    class OriginalBackend(Backend):
        def resolve(self, entry):
            return {'url': 'https://example.com/original'}
    originals = []
    def download(url, *args):
        if url.endswith('/original'):
            originals.append(url)
            if len(originals) == 1:
                return b'not an image'
        return image_bytes()
    p = panel(tmp_path, OriginalBackend(), download)
    try:
        p.search_input.setText('cat')
        p.search()
        wait(p)
        p.grid.setCurrentRow(0)
        p.preview()
        popup = p.preview_dialog
        geometry = popup.geometry()
        wait(p)
        assert not popup.retry_button.isHidden() and not popup.loading
        assert 0 <= popup.retry_button.y() - popup.error_label.geometry().bottom() <= 12
        QTest.mouseClick(popup.retry_button, Qt.MouseButton.LeftButton)
        wait(p)
        assert len(originals) == 2
        assert p.preview_dialog is popup and popup.geometry() == geometry
        assert not popup.loading and popup.retry_button.isHidden() and not popup._image.isNull()
    finally:
        finish(p)
