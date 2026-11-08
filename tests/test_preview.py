import time
import threading
import pytest

import test_docker as fixture
from test_grid_menu import entry, finish
from qt_test_binding import Qt, QPoint, QEvent
from qt_test_binding import QImage, QColor
from qt_test_binding import QTest
from qt_test_binding import QPushButton, QScrollArea

M = fixture.MODULE


def prepared_panel(tmp_path):
    path = tmp_path / 'preview.png'
    image = QImage(480, 320, QImage.Format.Format_RGB32)
    image.fill(QColor('#557799'))
    assert image.save(str(path))
    p = M.ImageSearchDocker(browser=object(), downloader=lambda *args: fixture.ImageSearchTests().png())
    p.display_results([entry()])
    p.grid.item(0).setData(M.PATH_ROLE, str(path))
    p.grid.setCurrentRow(0)
    return p


def wait_for(predicate):
    end = time.monotonic() + 3
    while time.monotonic() < end:
        QTest.qWait(10)
        if predicate():
            return
    assert predicate()


def test_preview_is_only_image_with_overlay_close_button(tmp_path):
    p = prepared_panel(tmp_path)
    try:
        p.preview()
        dialog = p.preview_dialog
        assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint, 'Preview still has native window chrome'
        assert dialog.windowType() == Qt.WindowType.Popup
        assert dialog.testAttribute(Qt.WidgetAttribute.WA_NoMouseReplay), 'Native popup must not replay the dismissal click onto the canvas'
        assert not dialog.findChildren(QScrollArea), 'Remove the scroll-pane frame'
        assert dialog.windowTitle() == ''
        assert dialog.image_label.pixmap().size() == dialog.size()
        assert dialog.rect().contains(dialog.close_button.geometry())
        assert dialog.close_button.x() > dialog.width() // 2
        QTest.mouseClick(dialog.close_button, Qt.MouseButton.LeftButton)
        assert not dialog.isVisible()
    finally:
        if p.preview_dialog is not None:
            p.preview_dialog.close()
        finish(p)


def test_outside_click_dismisses_preview_without_activating_underlying_control(tmp_path):
    p = prepared_panel(tmp_path)
    outside = QPushButton('Underlying canvas stand-in')
    clicks = []
    outside.clicked.connect(lambda: clicks.append(True))
    outside.move(0, 0)
    outside.show()
    try:
        p.preview()
        dialog = p.preview_dialog
        assert not dialog.frameGeometry().contains(outside.mapToGlobal(QPoint(5, 5)))
        dialog.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay, False)
        QTest.mouseClick(outside, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
        assert not dialog.isVisible(), 'Outside click did not dismiss image preview'
        assert not clicks, 'Dismissal click leaked into underlying content'
        assert dialog.testAttribute(Qt.WidgetAttribute.WA_NoMouseReplay), 'Reassert native replay protection before closing'
        QTest.mouseClick(outside, Qt.MouseButton.LeftButton)
        assert clicks == [True], 'Closed preview kept intercepting normal clicks'
    finally:
        outside.close()
        if p.preview_dialog is not None:
            p.preview_dialog.close()
        finish(p)


def test_switching_to_another_application_dismisses_preview(tmp_path):
    p = prepared_panel(tmp_path)
    try:
        p.preview()
        fixture.APP.sendEvent(p.preview_dialog, QEvent(QEvent.Type.WindowDeactivate))
        assert not p.preview_dialog.isVisible(), 'Preview stayed open when another app was activated'
    finally:
        if p.preview_dialog is not None:
            p.preview_dialog.close()
        finish(p)


def test_double_click_opens_loading_preview_immediately_and_replaces_in_place(tmp_path):
    class Browser:
        def resolve(self, item):
            return {'url': 'https://i.pinimg.com/originals/large.png'}
    gate = threading.Event()
    data = fixture.ImageSearchTests().png()
    def download(url, *args):
        if 'originals' in url:
            gate.wait(2)
        return data
    p = M.ImageSearchDocker(browser=Browser(), cache_dir=tmp_path, downloader=download)
    try:
        p.display_results([entry()])
        p.grid.setCurrentRow(0)
        assert p.busy
        p.grid.itemDoubleClicked.emit(p.grid.item(0))
        dialog = p.preview_dialog
        assert dialog is not None and dialog.isVisible(), 'Open the window before the image download completes'
        assert dialog.loading and dialog.spinner.isVisible()
        angle = dialog.spinner.angle
        for _ in range(20):
            QTest.qWait(25)
            if dialog.spinner.angle != angle:
                break
        assert dialog.spinner.angle != angle, f'Loading indicator is not animated: visible={dialog.isVisible()}, spinner={dialog.spinner.isVisible()}, active={dialog.spinner.timer.isActive()}, loading={dialog.loading}'
        dialog.move(100, 80)
        dialog.resize(360, 240)
        geometry = dialog.geometry()
        gate.set()
        wait_for(lambda: not dialog.loading)
        assert p.preview_dialog is dialog and dialog.isVisible()
        assert dialog.geometry() == geometry, 'Replacing the spinner reset preview geometry'
        assert not dialog.spinner.isVisible() and not dialog.spinner.timer.isActive()
        assert not dialog.image_label.pixmap().isNull()
    finally:
        gate.set()
        if p.preview_dialog is not None:
            p.preview_dialog.close()
        finish(p)


def test_image_click_keeps_preview_open_and_escape_closes_it(tmp_path):
    p = prepared_panel(tmp_path)
    try:
        p.preview()
        QTest.mouseClick(p.preview_dialog.image_label, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        assert p.preview_dialog.isVisible(), 'Clicking the image itself should not dismiss it'
        QTest.keyClick(p.preview_dialog, Qt.Key.Key_Escape)
        assert not p.preview_dialog.isVisible()
    finally:
        if p.preview_dialog is not None:
            p.preview_dialog.close()
        finish(p)


def test_missing_cached_file_does_not_keep_a_deleted_preview_reference(tmp_path):
    p = prepared_panel(tmp_path)
    try:
        p.preview()
        (tmp_path / 'preview.png').unlink()
        p.preview()
        QTest.qWait(10)
        assert p.preview_dialog is None
        assert '无法读取' in p.status.text()
    finally:
        finish(p)


def test_download_failure_stops_loading_animation_and_keeps_close_available(tmp_path):
    class Browser:
        def resolve(self, item):
            raise OSError('网络不可用')
    p = M.ImageSearchDocker(browser=Browser(), cache_dir=tmp_path, downloader=lambda *args: fixture.ImageSearchTests().png())
    try:
        p.display_results([entry()])
        p.grid.setCurrentRow(0)
        p.preview()
        dialog = p.preview_dialog
        wait_for(lambda: not p.busy)
        assert dialog.isVisible() and not dialog.loading, 'Failed request left an endless spinner'
        assert not dialog.spinner.timer.isActive()
        assert '网络不可用' in dialog.error_label.text()
        dialog.close_button.click()
        assert not dialog.isVisible()
    finally:
        finish(p)


@pytest.mark.parametrize('cancel', ['selection', 'query'])
def test_delayed_preview_does_not_open_after_user_moves_on(tmp_path, cancel):
    class Browser:
        def resolve(self, item):
            return {'url': 'https://i.pinimg.com/originals/large.png'}
    gate = threading.Event()
    data = fixture.ImageSearchTests().png()
    def download(url, *args):
        if 'originals' in url:
            gate.wait(2)
        return data
    p = M.ImageSearchDocker(browser=Browser(), cache_dir=tmp_path, downloader=download)
    try:
        p.display_results([entry(1), entry(2)])
        p.grid.setCurrentRow(0)
        p.grid.itemDoubleClicked.emit(p.grid.item(0))
        if cancel == 'selection':
            p.grid.setCurrentRow(1)
        else:
            p.search_input.setText('new query')
        gate.set()
        wait_for(lambda: not p.busy)
        assert not p.preview_dialog.isVisible(), 'Stale preview stayed open after switching image or editing the query'
    finally:
        gate.set()
        if p.preview_dialog is not None:
            p.preview_dialog.close()
        finish(p)
