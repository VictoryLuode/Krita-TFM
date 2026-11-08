from pathlib import Path
import tempfile
import time
import unittest
import test_docker as fixture
from qt_test_binding import QPoint, QPointF, Qt
from qt_test_binding import QWheelEvent
from qt_test_binding import QTest

M=fixture.MODULE

def entry(index,title=None):
    return {'id':str(index),'title':title or 'Concrete '+str(index),'thumbnail':'https://example.org/'+str(index)+'.jpg','detail_url':'https://example.org/detail/'+str(index),'source':'google'}
def wait_for(predicate):
    end=time.monotonic()+3
    while time.monotonic()<end:
        QTest.qWait(10)
        if predicate():return True
    return False

class GalleryTests(unittest.TestCase):
    def panel(self,browser):
        png=fixture.ImageSearchTests().png()
        return M.ImageSearchDocker(browser=browser,downloader=lambda *args:png)
    def test_image_only_grid_preserves_name_in_details_metadata(self):
        panel=self.panel(object())
        original=entry(0,'Rough Concrete 2150 - LotPixel | Free Download\nMore marketing text')
        try:
            panel.display_results([original])
            self.assertEqual(panel.grid.item(0).text(),'')
            self.assertEqual(M.image_label(original),'Rough Concrete 2150')
            self.assertFalse(panel.grid.wordWrap())
            self.assertEqual(panel.grid.item(0).data(M.ENTRY_ROLE)['title'],original['title'],'Display cleanup must not alter backend matching metadata')
        finally:panel.shutdown();panel.close()
    def test_more_appends_without_replacing_selection_or_duplicates(self):
        class Browser:
            done=False
            def more(self,source,limit=24):self.done=True;return [entry(0),entry(1)]
            def has_more(self,source):return not self.done
        panel=self.panel(Browser())
        try:
            panel.display_results([entry(0)])
            original=panel.grid.item(0)
            panel.load_more()
            self.assertTrue(wait_for(lambda:panel.grid.count()==2))
            self.assertEqual(panel.grid.item(0),original)
            self.assertFalse(panel.has_more)
        finally:panel.shutdown();panel.close()
    def test_downward_wheel_requests_more_even_before_scrollbar_exists(self):
        panel=self.panel(object())
        triggered=[]
        try:
            panel.grid.resize(350,500)
            panel.display_results([entry(0)])
            panel.grid.more_requested.connect(lambda:triggered.append(True))
            point=QPointF(40,40)
            event=QWheelEvent(point,point,QPoint(),QPoint(0,-120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
            fixture.APP.sendEvent(panel.grid.viewport(),event)
            self.assertTrue(triggered,'A small first batch cannot be scrolled to request the next batch')
        finally:panel.shutdown();panel.close()
    def test_own_file_drag_carries_a_scoped_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            path,_,_=M.prepare_image(fixture.ImageSearchTests().png(),Path(directory))
            self.assertTrue(M.file_drag_mime(path).hasFormat('application/x-krita-quick-image-search'))

if __name__=='__main__':unittest.main(verbosity=2)
