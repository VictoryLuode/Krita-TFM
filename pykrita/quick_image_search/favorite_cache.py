"""Safe, standard-library disk cache for favorite-search snapshots."""
import hashlib
import json
import math
import uuid
import os
import re
import threading
import time
from pathlib import Path

_KEY = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = {"source", "id", "title", "thumbnail", "detail_url", "image_url", "website_url", "source_url", "width", "height", "description", "image_name"}
_MAX_META = 8 * 1024 * 1024
_MAX_ENTRIES = 10000
_MAX_BLOB = 20 * 1024 * 1024


def cache_key(favorite_id, source, query):
    raw = json.dumps([str(favorite_id), str(source), str(query).strip()], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_document(doc):
    if not isinstance(doc, dict) or type(doc.get('version')) is not int or doc['version'] != 1:
        raise ValueError('Invalid snapshot version')
    if not isinstance(doc.get('entries'), list) or len(doc['entries']) > _MAX_ENTRIES:
        raise ValueError('Invalid entries')
    for entry in doc['entries']:
        if not isinstance(entry, dict) or not set(entry).issubset(_FIELDS):
            raise ValueError('Invalid entry')
        for field, value in entry.items():
            if field in ('width', 'height'):
                if type(value) is not int or not 0 <= value <= 100000:
                    raise ValueError('Invalid dimensions')
            elif field == 'id' and type(value) is int:
                if not 0 <= value < 10 ** 30:
                    raise ValueError('Invalid id')
            elif not isinstance(value, str) or len(value) > 65536:
                raise ValueError('Invalid image text')
        if 'source' in entry and entry['source'] not in ('pinterest', 'google'):
            raise ValueError('Invalid image source')
    if type(doc.get('scroll')) is not int or not 0 <= doc['scroll'] <= 2147483647:
        raise ValueError('Invalid scroll position')
    if type(doc.get('tile_size')) is not int or not 80 <= doc['tile_size'] <= 320:
        raise ValueError('Invalid tile size')
    if type(doc.get('has_more')) is not bool or not isinstance(doc.get('selected_id'), str) or len(doc['selected_id']) > 8192:
        raise ValueError('Invalid selection')
    if type(doc.get('saved_at')) not in (int, float) or not math.isfinite(doc['saved_at']):
        raise ValueError('Invalid timestamp')
    if not isinstance(doc.get('thumbnails'), dict) or len(doc['thumbnails']) > _MAX_ENTRIES:
        raise ValueError('Invalid thumbnails')
    for url, relative in doc['thumbnails'].items():
        if not isinstance(url, str) or len(url) > 8192 or not isinstance(relative, str) or not re.fullmatch(r'blobs/[0-9a-f]{64}\.blob', relative):
            raise ValueError('Invalid thumbnail path')


def linked(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


class FavoriteCache:
    def __init__(self, root, budget_bytes=200 * 1024 * 1024):
        self.root = Path(root)
        self.budget_bytes = max(0, int(budget_bytes))
        self._lock = threading.RLock()
        self.last_error = ""

    def _safe_root(self):
        self.root.mkdir(parents=True, exist_ok=True)
        if linked(self.root):
            raise OSError("cache root may not be a symlink")

    def _meta(self, key):
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            return None
        return self.root / (key + ".json")

    def _snapshots(self):
        if not self.root.exists() or linked(self.root):
            return []
        return [p for p in self.root.glob("[0-9a-f]" * 64 + ".json") if p.is_file() and not p.is_symlink()]

    def _cleanup_blobs(self):
        refs = set()
        for p in self._snapshots():
            try:
                if p.stat().st_size <= _MAX_META:
                    d = json.loads(p.read_text(encoding="utf-8"))
                    refs.update(v for v in d.get("thumbnails", {}).values() if isinstance(v, str) and re.fullmatch(r"blobs/[0-9a-f]{64}\.blob", v))
            except Exception:
                continue
        bdir = self.root / "blobs"
        if bdir.is_dir() and not linked(bdir):
            for p in bdir.glob("*.blob"):
                if _KEY.fullmatch(p.stem) and not linked(p) and "blobs/" + p.name not in refs:
                    try: p.unlink()
                    except OSError: pass

    def _managed_size(self):
        paths = self._snapshots()
        directory = self.root / 'blobs'
        if directory.is_dir() and not linked(directory):
            paths += [p for p in directory.glob('*.blob') if _KEY.fullmatch(p.stem) and not linked(p) and p.is_file()]
        return sum(p.stat().st_size for p in paths)

    def _enforce_budget(self):
        snaps = self._snapshots()
        def rank(p):
            try: return p.stat().st_mtime_ns
            except OSError: return 0
        total = sum(p.stat().st_size for p in snaps)
        for p in sorted(snaps, key=rank):
            if total <= self.budget_bytes: break
            size = p.stat().st_size
            p.unlink()
            total -= size
        self._cleanup_blobs()
        size = self._managed_size()
        # Blob cleanup and metadata-only accounting; remove further oldest snapshots as needed.
        for p in sorted(self._snapshots(), key=rank):
            if size <= self.budget_bytes: break
            n = p.stat().st_size
            p.unlink(); size -= n; self._cleanup_blobs()
            size = self._managed_size()

    def save(self, key, entries, thumbnails, scroll=0, selected_id="", has_more=False, tile_size=144):
        with self._lock:
            self.last_error = ""
            temporary_files = []
            try:
                self._safe_root()
                path = self._meta(key)
                if path is None: raise ValueError("invalid cache key")
                if not isinstance(entries, (list, tuple)) or len(entries) > _MAX_ENTRIES: raise ValueError("invalid entries")
                if not isinstance(thumbnails, dict): raise ValueError("invalid thumbnails")
                clean = []
                for entry in entries:
                    if not isinstance(entry, dict): raise ValueError("invalid entry")
                    clean.append({k: v for k, v in entry.items() if k in _FIELDS and v is not None})
                proposed_refs = {}
                blob_sizes = {}
                for url, data in thumbnails.items():
                    if not isinstance(url, str) or not isinstance(data, bytes) or len(data) > _MAX_BLOB:
                        raise ValueError('Invalid thumbnail')
                    digest = hashlib.sha256(data).hexdigest()
                    proposed_refs[url] = 'blobs/' + digest + '.blob'
                    blob_sizes[digest] = len(data)
                proposed = dict(version=1, entries=clean, thumbnails=proposed_refs, scroll=scroll,
                                selected_id=selected_id, has_more=has_more, tile_size=tile_size, saved_at=time.time())
                validate_document(proposed)
                proposed_bytes = json.dumps(proposed, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
                if len(proposed_bytes) > _MAX_META or len(proposed_bytes) + sum(blob_sizes.values()) > self.budget_bytes:
                    raise ValueError('Snapshot exceeds cache capacity; old snapshot retained')
                refs = {}
                bdir = self.root / "blobs"
                bdir.mkdir(exist_ok=True)
                if linked(bdir) or linked(path): raise ValueError("cache directory or file is linked")
                for url, data in thumbnails.items():
                    if not isinstance(url, str) or not isinstance(data, bytes) or len(data) > _MAX_BLOB: raise ValueError("invalid thumbnail")
                    digest = hashlib.sha256(data).hexdigest()
                    dest = bdir / (digest + ".blob")
                    if linked(dest): raise ValueError('Linked cache blob')
                    if not dest.exists() or dest.stat().st_size > _MAX_BLOB or hashlib.sha256(dest.read_bytes()).hexdigest() != digest:
                        tmp = bdir / (digest + ".tmp-" + uuid.uuid4().hex)
                        temporary_files.append(tmp)
                        with open(tmp, "xb") as f: f.write(data); f.flush(); os.fsync(f.fileno())
                        os.replace(tmp, dest)
                    refs[url] = "blobs/" + digest + ".blob"
                doc = {"version": 1, "entries": clean, "thumbnails": refs, "scroll": int(scroll), "selected_id": str(selected_id), "has_more": bool(has_more), "tile_size": int(tile_size), "saved_at": time.time()}
                raw = json.dumps(doc, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
                if len(raw) > _MAX_META: raise ValueError("metadata too large")
                tmp = self.root / (key + ".tmp-" + uuid.uuid4().hex)
                temporary_files.append(tmp)
                with open(tmp, "xb") as f: f.write(raw); f.flush(); os.fsync(f.fileno())
                os.replace(tmp, path)
                self._enforce_budget()
                return path.exists()
            except Exception as exc:
                self.last_error = str(exc)
                try:
                    for p in temporary_files:
                        if p.exists(): p.unlink()
                except OSError: pass
                return False

    def load(self, key):
        with self._lock:
            self.last_error = ""
            try:
                path = self._meta(key)
                if path is None or linked(self.root) or linked(path) or not path.is_file(): return None
                if path.stat().st_size > _MAX_META: return None
                doc = json.loads(path.read_text(encoding="utf-8"))
                validate_document(doc)
                thumbs = {}
                for url, rel in doc.get("thumbnails", {}).items():
                    if not isinstance(url, str) or not isinstance(rel, str) or not re.fullmatch(r"blobs/[0-9a-f]{64}\.blob", rel): continue
                    blob = self.root / rel
                    if linked(self.root / 'blobs') or linked(blob) or not blob.is_file() or blob.stat().st_size > _MAX_BLOB: continue
                    data = blob.read_bytes()
                    if hashlib.sha256(data).hexdigest() == Path(rel).stem: thumbs[url] = data
                try: os.utime(path, None)
                except OSError: pass
                return {"entries": doc["entries"], "thumbnails": thumbs, "scroll": doc["scroll"], "selected_id": doc["selected_id"], "has_more": doc["has_more"], "tile_size": doc["tile_size"], "saved_at": doc["saved_at"]}
            except Exception as exc:
                self.last_error = str(exc)
                return None

    def clear(self, key):
        with self._lock:
            path = self._meta(key)
            if path is None: return
            try:
                if linked(self.root): return
                if path.is_file() and not linked(path): path.unlink()
                self._cleanup_blobs()
            except OSError as exc:
                self.last_error = str(exc)
