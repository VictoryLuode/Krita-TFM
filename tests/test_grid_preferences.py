from qt_test_binding import Qt, QPoint, QPointF
from qt_test_binding import QWheelEvent
from test_search_history_ui import panel, finish
import test_docker as fixture


def test_explicit_grid_zoom_is_remembered_for_a_new_panel_instance(tmp_path):
    p = panel(tmp_path)
    point = QPointF(40, 40)
    try:
        fixture.APP.sendEvent(p.grid.viewport(), QWheelEvent(point, point, QPoint(), QPoint(0, 120),
                              Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.NoScrollPhase, False))
        expected = p.grid.tile_size
    finally:
        finish(p)
    q = panel(tmp_path)
    try:
        assert q.grid.tile_size == expected, 'Grid size was not persisted across panel instances'
    finally:
        finish(q)


def test_old_favorite_snapshot_size_does_not_override_the_current_global_grid_size(tmp_path):
    p = panel(tmp_path)
    try:
        assert hasattr(p, '_grid_settings')
        p.remember_grid_size(240)
        p.grid.set_tile_size(240)
        record = p.search_store.toggle_favorite('pinterest', 'cat')
        p.favorite_cache.save(p.favorite_key(record), [dict(source='pinterest', id='1', thumbnail='https://example.com/a')], {}, tile_size=80)
        p.activate_record(record['id'])
        from test_search_history_ui import wait
        wait(p)
        assert p.grid.tile_size == 240
    finally:
        finish(p)
