import importlib
from pathlib import Path
import sys
import types
import json

import pytest
from qt_test_binding import QApplication, QDockWidget, QTest, Qt
from test_asset_thumbnails import save, wait_for
from qt_test_binding import QMimeData


@pytest.fixture
def assets(tmp_path,monkeypatch):
    source=Path(__file__).parents[1]/'pykrita/tfm'
    name='_asset_panel_test'
    package=types.ModuleType(name); package.__path__=[str(source)]
    monkeypatch.setitem(sys.modules,name,package)
    manager=types.ModuleType(name+'.manager')
    root=tmp_path/'assets'; root.mkdir()
    manager.assets_directory=lambda:str(root)
    manager.assets_enabled=lambda:True
    monkeypatch.setitem(sys.modules,name+'.manager',manager)
    settings={}
    app=types.SimpleNamespace(readSetting=lambda group,key,default='':settings.get((group,key),default),
                              writeSetting=lambda group,key,value:settings.__setitem__((group,key),value))
    fake=types.ModuleType('krita'); fake.DockWidget=QDockWidget
    fake.InfoObject=fake.Selection=type('Stub',(),{})
    fake.Krita=types.SimpleNamespace(instance=lambda:app)
    monkeypatch.setitem(sys.modules,'krita',fake)
    module=importlib.import_module(name+'.assets.docker')
    yield root,module
    for key in list(sys.modules):
        if key.startswith(name+'.'):
            sys.modules.pop(key,None)


def test_lazy_tree_preserves_unaffected_nodes_and_async_grid(assets):
    root,M=assets
    (root/'A'/'nested').mkdir(parents=True)
    (root/'B').mkdir()
    for i in range(20): save(root/f'{i:03}.png')
    p=M.AssetLibraryDocker(); p.resize(640,480); p.show()
    QApplication.processEvents()
    try:
        a=p._find_folder_item('A'); b=p._find_folder_item('B')
        assert a.childCount()==0 and p._find_folder_item('A/nested') is None
        a.setExpanded(True)
        assert p._find_folder_item('A/nested') is not None
        wait_for(lambda:any(not p.grid.item(i).icon().isNull() for i in range(p.grid.count())))
        (root/'A'/'new').mkdir()
        p._reload('')
        assert p._find_folder_item('B') is b and p._find_folder_item('A') is a
        assert p._find_folder_item('A/new') is not None
        p.tree.setCurrentItem(a)
        assert p.grid.count()==0
        QTest.qWait(60)
        assert p.grid.count()==0  # no stale image deliveries to the new folder
    finally:
        p._thumb_service.close()
        wait_for(lambda:not p._thumb_service.active)
        p.close();p.deleteLater();QApplication.processEvents()


def test_zoom_burst_keeps_visible_asset_and_uniform_sizes(assets):
    from unittest.mock import patch
    _, module = assets
    p = module.AssetLibraryDocker()
    p.resize(760, 480)
    p.show()
    grid = p.grid
    try:
        grid.addItems([str(i) for i in range(1000)])
        for mode in (module.VIEW_THUMB, module.VIEW_LIST):
            grid.set_view_mode(mode)
            grid.scrollToItem(grid.item(500), module.QAbstractItemView.ScrollHint.PositionAtTop)
            QApplication.processEvents()
            anchor = grid.itemAt(module.QPoint(8, 8))
            assert anchor is not None
            previous = grid.iconSize().width()
            setter = 'set_icon_edge' if mode == module.VIEW_THUMB else 'set_list_icon'
            with patch.object(grid, setter, wraps=getattr(grid, setter)) as resize:
                for _ in range(3):
                    grid._queue_zoom(1)
                assert not resize.called
                wait_for(lambda: grid.iconSize().width() != previous)
                assert resize.call_count == 1
            assert grid.iconSize().width() == previous + 3 * (16 if mode == module.VIEW_THUMB else module.LIST_STEP)
            assert grid.visualItemRect(anchor).intersects(grid.viewport().rect())
            assert grid.visualItemRect(anchor).height() == grid._item_size_hint().height()
    finally:
        p._thumb_service.close()
        p.close(); p.deleteLater(); QApplication.processEvents()


def test_reload_rename_and_internal_drop_preserve_state(assets):
    root, M = assets
    (root/'A'/'nested').mkdir(parents=True); (root/'B').mkdir()
    for i in range(80): save(root/'A'/f'{i:03}.png')
    p=M.AssetLibraryDocker();p.resize(420,350);p.show()
    QApplication.processEvents()
    try:
        a=p._find_folder_item('A');a.setExpanded(True)
        p.tree.setCurrentItem(a);QApplication.processEvents()
        p.grid.item(2).setSelected(True);p.grid.item(3).setSelected(True)
        selected=set(p._selected_rels())
        p.grid.verticalScrollBar().setValue(p.grid.verticalScrollBar().maximum()//2)
        scroll=p.grid.verticalScrollBar().value()
        p._reload('A');QApplication.processEvents()
        assert set(p._selected_rels())==selected
        assert p.grid.verticalScrollBar().value()==scroll
        assert p._find_folder_item('A').isExpanded()
        untouched=p._find_folder_item('B')
        a=p._find_folder_item('A');a.setText(0,'Renamed')
        wait_for(lambda:p._browsed=='Renamed')
        assert (root/'Renamed/002.png').is_file()
        assert p._find_folder_item('B') is untouched
        mime=QMimeData();mime.setData('application/x-tfm-assets',json.dumps({'paths':['Renamed/002.png','Renamed/003.png']}).encode())
        p._drop_on_folder('B',mime);QApplication.processEvents()
        assert p._browsed=='B' and p.grid.count()==2
        assert (root/'B/002.png').is_file() and not (root/'Renamed/002.png').exists()
        assert p._selected_rels()==['B/003.png']
    finally:
        p._thumb_service.close();wait_for(lambda:not p._thumb_service.active)
        p.close();p.deleteLater();QApplication.processEvents()


@pytest.mark.parametrize("same", [True, False])
def test_insert_uses_krita_document_equality(assets, same):
    from unittest.mock import Mock
    from types import SimpleNamespace
    _, module = assets
    pending_doc = SimpleNamespace(identity=1)
    panel = Mock()
    panel._pending_insert = dict(generation=1, mode="paint", center=None, doc=pending_doc, view=None)
    panel._document.return_value = SimpleNamespace(identity=1 if same else 2)
    module.AssetLibraryDocker._finish_insert_rels(panel, (1, [("pic", "path", None, None)], None))
    assert panel._insert_one.call_count == int(same)


def test_u16_asset_keeps_16bit_channels_and_alpha(assets):
    import struct
    from qtcompat import QImage, QColor
    pixels = importlib.import_module('_asset_panel_test.assets.pixels')
    image = QImage(1024, 1, QImage.Format.Format_RGBA64)
    for x in range(1024):
        image.setPixelColor(x, 0, QColor.fromRgba64(x * 64, 1234, 5678, 32001))
    raw, width, height = pixels.paint_bytes(image, 'U16')
    assert (width, height) == (1024, 1)
    assert list(struct.iter_unpack('<4H', raw)) == [(5678, 1234, x * 64, 32001) for x in range(1024)]
