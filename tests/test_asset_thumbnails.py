"""Exercise production decoding, cache invalidation and stale result handling."""
import importlib.util
import os
from pathlib import Path
import threading
import time

from qt_test_binding import QApplication, QImage, Qt, QTest, QThread

SPEC = importlib.util.spec_from_file_location('asset_thumbnails_test',Path(__file__).parents[1]/'pykrita/tfm/assets/thumbnails.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
APP = QApplication.instance() or QApplication([])


def wait_for(predicate, seconds=3):
    deadline = time.monotonic()+seconds
    while not predicate() and time.monotonic()<deadline:
        QTest.qWait(5)
    assert predicate()


def save(path, size=64, color=Qt.GlobalColor.red):
    image = QImage(size,size,QImage.Format.Format_ARGB32)
    image.fill(color)
    assert image.save(str(path),'PNG')


def test_real_decode_and_signature_invalidation(tmp_path):
    path = tmp_path/'asset.png'
    save(path)
    calls, results = [], []
    def decode(path,edge):
        assert QThread.currentThread() != APP.thread()
        calls.append((path,edge))
        return M.decode_image(path,edge)
    service = M.ThumbnailService(decoder=decode)
    service.ready.connect(results.append)
    def request(edge):
        previous=len(results)
        service.reset()
        service.request([('asset',str(path),edge)])
        wait_for(lambda:len(results)>previous)
    request(32)
    assert results[-1][-1][0].size().width()==32 and len(calls)==1
    request(32)
    assert len(calls)==1
    request(48)
    assert len(calls)==2
    save(path,96,Qt.GlobalColor.blue)
    request(32)
    assert len(calls)==3 and results[-1][-1][0].pixelColor(0,0).blue()==255
    service.close()


def test_generation_and_visible_first_queue_are_bounded(tmp_path):
    paths=[]
    for i in range(12):
        path=tmp_path/f'{i}.png'; save(path); paths.append(str(path))
    gate=threading.Event()
    calls,results=[],[]
    def decode(path,edge):
        calls.append(path)
        gate.wait(2)
        return M.decode_image(path,edge)
    service=M.ThumbnailService(decoder=decode)
    service.ready.connect(results.append)
    service.request([(str(i),p,32) for i,p in enumerate(paths[:6])])
    wait_for(lambda:len(calls)==2)
    generation=service.reset()
    service.request([(str(i),paths[i],32) for i in (10,11,9)])
    gate.set()
    wait_for(lambda:len(results)==3)
    assert calls[:2]==paths[:2] and set(calls[2:4])=={paths[10],paths[11]}
    assert all(item[0]==generation for item in results)
    assert paths[2] not in calls
    service.close()


def test_cache_has_byte_budget_and_bad_images_are_diagnostic(tmp_path):
    image=QImage(64,64,QImage.Format.Format_ARGB32)
    cache=M.ImageCache(budget=2*image.sizeInBytes())
    for i in range(10):
        cache.put((str(i),), (image,None,''))
    assert len(cache.entries)==2 and cache.bytes<=cache.budget
    assert cache.get(('0',)) is None and cache.get(('9',)) is not None
    bad=tmp_path/'broken.png'; bad.write_bytes(b'not a png')
    result=M.decode_image(str(bad),32)
    assert result[0].isNull() and result[2]
