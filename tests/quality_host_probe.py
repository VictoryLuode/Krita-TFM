"""Loaded only as a temporary plugin in the disposable candidate Krita install."""
import json
import os
from pathlib import Path
import struct
import traceback

from krita import Krita, Extension
from PyQt5.QtCore import QTimer, QEventLoop, QByteArray, Qt
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication, QDialog, QDoubleSpinBox, QDialogButtonBox

OUT = Path(os.environ['TFM_HOST_EVIDENCE'])
REPORT = {'environment': 'live Krita 5.3 Qt5, isolated install and resource/profile', 'checks': []}
DOCUMENTS = []


def wait(ms):
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec_()


def check(name, condition, **details):
    REPORT['checks'].append(dict(name=name, status='passed' if condition else 'failed', **details))
    (OUT/'result.json').write_text(json.dumps(REPORT, indent=2), encoding='utf-8')
    if not condition:
        raise AssertionError(name)


def document(depth, width=64, height=48):
    app=Krita.instance()
    doc=app.createDocument(width,height,'TFM quality '+depth,'RGBA',depth,'',120.0)
    DOCUMENTS.append(doc)
    app.activeWindow().addView(doc)
    node=doc.createNode('Fixture','paintlayer');doc.rootNode().addChildNode(node,None);doc.setActiveNode(node)
    pixels=bytearray()
    for y in range(height):
        for x in range(width):
            r,g,b,a=.2+.4*x/width,.25+.25*y/height,.3,.8
            if depth=='U8': pixels.extend(bytes(round(v*255) for v in (b,g,r,a)))
            elif depth=='U16':pixels.extend(struct.pack('<4H',*(round(v*65535) for v in (b,g,r,a))))
            else:pixels.extend(struct.pack('<4'+('e' if depth=='F16' else 'f'),r,g,b,a))
    node.setPixelData(QByteArray(bytes(pixels)),0,0,width,height);doc.refreshProjection();doc.waitForDone()
    wait(150)
    return doc,node


def native_dialog(doc, *, accept=True, value=None, filename='filter-preview.png'):
    state={}
    def handle():
        try:
            dialogs=[w for w in QApplication.topLevelWidgets() if isinstance(w,QDialog) and w.isVisible()
                     and w.findChild(QDialogButtonBox) is not None]
            if not dialogs: raise RuntimeError('native filter dialog did not open')
            dialog=dialogs[-1]
            boxes=dialog.findChildren(QDoubleSpinBox)
            state['values']=[box.value() for box in boxes]
            if value is not None:
                if not boxes:raise RuntimeError('native parameters not found')
                boxes[0].setValue(value)
            wait(650);doc.waitForDone();wait(100)
            state['preview']=bytes(doc.projectionPixelData(0,0,doc.width(),doc.height()))
            dialog.grab().save(str(OUT/filename))
            box=dialog.findChild(QDialogButtonBox)
            box.button(QDialogButtonBox.Ok if accept else QDialogButtonBox.Cancel).click()
        except Exception:
            state['error']=traceback.format_exc()
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget,QDialog):widget.reject()
        finally:state['done']=True
    QTimer.singleShot(600,handle)
    Krita.instance().action('krita_filter_tfm_vibrance').trigger()
    for _ in range(160):
        if state.get('done'):break
        wait(50)
    if 'error' in state:raise RuntimeError(state['error'])
    check('native filter dialog completed',state.get('done',False))
    doc.waitForDone();wait(250)
    return state


def run():
    try:
        app=Krita.instance()
        from tfm.filters.catalog import FILTERS
        import tfm
        check('candidate Python package loaded', str(Path(tfm.__file__).resolve()).startswith(os.environ['TFM_HOST_RESOURCE']))
        missing=[entry['id'] for entry in FILTERS if entry['id'] not in app.filters()]
        check('all 17 native filters registered', not missing, missing=missing)
        for name in ('tfm_edit','tfm_assets','tfm_color_range','tfm_image_search','krita_filter_tfm_vibrance'):
            check('action '+name,app.action(name) is not None)
        for depth in ('U8','U16','F16','F32'):
            doc,node=document(depth)
            original=bytes(node.pixelData(0,0,64,48))
            filter=app.filter('tfm_vibrance');config=filter.configuration();config.setProperty('blend',0.0)
            filter.setConfiguration(config);filter.apply(node,0,0,64,48);doc.waitForDone()
            check(depth+' zero effect',bytes(node.pixelData(0,0,64,48))==original)
            config.setProperty('blend',1.0);config.setProperty('vibrance',40.0);filter.setConfiguration(config)
            check(depth+' apply accepted',filter.apply(node,0,0,64,48));doc.waitForDone()
            check(depth+' applied pixels',bytes(node.pixelData(0,0,64,48))!=original)
        doc,node=document('U8',128,96)
        original=bytes(node.pixelData(0,0,128,96))
        native_dialog(doc,accept=False,value=44,filename='filter-cancel-preview.png')
        check('cancel preview preserves pixels',bytes(node.pixelData(0,0,128,96))==original)
        preview=native_dialog(doc,value=44)
        after=bytes(node.pixelData(0,0,128,96))
        check('dialog applies changed pixels',after!=original)
        check('preview and final projection match',preview['preview']==bytes(doc.projectionPixelData(0,0,128,96)))
        app.action('edit_undo').trigger();doc.waitForDone();wait(150)
        check('native filter undo',bytes(node.pixelData(0,0,128,96))==original)
        app.action('edit_redo').trigger();doc.waitForDone();wait(150)
        check('native filter redo',bytes(node.pixelData(0,0,128,96))==after)
        reopened=native_dialog(doc,accept=False,filename='filter-reopened.png')
        check('last native parameters reopen',44 in reopened.get('values',[]), values=reopened.get('values'))
        from tfm.assets.docker import AssetLibraryDocker
        panel=AssetLibraryDocker();panel.show();wait(150)
        asset=QImage(32,24,QImage.Format_ARGB32);asset.fill(Qt.red)
        path=Path(panel._root)/'Probe';path.mkdir(parents=True,exist_ok=True);asset.save(str(path/'sample.png'))
        panel._reload('Probe');wait(250)
        previous=len(doc.rootNode().childNodes());panel._insert_rels(['Probe/sample.png'],(32,32));doc.waitForDone()
        check('asset inserted into live canvas',len(doc.rootNode().childNodes())==previous+1)
        panel.grab().save(str(OUT/'asset-panel.png'))
        # Provider-independent host integration; remote search provider availability
        # and user-owned browser profiles are deliberately not acceptance claims.
        from quick_image_search.docker import ImageSearchDocker
        from PyQt5.QtCore import QBuffer,QIODevice
        buffer=QBuffer();buffer.open(QIODevice.WriteOnly);asset.save(buffer,'PNG');png=bytes(buffer.data())
        class Backend:
            def search(self,source,query,limit=24):return [dict(source=source,id='probe',title=query,thumbnail='http://local.invalid/fixture')]
            def has_more(self,source):return False
            def close(self,*args,**kwargs):pass
        search=ImageSearchDocker(browser=Backend(),cache_dir=OUT/'search-cache',user_data_dir=OUT/'search-data',downloader=lambda *a:png)
        search.show();search.search_input.setText('candidate fixture');search.search()
        for _ in range(100):
            wait(30)
            if not search.busy and not search.jobs:break
        check('search UI integrates in live host',search.grid.count()==1)
        search.resize(280,480);search.status.setText('Long diagnostic message / 长错误信息 '*10);wait(100)
        search.grab().save(str(OUT/'search-narrow.png'))
        search.shutdown();search.close();panel.close()
        app.activeWindow().qwindow().grab().save(str(OUT/'host.png'))
        REPORT['status']='passed'
    except Exception:
        REPORT['status']='failed';REPORT['error']=traceback.format_exc()
    finally:
        (OUT/'result.json').write_text(json.dumps(REPORT,indent=2),encoding='utf-8')
        for doc in DOCUMENTS:
            doc.setModified(False)
        QTimer.singleShot(300,QApplication.instance().quit)


class Probe(Extension):
    def setup(self):
        self.started=False
        Krita.instance().notifier().windowCreated.connect(self.start)
    def createActions(self,window):pass
    def start(self,*args):
        if not self.started:
            self.started=True;QTimer.singleShot(3500,run)


Krita.instance().addExtension(Probe(Krita.instance()))
