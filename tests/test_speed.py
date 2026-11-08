import threading
import time
import unittest
import tempfile
from qt_test_binding import QTest
import test_docker as fixture

M = fixture.MODULE

def wait_for(predicate, timeout=3):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        QTest.qWait(10)
        if predicate(): return True
    return False


def entries(count):
    return [{'id':str(i),'source':'google','title':'Concrete '+str(i),'thumbnail':'https://example.org/thumb/'+str(i),'detail_url':'https://example.org/detail/'+str(i)} for i in range(count)]


class SpeedTests(unittest.TestCase):
    def test_thumbnails_download_concurrently_with_a_bounded_pool(self):
        png=fixture.ImageSearchTests().png()
        lock=threading.Lock()
        stats={'active':0,'peak':0,'finished':0}
        def download(*args):
            with lock:
                stats['active']+=1
                stats['peak']=max(stats['peak'],stats['active'])
            time.sleep(.08)
            with lock:
                stats['active']-=1
                stats['finished']+=1
            return png
        panel=M.ImageSearchDocker(browser=object(),downloader=download)
        try:
            panel.display_results(entries(6))
            self.assertTrue(wait_for(lambda:stats['finished']==6))
            self.assertGreaterEqual(stats['peak'],3,'A slow thumbnail still blocks all following thumbnails')
            self.assertLessEqual(stats['peak'],4,'Thumbnail concurrency must remain bounded')
        finally:
            panel.shutdown()
            panel.close()

    def test_repeated_results_reuse_thumbnail_bytes(self):
        png=fixture.ImageSearchTests().png()
        downloaded=[]
        def download(url,*args):
            downloaded.append(url)
            return png
        panel=M.ImageSearchDocker(browser=object(),downloader=download)
        try:
            for _ in range(2):
                panel.display_results(entries(4))
                self.assertTrue(wait_for(lambda:all(not panel.grid.item(i).icon().isNull() for i in range(4))))
                panel.shutdown()
            self.assertEqual(len(downloaded),4,'The same thumbnails were downloaded again')
        finally:
            panel.shutdown()
            panel.close()

    def test_large_image_loading_keeps_grid_usable_and_honors_latest_selection(self):
        png=fixture.ImageSearchTests().png()
        started=threading.Event()
        release=threading.Event()
        resolved=[]
        class Browser:
            def resolve(self, entry):
                resolved.append(entry['id'])
                return {'url':'https://example.org/large/'+entry['id'],'referer':entry['detail_url']}
        def download(url,*args):
            if url.endswith('/large/0'):
                started.set()
                release.wait(3)
            return png
        with tempfile.TemporaryDirectory() as directory:
            panel=M.ImageSearchDocker(browser=Browser(),cache_dir=directory,downloader=download)
            try:
                panel.display_results(entries(2))
                panel.grid.setCurrentRow(0)
                self.assertTrue(wait_for(started.is_set))
                self.assertTrue(panel.grid.isEnabled(),'Loading one full image locks the entire grid')
                panel.grid.setCurrentRow(1)
                release.set()
                self.assertTrue(wait_for(lambda:bool(panel.grid.item(1).data(M.PATH_ROLE))))
                self.assertEqual(resolved,['0','1'])
                self.assertEqual(panel.grid.currentRow(),1)
            finally:
                release.set()
                panel.shutdown()
                panel.close()

    def test_repeated_image_reuses_prepared_file(self):
        png=fixture.ImageSearchTests().png()
        resolved=[]
        large_downloads=[]
        class Browser:
            def resolve(self, entry):
                resolved.append(entry['id'])
                return {'url':'https://example.org/large/'+entry['id'],'referer':entry['detail_url']}
        def download(url,*args):
            if '/large/' in url: large_downloads.append(url)
            return png
        with tempfile.TemporaryDirectory() as directory:
            panel=M.ImageSearchDocker(browser=Browser(),cache_dir=directory,downloader=download)
            try:
                for _ in range(2):
                    panel.display_results(entries(1))
                    panel.grid.setCurrentRow(0)
                    self.assertTrue(wait_for(lambda:bool(panel.grid.item(0).data(M.PATH_ROLE))))
                    panel.shutdown()
                self.assertEqual(len(resolved),1,'The same image detail page was opened again')
                self.assertEqual(len(large_downloads),1,'The prepared large image was downloaded again')
            finally:
                panel.shutdown()
                panel.close()

if __name__=='__main__':
    unittest.main(verbosity=2)
