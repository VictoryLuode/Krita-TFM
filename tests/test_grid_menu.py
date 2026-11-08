import time
from unittest.mock import patch
import test_docker as fixture
from qt_test_binding import QSize,QPoint
from qt_test_binding import QColor,QImage
from qt_test_binding import QTest

M=fixture.MODULE

def entry(index=1):
    return {'id':str(index),'source':'pinterest','title':'Concrete '+str(index),'thumbnail':'https://i.pinimg.com/236x/'+str(index)+'.jpg','detail_url':'https://www.pinterest.com/pin/'+str(index)+'/','website_url':'https://example.org/material/'+str(index),'width':1200,'height':800}

def panel():
    return M.ImageSearchDocker(browser=object(),downloader=lambda *a:fixture.ImageSearchTests().png())

def finish(p):
    p.shutdown();p.close();p.deleteLater()

def test_default_pinterest_and_image_only_grid_without_name_controls():
    p=panel()
    try:
        assert p.source.currentData()=='pinterest'
        assert not hasattr(p,'names_toggle'),'Remove the name checkbox rather than hiding it'
        assert not hasattr(p.grid,'show_names'),'Remove the obsolete caption mode'
        p.display_results([entry()])
        assert p.grid.item(0).text()==''
        assert p.grid.item(0).toolTip()==''
        assert p.grid.item(0).data(M.ENTRY_ROLE)['title']=='Concrete 1'
    finally:finish(p)

def test_all_cells_keep_equal_geometry_before_and_after_images():
    p=panel();p.resize(640,620);p.show()
    try:
        p.display_results([entry(i) for i in range(8)])
        p.grid.doItemsLayout();fixture.APP.processEvents()
        before=[p.grid.visualItemRect(p.grid.item(i)) for i in range(8)]
        assert len({(r.width(),r.height()) for r in before})==1
        for i in range(8):
            image=QImage(30+i*40,250-i*20,QImage.Format.Format_RGB32);image.fill(QColor('#556677'))
            from qt_test_binding import QBuffer,QIODevice
            buf=QBuffer();buf.open(QIODevice.OpenModeFlag.WriteOnly);image.save(buf,'PNG')
            p.set_thumbnail((p.generation,i,bytes(buf.data())))
        p.grid.doItemsLayout();fixture.APP.processEvents()
        assert before==[p.grid.visualItemRect(p.grid.item(i)) for i in range(8)]
    finally:finish(p)

def test_context_actions_use_clicked_not_previously_selected_image():
    p=panel()
    try:
        p.display_results([entry(1),entry(2)])
        menu=p.build_context_menu(p.grid.item(1))
        actions={a.text():a for a in menu.actions() if not a.isSeparator()}
        assert set(actions)=={'图片详细信息','打开原网址','查找相似图片'}
        with patch.object(M.QDesktopServices,'openUrl',return_value=True) as open_url:
            actions['打开原网址'].trigger()
        assert open_url.call_args.args[0].toString()=='https://example.org/material/2'
        actions['图片详细信息'].trigger()
        assert p.details_dialog.isVisible()
        from qt_test_binding import QPlainTextEdit
        text=p.details_dialog.findChild(QPlainTextEdit).toPlainText()
        assert 'Concrete 2' in text and '1200' in text
        assert p.build_context_menu(None) is None
        p.details_dialog.close()
    finally:finish(p)


def test_delegate_really_paints_the_image_not_only_its_cell():
    from qt_test_binding import QRect,QBuffer,QIODevice
    from qt_test_binding import QPainter
    from qt_test_binding import QStyleOptionViewItem
    p=panel()
    try:
        p.display_results([entry()])
        image=QImage(240,240,QImage.Format.Format_RGB32);image.fill(QColor('#ff00ff'))
        buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly);image.save(buffer,'PNG')
        p.set_thumbnail((p.generation,0,bytes(buffer.data())))
        rendered=QImage(144,144,QImage.Format.Format_RGB32);rendered.fill(QColor('white'))
        painter=QPainter(rendered)
        option=QStyleOptionViewItem();option.rect=QRect(0,0,144,144);option.widget=p.grid
        p.grid.itemDelegate().paint(painter,option,p.grid.model().index(0,0))
        painter.end()
        assert rendered.pixelColor(72,72)==QColor('#ff00ff')
        assert rendered.pixelColor(72,132)==QColor('#ff00ff'),'Bottom of tile must remain image, not a caption or reserved strip'
    finally:finish(p)


def test_grid_and_controls_fit_narrow_default_and_wide_panels():
    p=panel();p.show()
    try:
        p.display_results([entry(i) for i in range(12)])
        for width in (332,640,900):
            p.resize(width,620);fixture.APP.processEvents();p.grid.doItemsLayout()
            rects=[p.grid.visualItemRect(p.grid.item(i)) for i in range(12)]
            assert all(r.width()==144 and r.height()==144 for r in rects)
            assert all(r.left()>=0 and r.right()<p.grid.viewport().width() for r in rects)
            assert p.favorite_tabs.geometry().right() < p.status.geometry().left()
            assert p.search_input.width()>=64
    finally:finish(p)


def test_context_similar_uploads_clicked_image_and_replaces_results():
    class Browser:
        def __init__(self):self.resolved=[];self.uploaded=[]
        def resolve(self,e):self.resolved.append(e['id']);return {'url':'https://i.pinimg.com/originals/'+e['id']+'.jpg'}
        def similar(self,data,limit=24):self.uploaded.append(data);return [entry(99)]
        def has_more(self,source):return True
        def more(self,source,limit=24):return [entry(100)]
    browser=Browser()
    p=M.ImageSearchDocker(browser=browser,downloader=lambda *a:fixture.ImageSearchTests().png())
    try:
        assert hasattr(p,'find_similar'),'Similarity action is not implemented'
        p.display_results([entry(1),entry(2)])
        menu=p.build_context_menu(p.grid.item(1))
        next(a for a in menu.actions() if a.text()=='查找相似图片').trigger()
        deadline=time.monotonic()+3
        while p.busy and time.monotonic()<deadline:QTest.qWait(10)
        assert not p.busy,p.status.text()
        assert browser.resolved==['2']
        assert browser.uploaded and browser.uploaded[0].startswith(b'\xff\xd8')
        assert p.grid.item(0).data(M.ENTRY_ROLE)['id']=='99'
        assert p.source.currentData()=='pinterest'
        assert p.has_more
    finally:finish(p)
