from test_preview import prepared_panel, wait_for
import threading
from test_grid_menu import finish, entry
import test_docker as fixture
from qt_test_binding import Qt, QPoint, QPointF, QEvent
from qt_test_binding import QImage, QColor, QPainter, QWheelEvent, QMouseEvent
from qt_test_binding import QTest

M = fixture.MODULE


def wheel(dialog, amount, point):
    fixture.APP.sendEvent(dialog.image_label, QWheelEvent(QPointF(point), QPointF(dialog.image_label.mapToGlobal(point)),
                            QPoint(), QPoint(0, amount), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))


def test_rapid_navigation_discards_stale_download_and_keeps_latest_target(tmp_path):
    p = prepared_panel(tmp_path)
    gate = threading.Event()
    blue_path, green_path = tmp_path / 'blue.png', tmp_path / 'green.png'
    for path, color in ((blue_path, 'blue'), (green_path, 'green')):
        image = QImage(48, 32, QImage.Format.Format_RGB32)
        image.fill(QColor(color))
        assert image.save(str(path))
    calls = []
    class Browser:
        def resolve(self, item):
            calls.append(item['id'])
            return {'url': 'https://example.org/large/' + item['id']}
    def download(url, *args):
        if '/large/2' in url:
            gate.wait(2)
            return blue_path.read_bytes()
        return green_path.read_bytes()
    p.browser = Browser()
    p.downloader = download
    p.append_results([entry(2), entry(3)])
    try:
        p.preview()
        dialog = p.preview_dialog
        geometry = dialog.geometry()
        QTest.keyClick(dialog, Qt.Key.Key_Right)
        assert dialog.isVisible() and dialog.loading
        QTest.keyClick(dialog, Qt.Key.Key_Right)
        assert p.grid.currentRow() == 2 and dialog.isVisible() and dialog.loading
        gate.set()
        wait_for(lambda: not dialog.loading and not p.busy)
        assert p.preview_dialog is dialog and dialog.geometry() == geometry
        assert dialog._image.toImage().pixelColor(10, 10) == QColor('green'), 'Old blue image overwrote the latest target'
        assert calls == ['2', '3']
    finally:
        gate.set()
        finish(p)


def test_overlay_arrows_reuse_navigation_and_do_not_overlap_close_or_resize(tmp_path):
    p = prepared_panel(tmp_path)
    p.append_results([entry(2)])
    p.grid.item(1).setData(M.PATH_ROLE, str(tmp_path / 'preview.png'))
    try:
        p.preview()
        dialog = p.preview_dialog
        assert hasattr(dialog, 'previous_button') and hasattr(dialog, 'next_button')
        assert not dialog.previous_button.isEnabled() and dialog.next_button.isEnabled()
        geometry = dialog.geometry()
        QTest.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
        assert p.grid.currentRow() == 1 and dialog.geometry() == geometry and dialog.isVisible()
        assert dialog.previous_button.isEnabled() and not dialog.next_button.isEnabled()
        QTest.keyClick(dialog.previous_button, Qt.Key.Key_Left)
        assert p.grid.currentRow() == 0, 'Arrow-button focus broke keyboard navigation'
        dialog.resize(dialog.minimumSize())
        fixture.APP.processEvents()
        assert not dialog.next_button.geometry().intersects(dialog.close_button.geometry())
        assert dialog.previous_button.x() >= 8 and dialog.next_button.geometry().right() < dialog.width() - 8
    finally:
        finish(p)


def test_arrow_keys_switch_adjacent_images_in_the_same_preview(tmp_path):
    p = prepared_panel(tmp_path)
    second = QImage(480, 320, QImage.Format.Format_RGB32)
    second.fill(QColor('blue'))
    second_path = tmp_path / 'second.png'
    assert second.save(str(second_path))
    p.append_results([entry(2)])
    p.grid.item(1).setData(M.PATH_ROLE, str(second_path))
    try:
        p.preview()
        dialog = p.preview_dialog
        geometry = dialog.geometry()
        QTest.keyClick(dialog, Qt.Key.Key_Right)
        assert p.grid.currentRow() == 1, 'Right arrow did not advance to the next image'
        assert p.preview_dialog is dialog and dialog.geometry() == geometry
        assert dialog._image.toImage().pixelColor(10, 10) == QColor('blue')
        QTest.keyClick(dialog, Qt.Key.Key_Right)
        assert p.grid.currentRow() == 1, 'Last image should not wrap or start a new search'
        QTest.keyClick(dialog, Qt.Key.Key_Left)
        assert p.grid.currentRow() == 0
        assert dialog.isVisible() and dialog.geometry() == geometry
    finally:
        finish(p)


def test_middle_drag_pans_image_and_double_click_restores_fit(tmp_path):
    p = prepared_panel(tmp_path)
    try:
        p.preview()
        dialog = p.preview_dialog
        geometry = dialog.geometry()
        fit_rect = dialog.image_rect()
        wheel(dialog, 120, QPoint(120, 160))
        zoomed = dialog.image_rect()
        origin = dialog.image_label.mapToGlobal(QPoint(120, 160))
        end = origin + QPoint(30, 20)
        for kind, point, buttons in ((QEvent.Type.MouseButtonPress, origin, Qt.MouseButton.MiddleButton),
                                     (QEvent.Type.MouseMove, end, Qt.MouseButton.MiddleButton),
                                     (QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.NoButton)):
            button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.MiddleButton
            fixture.APP.sendEvent(dialog.image_label, QMouseEvent(kind, QPointF(dialog.image_label.mapFromGlobal(point)),
                                   QPointF(point), button, buttons, Qt.KeyboardModifier.NoModifier))
        assert dialog.image_rect().topLeft() == zoomed.topLeft() + QPointF(30, 20), 'Middle drag did not pan the image'
        assert dialog.geometry() == geometry
        QTest.mouseDClick(dialog.image_label, Qt.MouseButton.LeftButton, pos=QPoint(120, 160))
        assert dialog.image_rect() == fit_rect, 'Double-click did not restore fit'
        assert dialog.geometry() == geometry
    finally:
        finish(p)


def test_preview_wheel_zooms_pixels_around_pointer_without_resizing_window(tmp_path):
    p = prepared_panel(tmp_path)
    image = QImage(480, 320, QImage.Format.Format_RGB32)
    image.fill(QColor('red'))
    painter = QPainter(image)
    painter.fillRect(240, 0, 240, 320, QColor('blue'))
    painter.end()
    assert image.save(str(tmp_path / 'preview.png'))
    try:
        p.preview()
        dialog = p.preview_dialog
        geometry = dialog.geometry()
        assert dialog.image_label.grab().toImage().pixelColor(250, 160) == QColor('blue')
        wheel(dialog, 120, QPoint(120, 160))
        rendered = dialog.image_label.grab().toImage()
        assert rendered.pixelColor(250, 160) == QColor('red'), 'Wheel did not magnify the actual image pixels'
        assert rendered.pixelColor(120, 160) == QColor('red'), 'Pointer anchor drifted'
        assert dialog.geometry() == geometry, 'Image zoom changed saved window geometry'
    finally:
        finish(p)
