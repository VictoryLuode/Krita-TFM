"""Read one directory at a time; avoid rescanning unchanged expanded branches."""
import os
from . import store


class DirectoryCatalog:
    def __init__(self, root):
        self.root, self.cache = root, {}
        self.order_key, self.order = None, {}

    @staticmethod
    def stamp(path):
        try:
            stat = os.stat(path)
            return stat.st_mtime_ns, stat.st_size
        except OSError:
            return None

    def children(self, parent):
        order_key = self.stamp(os.path.join(self.root, store._ORDER_FILE))
        if order_key != self.order_key:
            self.order_key, self.order = order_key, store._load_order(self.root)
        key = self.stamp(store._folder(self.root,parent)), repr(self.order.get(parent,[]))
        cached = self.cache.get(parent)
        if cached is None or cached[0] != key:
            entries = store.merged_children(self.root,parent,order=self.order)
            self.cache[parent] = key, entries
        return self.cache[parent][1]
