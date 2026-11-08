import hashlib
import json
import multiprocessing
import os
import tempfile
import unittest
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "pykrita" / "quick_image_search" / "favorite_cache.py"
spec = __import__("importlib.util", fromlist=["spec_from_file_location"]).spec_from_file_location("favorite_cache", MODULE_PATH)
module = __import__("importlib.util", fromlist=["module_from_spec"]).module_from_spec(spec)
spec.loader.exec_module(module)
FavoriteCache, cache_key = module.FavoriteCache, module.cache_key


class FavoriteCacheTests(unittest.TestCase):
    def setUp(self):
        temporary_root = Path(__file__).resolve().parents[3] / 'tmp' / 'data' / 'krita-cache-unit'
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=str(temporary_root))
        self.root = Path(self.tmp.name) / "cache"
        self.cache = FavoriteCache(self.root, budget_bytes=1_000_000)

    def tearDown(self):
        self.tmp.cleanup()

    def test_key_separates_source_and_trims_query(self):
        self.assertEqual(cache_key("fav", "a", "  cat "), cache_key("fav", "a", "cat"))
        self.assertNotEqual(cache_key("fav", "a", "cat"), cache_key("fav", "b", "cat"))
        self.assertEqual(len(cache_key("fav", "a", "cat")), 64)

    def test_roundtrip_allowlisted_json_and_thumbnail(self):
        key = cache_key("f", "src", "q")
        entries = [{"id": "1", "title": "one", "thumbnail": "https://x/t", "local_path": "/secret"}]
        self.assertTrue(self.cache.save(key, entries, {"https://x/t": b"image-bytes"}, 7, "1", True, 128))
        got = self.cache.load(key)
        self.assertEqual(got["entries"], [{"id": "1", "title": "one", "thumbnail": "https://x/t"}])
        self.assertEqual(got["thumbnails"], {"https://x/t": b"image-bytes"})
        self.assertEqual((got["scroll"], got["selected_id"], got["has_more"], got["tile_size"]), (7, "1", True, 128))
        json.dumps(got["entries"], allow_nan=False)

    def test_reopen_and_subprocess_read(self):
        key = cache_key("f", "src", "q")
        self.cache.save(key, [{"id": "1"}], {}, 0)
        fresh = FavoriteCache(self.root)
        self.assertEqual(fresh.load(key)["entries"], [{"id": "1"}])
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        p = ctx.Process(target=_child_load, args=(str(self.root), key, queue))
        p.start(); p.join(15)
        self.assertEqual(p.exitcode, 0)
        self.assertEqual(queue.get(timeout=2), [{"id": "1"}])

    def test_corrupt_metadata_returns_none_and_bad_blob_is_dropped(self):
        key = cache_key("f", "s", "q")
        self.cache.save(key, [{"id": "1"}], {"u": b"abc"})
        meta = next(self.root.rglob("*.json"))
        data = json.loads(meta.read_text("utf-8"))
        blob = self.root / data["thumbnails"]["u"]
        blob.write_bytes(b"tampered")
        self.assertEqual(self.cache.load(key)["thumbnails"], {})
        meta.write_text("{broken", encoding="utf-8")
        self.assertIsNone(self.cache.load(key))

    def test_invalid_key_rejected_without_path_escape(self):
        before = set(self.root.rglob("*"))
        self.assertFalse(self.cache.save("../x", [], {}))
        self.assertIsNone(self.cache.load("../x"))
        self.cache.clear("../x")
        self.assertEqual(set(self.root.rglob("*")), before)

    def test_clear_snapshot_preserves_shared_blob_until_unreferenced(self):
        k1, k2 = cache_key("1", "s", "q"), cache_key("2", "s", "q")
        self.cache.save(k1, [], {"u": b"same"})
        self.cache.save(k2, [], {"u": b"same"})
        self.cache.clear(k1)
        self.assertEqual(self.cache.load(k2)["thumbnails"]["u"], b"same")
        self.cache.clear(k2)
        self.assertFalse(list(self.root.rglob("*.blob")))

    def test_budget_evicts_least_recently_used_snapshot(self):
        root = Path(self.tmp.name) / "limited"
        cache = FavoriteCache(root, budget_bytes=900)
        keys = [cache_key(str(i), "s", "q") for i in range(3)]
        for i, key in enumerate(keys):
            cache.save(key, [{"id": str(i), "title": "x" * 200}], {})
        self.assertIsNone(cache.load(keys[0]))
        self.assertIsNotNone(cache.load(keys[2]))
        self.assertLessEqual(sum(p.stat().st_size for p in root.rglob("*") if p.is_file()), 900)

    def test_failed_meta_replace_keeps_previous_snapshot(self):
        key = cache_key("f", "s", "q")
        self.cache.save(key, [{"id": "old"}], {})
        original = os.replace
        def fail_meta(src, dst):
            if str(dst).endswith(".json"):
                raise OSError("injected replace failure")
            return original(src, dst)
        os.replace = fail_meta
        try:
            self.assertFalse(self.cache.save(key, [{"id": "new"}], {}))
            self.assertTrue(self.cache.last_error)
        finally:
            os.replace = original
        self.assertEqual(self.cache.load(key)["entries"], [{"id": "old"}])

    def test_invalid_controls_are_rejected_and_other_files_are_not_managed(self):
        key = cache_key('f', 's', 'q')
        self.assertTrue(self.cache.save(key, [{'id': 'old'}], {}))
        self.assertFalse(self.cache.save(key, [{'id': 'new'}], {}, scroll=-1))
        self.assertEqual(self.cache.load(key)['entries'], [{'id': 'old'}])
        unrelated = self.root / 'blobs' / 'personal.blob'
        unrelated.write_bytes(b'not cache data')
        self.cache.clear(key)
        self.assertTrue(unrelated.is_file())

    def test_malformed_metadata_and_overbudget_refresh_preserve_safe_state(self):
        key = cache_key('f', 's', 'q')
        self.cache.save(key, [{'id': 'old'}], {})
        meta = self.root / (key + '.json')
        before = meta.read_bytes()
        self.cache.budget_bytes = len(before) + 10
        self.assertFalse(self.cache.save(key, [{'id': 'new'}], {'u': b'x' * 2000}))
        self.assertEqual(meta.read_bytes(), before)
        doc = json.loads(before)
        doc['entries'] = [False]
        meta.write_text(json.dumps(doc), encoding='utf-8')
        self.assertIsNone(self.cache.load(key))


def _child_load(root, key, queue):
    path = Path(__file__).resolve().parents[1] / "pykrita" / "quick_image_search" / "favorite_cache.py"
    spec = __import__("importlib.util", fromlist=["spec_from_file_location"]).spec_from_file_location("favorite_cache", path)
    module = __import__("importlib.util", fromlist=["module_from_spec"]).module_from_spec(spec)
    spec.loader.exec_module(module)
    queue.put(module.FavoriteCache(root).load(key)["entries"])


if __name__ == "__main__":
    unittest.main()
