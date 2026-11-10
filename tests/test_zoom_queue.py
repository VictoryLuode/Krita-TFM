from i18n import tr
import threading,time
import test_docker as fixture
from test_grid_menu import entry,finish
from qt_test_binding import QPoint,QPointF,Qt
from qt_test_binding import QWheelEvent
from qt_test_binding import QTest
from qt_test_binding import QLabel
M=fixture.MODULE

def wheel(grid,amount,modifiers=Qt.KeyboardModifier.ControlModifier):
    point=QPointF(40,40)
    fixture.APP.sendEvent(grid.viewport(),QWheelEvent(point,point,QPoint(),QPoint(0,amount),Qt.MouseButton.NoButton,modifiers,Qt.ScrollPhase.NoScrollPhase,False))

def test_ctrl_wheel_resizes_cells_and_reflows_without_requesting_more():
    p=M.ImageSearchDocker(browser=object(),downloader=lambda *a:fixture.ImageSearchTests().png())
    p.resize(640,620);p.show()
    try:
        p.display_results([entry(i) for i in range(20)])
        p.grid.doItemsLayout();fixture.APP.processEvents()
        original=p.grid.gridSize().width();more=[]
        p.grid.more_requested.connect(lambda:more.append(True))
        columns_before=len({p.grid.visualItemRect(p.grid.item(i)).left() for i in range(20)})
        for _ in range(6):wheel(p.grid,120)
        p.grid.doItemsLayout();fixture.APP.processEvents()
        assert p.grid.gridSize().width()>original
        assert all(p.grid.visualItemRect(p.grid.item(i)).width()==p.grid.gridSize().width() for i in range(20))
        assert len({p.grid.visualItemRect(p.grid.item(i)).left() for i in range(20)})<columns_before
        for _ in range(6):wheel(p.grid,-120)
        assert p.grid.gridSize().width()==original
        assert not more,'Ctrl-wheel must not invoke paging'
    finally:finish(p)

def test_idle_footer_descriptions_are_absent_but_errors_remain_visible():
    p=M.ImageSearchDocker(browser=object(),downloader=lambda *a:fixture.ImageSearchTests().png());p.show()
    try:
        p.display_results([entry()]);fixture.APP.processEvents()
        assert p.status.isHidden()
        assert not any('画布内拖入' in label.text() for label in p.findChildren(QLabel))
        p.status.setText('失败：测试错误');fixture.APP.processEvents()
        assert not p.status.isHidden()
        p.status.clear();assert p.status.isHidden()
    finally:finish(p)

def test_similarity_can_be_clicked_while_busy_and_runs_after_current_job():
    class Browser:
        def __init__(self):self.calls=0
        def resolve(self,e):return {'url':'https://i.pinimg.com/originals/1.jpg'}
        def similar(self,data,limit=24):self.calls+=1;return [entry(99)]
        def has_more(self,source):return False
    browser=Browser();gate=threading.Event()
    p=M.ImageSearchDocker(browser=browser,downloader=lambda *a:fixture.ImageSearchTests().png())
    try:
        p.display_results([entry()])
        p.run_job(lambda job:gate.wait(2),lambda result:None,lock_grid=False)
        action=next(a for a in p.build_context_menu(p.grid.item(0)).actions() if a.text()==tr('Find similar images', '查找相似图片'))
        assert action.isEnabled(),'A background image job must not disable similarity'
        action.trigger();assert browser.calls==0
        gate.set();end=time.monotonic()+3
        while time.monotonic()<end and (p.busy or not browser.calls):QTest.qWait(10)
        assert browser.calls==1
        assert p.grid.item(0).data(M.ENTRY_ROLE)['id']=='99'
    finally:gate.set();finish(p)
