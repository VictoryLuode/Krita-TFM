"""Offline real-Qt asset panel benchmark with a disposable 1000-file fixture.

Run each --source variant in its own process. Cold means empty application cache;
the OS file cache is not forcibly cleared. No Krita user resources are touched.
"""
import argparse
import importlib
import json
import os
from pathlib import Path
import statistics
import sys
import time
import types

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'pykrita'))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt5.QtWidgets import QApplication,QDockWidget
from PyQt5.QtCore import Qt,QTimer,QEvent,QCoreApplication
from PyQt5.QtGui import QImage,QColor
from benchmark_gpu_worker import memory,summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--generate',action='store_true')
    args=parser.parse_args()
    app=QApplication([])
    root=args.data.resolve()
    if args.generate:
        root.mkdir(parents=True,exist_ok=True)
        for category in ('A','B'):
            folder=root/category;folder.mkdir(exist_ok=True)
            for i in range(500):
                side=4096 if i==0 else 1024 if i%50==0 else 128+(i%5)*96
                image=QImage(side,side*3//4,QImage.Format_ARGB32)
                image.fill(QColor.fromHsv(i%360,180,220))
                suffix='jpg' if i%2 else 'png'
                assert image.save(str(folder/f'{i:04}.{suffix}'))
            (folder/'broken.png').write_bytes(b'broken fixture')
            for i in range(20):
                (folder/f'folder{i}'/'nested'/'deeper').mkdir(parents=True,exist_ok=True)
    name='_asset_benchmark'
    package=types.ModuleType(name);package.__path__=[str(args.source.resolve()/'pykrita/tfm')]
    sys.modules[name]=package
    manager=types.ModuleType(name+'.manager')
    manager.assets_directory=lambda:str(root)
    manager.assets_enabled=lambda:True
    sys.modules[manager.__name__]=manager
    settings={('TFM','assets_last_folder'):'A'}
    host=types.SimpleNamespace(readSetting=lambda g,k,d='':settings.get((g,k),d),
                              writeSetting=lambda g,k,v:settings.__setitem__((g,k),v))
    krita=types.ModuleType('krita');krita.DockWidget=QDockWidget
    krita.InfoObject=krita.Selection=type('Stub',(),{})
    krita.Krita=types.SimpleNamespace(instance=lambda:host)
    sys.modules['krita']=krita
    module=importlib.import_module(name+'.assets.docker')
    timer=QTimer();timer.setInterval(10)
    last=[time.perf_counter()];gaps=[]
    def beat():
        now=time.perf_counter();gaps.append((now-last[0])*1000);last[0]=now
    timer.timeout.connect(beat);timer.start()
    started=time.perf_counter()
    panel=module.AssetLibraryDocker();panel.resize(800,600);panel.show()
    construction=(time.perf_counter()-started)*1000
    timings=[]
    for repeat in range(10):
        folder='A' if repeat%2==0 else 'B'
        started=time.perf_counter()
        panel._reload(folder)
        deadline=time.perf_counter()+20
        while True:
            app.processEvents()
            viewport=panel.grid.viewport().rect()
            visible=[panel.grid.item(i) for i in range(panel.grid.count())
                     if panel.grid.visualItemRect(panel.grid.item(i)).intersects(viewport)]
            if visible and all(not item.icon().isNull() for item in visible):break
            if time.perf_counter()>deadline:raise RuntimeError('Visible asset thumbnails did not load')
            time.sleep(.002)
        timings.append((time.perf_counter()-started)*1000)
        # Let queued work settle before the next switch, without counting hidden
        # decoding as time-to-visible. The heartbeat still records responsiveness.
        settle=time.perf_counter()+.2
        while time.perf_counter()<settle:app.processEvents();time.sleep(.002)
    timer.stop()
    current=types.SimpleNamespace(_handle=__import__('ctypes').windll.kernel32.GetCurrentProcess())
    record={'fixture':'1000 mixed PNG/JPEG + 2 corrupt files; 4K large images; 120 nested directories',
            'cold_definition':'new application cache; OS cache not purged',
            'construction_ms':construction,'first_folder_ms':timings[0],
            'switch_ms':summary(timings[1:]),'heartbeat_gap_ms':summary(gaps),
            'peak_working_set_bytes':memory(current)}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps({k:v if not isinstance(v,dict) else {n:x for n,x in v.items() if n!='samples'} for k,v in record.items()},indent=2))
    if hasattr(panel,'_thumb_service'):
        panel._thumb_service.close()
        deadline=time.monotonic()+3
        while panel._thumb_service.active and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
    panel.close();panel.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    app.processEvents()


if __name__=='__main__':main()
