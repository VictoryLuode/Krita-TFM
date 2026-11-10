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
