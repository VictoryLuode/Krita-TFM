from test_preview import prepared_panel
import json
import pytest
from test_grid_menu import finish
import test_docker as fixture
from qt_test_binding import QEvent, QPoint, QPointF, Qt, QRect
from qt_test_binding import QMouseEvent

M = fixture.MODULE


class Settings:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def readSetting(self, group, key, default):
        return self.data.get((group, key), default)

    def writeSetting(self, group, key, value):
        self.data[group, key] = value


def drag(widget, start, delta):
    origin = widget.mapToGlobal(start)
    end = origin + delta
    for kind, point, buttons in ((QEvent.Type.MouseButtonPress, origin, Qt.MouseButton.LeftButton),
                                  (QEvent.Type.MouseMove, end, Qt.MouseButton.LeftButton),
                                  (QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.NoButton)):
        event = QMouseEvent(kind, QPointF(widget.mapFromGlobal(point)), QPointF(point),
                            Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton,
                            buttons, Qt.KeyboardModifier.NoModifier)
        fixture.APP.sendEvent(widget, event)


def test_dragging_bottom_right_resizes_without_stretching_the_image(tmp_path):
    p = prepared_panel(tmp_path)
    try:
        p.preview()
        dialog = p.preview_dialog
        size = dialog.size()
        position = dialog.pos()
        drag(dialog.image_label, QPoint(size.width() - 2, size.height() - 2), QPoint(80, 40))
        assert dialog.width() == size.width() + 80 and dialog.height() == size.height() + 40
        assert dialog.pos() == position
        pixmap = dialog.image_label.pixmap()
        assert abs(pixmap.width() * 320 - pixmap.height() * 480) <= 480, 'Image was stretched instead of fitted'
        assert dialog.image_label.geometry() == dialog.rect()
        assert dialog.close_button.geometry().right() >= dialog.width() - 12
        assert dialog.rect().contains(dialog.close_button.geometry())
    finally:
        finish(p)


def test_last_position_and_size_are_persisted_and_restored(tmp_path, monkeypatch):
    p = prepared_panel(tmp_path)
    store = Settings()
    monkeypatch.setattr(M.Krita, 'instance', staticmethod(lambda: store))
    try:
        p.preview()
        dialog = p.preview_dialog
        dialog.move(100, 90)
        dialog.resize(360, 240)
        geometry = dialog.geometry()
        dialog.close()
        assert ('quick_image_search', 'preview_geometry') in store.data, 'Geometry was not written to Krita settings'
        fresh_store = Settings(store.data)
        monkeypatch.setattr(M.Krita, 'instance', staticmethod(lambda: fresh_store))
        p.preview()
        assert p.preview_dialog.geometry() == geometry, 'Preview forgot position or size'
        assert set(store.data) == {('quick_image_search', 'preview_geometry')}, 'Unrelated Krita settings were changed'
    finally:
        finish(p)


@pytest.mark.parametrize('edge,dx,dy', [('left', -20, 0), ('right', 20, 0), ('top', 0, -20),
                                     ('bottom', 0, 20), ('top-left', -20, -20),
                                     ('top-right', 20, -20), ('bottom-left', -20, 20)])
def test_each_other_resize_edge_keeps_the_opposite_edge_anchored(tmp_path, edge, dx, dy):
    p = prepared_panel(tmp_path)
    try:
        p.preview()
        dialog = p.preview_dialog
        before = dialog.geometry()
        point = dialog.rect().center()
        expected = QRect(before)
        if 'left' in edge:
            point.setX(2)
            expected.setLeft(before.left() + dx)
        if 'right' in edge:
            point.setX(dialog.width() - 2)
            expected.setRight(before.right() + dx)
        if 'top' in edge:
            point.setY(2)
            expected.setTop(before.top() + dy)
        if 'bottom' in edge:
            point.setY(dialog.height() - 2)
            expected.setBottom(before.bottom() + dy)
        drag(dialog.image_label, point, QPoint(dx, dy))
        assert dialog.geometry() == expected
    finally:
        finish(p)


@pytest.mark.parametrize('saved', ['', 'not json', '{}', '[true,0,320,240]', '[0,0,-1,50]', '[99999999999,0,320,240]'])
def test_invalid_saved_geometry_uses_safe_default(saved):
    default = QRect(100, 100, 480, 320)
    assert M.restored_preview_geometry(saved, default, [QRect(0, 0, 1920, 1080)]) == default


def test_disconnected_monitor_and_changed_resolution_keep_preview_reachable():
    default = QRect(100, 100, 480, 320)
    screen = QRect(0, 0, 1280, 720)
    restored = M.restored_preview_geometry(json.dumps([5000, 2000, 2000, 1500]), default, [screen])
    assert screen.contains(restored)
    left = QRect(-1920, 0, 1920, 1080)
    primary = QRect(0, 0, 1920, 1080)
    saved = QRect(-1600, 100, 480, 320)
    restored = M.restored_preview_geometry(json.dumps([saved.x(), saved.y(), saved.width(), saved.height()]), default, [primary, left])
    assert restored == saved, 'A connected negative-coordinate monitor should not be reset to primary'


def test_dragging_the_image_moves_the_frameless_preview(tmp_path):
    p = prepared_panel(tmp_path)
    try:
        p.preview()
        dialog = p.preview_dialog
        before = dialog.pos()
        delta = QPoint(40, 20)
        drag(dialog.image_label, dialog.rect().center(), delta)
        assert dialog.pos() == before + delta, 'Image drag did not move the preview window'
        assert dialog.isVisible()
    finally:
        finish(p)
