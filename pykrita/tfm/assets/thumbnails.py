"""Bounded QImage decoding and byte-budgeted cache; no worker creates a QPixmap."""
from collections import OrderedDict
import os
import threading

from qtcompat import QObject, QRunnable, QThreadPool, QSize, Qt, QImage, QImageReader, pyqtSignal


def file_key(path, edge):
    stat = os.stat(path)
    return os.path.normcase(os.path.abspath(path)), stat.st_size, stat.st_mtime_ns, int(edge)


def decode_image(path, edge):
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    dimensions = (size.width(), size.height()) if size.isValid() else None
    if size.isValid():
        if size.width()*size.height() > 128*1024*1024:
            return QImage(), dimensions, 'Thumbnail exceeds the 128 megapixel decode limit'
        if max(size.width(),size.height()) > edge:
            reader.setScaledSize(size.scaled(edge,edge,Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        return image, dimensions, reader.errorString()
    if max(image.width(),image.height()) > edge:
        image = image.scaled(edge,edge,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
    return image, dimensions, ''


class ImageCache:
    def __init__(self, budget=64*1024*1024):
        self.budget, self.bytes = budget, 0
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            entry = self.entries.get(key)
            if entry is not None:
                self.entries.move_to_end(key)
                return entry[0]

    def put(self, key, result):
        image = result[0]
        cost = max(256, int(image.sizeInBytes()))
        if cost > self.budget:
            return
        with self.lock:
            previous = self.entries.pop(key, None)
            if previous:
                self.bytes -= previous[1]
            self.entries[key] = result, cost
            self.bytes += cost
            while self.bytes > self.budget:
                _, (_, removed) = self.entries.popitem(last=False)
                self.bytes -= removed


class _Signals(QObject):
    finished = pyqtSignal(object)


class _Decode(QRunnable):
    def __init__(self, request, signals, cache, decoder, describe):
        super().__init__()
        self.request, self.signals, self.cache, self.decoder = request, signals, cache, decoder
        self.describe = describe

    def run(self):
        serial, generation, identity, path, edge = self.request
        key, result = None, (QImage(), None, '')
        try:
            key = file_key(path, edge)
            result = self.cache.get(key)
            if result is None:
                result = self.decoder(path, edge)
                if file_key(path, edge) != key:
                    result = QImage(), None, 'Asset changed while its thumbnail was decoded'
                else:
                    self.cache.put(key,result)
        except (OSError, ValueError, RuntimeError) as error:
            result = QImage(), None, str(error)
        try:
            description = self.describe(path) if self.describe else ''
        except (OSError, ValueError, RuntimeError) as error:
            description = str(error)
        self.signals.finished.emit((serial,generation,identity,path,edge,key,(*result,description)))


_POOL = QThreadPool()
_POOL.setMaxThreadCount(2)


class ThumbnailService(QObject):
    ready = pyqtSignal(object)

    def __init__(self, parent=None, *, budget=64*1024*1024, decoder=decode_image, describe=None):
        super().__init__(parent)
        self.cache, self.decoder = ImageCache(budget), decoder
        self.describe = describe
        self.generation, self.serial = 0, 0
        self.closed = False
        self.pending, self.active, self.delivered = OrderedDict(), {}, set()
        self.wanted = set()
        self.signals = _Signals()
        self.signals.finished.connect(self._finished)

    def reset(self):
        self.generation += 1
        self.pending.clear()
        self.delivered.clear()
        self.wanted.clear()
        return self.generation

    def close(self):
        self.closed = True
        self.reset()

    def request(self, entries):
        """Replace queued work with visible-first (identity, path, edge) entries."""
        if self.closed:
            return
        self.wanted = set(entries)
        self.delivered.intersection_update(self.wanted)
        active = {(r[2],r[3],r[4]) for r in self.active.values() if r[1] == self.generation}
        self.pending = OrderedDict((entry,None) for entry in entries
                                   if entry not in active and entry not in self.delivered)
        self._pump()

    def _pump(self):
        while not self.closed and self.pending and len(self.active) < 2:
            (identity,path,edge), _ = self.pending.popitem(last=False)
            self.serial += 1
            request = self.serial,self.generation,identity,path,edge
            self.active[self.serial] = request
            _POOL.start(_Decode(request,self.signals,self.cache,self.decoder,self.describe))

    def _finished(self, payload):
        serial,generation,identity,path,edge,key,result = payload
        self.active.pop(serial,None)
        if not self.closed and generation == self.generation and (identity,path,edge) in self.wanted:
            self.delivered.add((identity,path,edge))
            self.ready.emit((generation,identity,path,edge,key,result))
        self._pump()
