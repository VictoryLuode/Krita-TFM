import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).parents[1] / "pykrita" / "quick_image_search" / "search_store.py"
spec = importlib.util.spec_from_file_location("search_store", MODULE)
search_store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(search_store)
SearchStore = search_store.SearchStore


def test_search_deduplicates_by_trimmed_source_and_preserves_original_query(tmp_path):
    store = SearchStore(tmp_path / "db.json", clock=lambda: 10)
    first = store.record_search("google", "  Cat ", "Cat original")
    second = store.record_search("google", "Cat", "")
    assert first["id"] == second["id"]
    assert second["original_query"] == "Cat original"
    assert store.record_search("pinterest", "Cat")["id"] != first["id"]
    assert store.lookup("google", " Cat ")["query"] == "Cat"


def test_favorites_and_recent_rules(tmp_path):
    tick = iter(range(1, 100))
    store = SearchStore(tmp_path / "db.json", history_limit=2, clock=lambda: next(tick))
    a = store.record_search("google", "a")
    b = store.record_search("google", "b")
    fav = store.toggle_favorite("google", "a")
    c = store.record_search("google", "c")
    assert fav["favorite"] is True
    assert [x["query"] for x in store.recent()] == ["c", "b"]
    assert [x["query"] for x in store.favorites()] == ["a"]
    store.remove_history(a["id"])
    assert store.get(a["id"])["favorite"] is True
    store.toggle_favorite("google", "a")
    assert store.get(a["id"]) is None, 'An old unfavorited record follows the recent limit'
    assert c["last_used"] is not None


def test_unsearched_favorite_and_empty_inputs(tmp_path):
    store = SearchStore(tmp_path / "db.json")
    assert store.record_search("google", "  ") is None
    assert store.toggle_favorite("google", "idea")["last_used"] is None
    assert store.recent() == []
    assert store.clear_recent() is None
    assert store.favorites()[0]["query"] == "idea"


@pytest.mark.parametrize("source,query", [("bing", "x"), ("google", None), (None, "x")])
def test_rejects_invalid_types_and_source(tmp_path, source, query):
    store = SearchStore(tmp_path / "db.json")
    with pytest.raises((TypeError, ValueError)):
        store.record_search(source, query)


def test_copy_limit_sort_and_schema(tmp_path):
    t = iter([1, 2, 3])
    path = tmp_path / "db.json"
    store = SearchStore(path, history_limit=1, clock=lambda: next(t))
    row = store.record_search("google", "a")
    row["query"] = "mutated"
    assert store.get(row["id"])["query"] == "a"
    store.record_search("google", "b")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert [r["query"] for r in store.recent()] == ["b"]


def test_atomic_write_failure_rolls_back_memory_and_disk(tmp_path, monkeypatch):
    path = tmp_path / "db.json"
    store = SearchStore(path)
    prior = store.record_search("google", "kept")
    original = os.replace
    def fail(*args):
        raise OSError("simulated replace failure")
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        store.record_search("google", "lost")
    assert store.lookup("google", "lost") is None
    assert json.loads(path.read_text(encoding="utf-8"))["records"][0]["id"] == prior["id"]
    monkeypatch.setattr(os, "replace", original)


def test_corrupt_file_is_backed_up_and_store_recovers(tmp_path):
    path = tmp_path / "db.json"
    path.write_text("{bad", encoding="utf-8")
    store = SearchStore(path)
    assert store.last_error
    assert list(tmp_path.glob("db.json.corrupt*"))
    assert store.record_search("google", "usable")


def test_subprocess_reads_persisted_record(tmp_path):
    path = tmp_path / "db.json"
    store = SearchStore(path)
    row = store.record_search("pinterest", "forest")
    code = "import importlib.util,sys; p=sys.argv[1]; s=importlib.util.spec_from_file_location('m',sys.argv[2]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.SearchStore(p).lookup('pinterest','forest')['id'])"
    output = subprocess.check_output([sys.executable, "-c", code, str(path), str(MODULE)], text=True).strip()
    assert output == row["id"]


def test_first_write_creates_nested_directory_and_favorites_do_not_consume_recent_limit(tmp_path):
    store = SearchStore(tmp_path / 'new' / 'nested' / 'db.json', history_limit=2)
    store.record_search('google', 'a')
    store.record_search('google', 'b')
    store.record_search('google', 'c')
    store.toggle_favorite('google', 'c')
    store.record_search('google', 'd')
    assert [r['query'] for r in store.recent()] == ['d', 'b']
    assert SearchStore(store.path).favorites()[0]['query'] == 'c'


@pytest.mark.parametrize('field,value', [('source', []), ('created_at', float('nan')), ('last_used', True)])
def test_bad_typed_record_is_quarantined(tmp_path, field, value):
    path = tmp_path / 'db.json'
    store = SearchStore(path)
    store.record_search('google', 'a')
    document = json.loads(path.read_text('utf-8'))
    document['records'][0][field] = value
    path.write_text(json.dumps(document), encoding='utf-8')
    recovered = SearchStore(path)
    assert recovered.last_error and not recovered.recent()
    assert list(tmp_path.glob('db.json.corrupt*'))


def test_alias_and_order_persist_without_changing_search_or_recent(tmp_path):
    path = tmp_path / 'db.json'
    tick = iter(range(10, 100))
    store = SearchStore(path, clock=lambda: next(tick))
    a = store.toggle_favorite('google', 'a')
    b = store.toggle_favorite('pinterest', 'b')
    recent = store.record_search('google', 'recent')
    store.set_alias(a['id'], '  Favorite A  ')
    store.reorder_favorites([b['id'], a['id']])
    assert [r['id'] for r in store.favorites()] == [b['id'], a['id']]
    assert store.get(a['id'])['alias'] == 'Favorite A'
    assert store.get(a['id'])['query'] == 'a'
    assert [r['id'] for r in store.recent()] == [recent['id']]
    code = "import importlib.util,sys; s=importlib.util.spec_from_file_location('m',sys.argv[2]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); x=m.SearchStore(sys.argv[1]); print('|'.join(r['id']+':'+r['alias'] for r in x.favorites()))"
    output = subprocess.check_output([sys.executable, '-c', code, str(path), str(MODULE)], text=True).strip()
    assert output == f"{b['id']}:|{a['id']}:Favorite A"


@pytest.mark.parametrize('alias', [None, 1, 'x' * 257])
def test_invalid_alias_rejected_without_changes(tmp_path, alias):
    store = SearchStore(tmp_path / 'db.json')
    row = store.toggle_favorite('google', 'a')
    with pytest.raises((TypeError, ValueError)):
        store.set_alias(row['id'], alias)


def test_alias_requires_existing_favorite_and_order_is_exact_permutation(tmp_path):
    store = SearchStore(tmp_path / 'db.json')
    a = store.toggle_favorite('google', 'a')
    b = store.toggle_favorite('google', 'b')
    store.toggle_favorite('google', 'a')
    with pytest.raises(ValueError):
        store.set_alias(a['id'], 'x')
    for ids in ([b['id'], b['id']], [b['id'], 'missing'], []):
        with pytest.raises(ValueError):
            store.reorder_favorites(ids)


def test_unfavorite_refavorite_moves_to_end(tmp_path):
    store = SearchStore(tmp_path / 'db.json', clock=iter(range(1, 20)).__next__)
    a = store.toggle_favorite('google', 'a')
    store.toggle_favorite('google', 'b')
    store.toggle_favorite('google', 'a')
    a = store.toggle_favorite('google', 'a')
    assert [r['query'] for r in store.favorites()] == ['b', 'a']
    assert a['favorite_order'] == 2


def test_schema1_favorites_migrate_by_original_favorited_time(tmp_path):
    path = tmp_path / 'db.json'
    records = []
    for ident, query, when in [('later', 'later', 20), ('earlier', 'earlier', 10)]:
        records.append(dict(id=ident, source='google', query=query, original_query='orig '+query,
                            favorite=True, created_at=1, favorited_at=when, last_used=None))
    path.write_text(json.dumps({'schema_version': 1, 'records': records}), encoding='utf-8')
    store = SearchStore(path)
    assert not store.last_error
    assert [r['id'] for r in store.favorites()] == ['earlier', 'later']
    assert store.get('later')['original_query'] == 'orig later'
    assert json.loads(path.read_text('utf-8'))['schema_version'] == 2


def test_alias_write_failure_rolls_back(tmp_path, monkeypatch):
    path = tmp_path / 'db.json'
    store = SearchStore(path)
    row = store.toggle_favorite('google', 'a')
    before = path.read_bytes()
    def fail(*args):
        raise OSError('replace failed')
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError):
        store.set_alias(row['id'], 'changed')
    assert store.get(row['id'])['alias'] == ''
    assert path.read_bytes() == before


def _schema1_bytes():
    return json.dumps({'schema_version': 1, 'records': [dict(
        id='favorite', source='google', query='kept', original_query='', favorite=True,
        created_at=1, favorited_at=2, last_used=None)]}).encode('utf-8')


def test_schema1_upgrade_replace_failure_preserves_records_and_original(tmp_path, monkeypatch):
    path = tmp_path / 'db.json'
    raw = _schema1_bytes()
    path.write_bytes(raw)
    def fail(*args):
        raise OSError('simulated replace failure')
    monkeypatch.setattr(os, 'replace', fail)
    store = SearchStore(path)
    assert store.get('favorite')['query'] == 'kept'
    assert path.read_bytes() == raw
    assert not list(tmp_path.glob('db.json.corrupt*'))
    assert '升级' in store.last_error


def test_schema1_upgrade_keeps_readable_unique_backup(tmp_path):
    path = tmp_path / 'db.json'
    raw = _schema1_bytes()
    path.write_bytes(raw)
    store = SearchStore(path)
    backups = list(tmp_path.glob('db.json.schema1-backup-*'))
    assert len(backups) == 1
    assert backups[0].read_bytes() == raw
    assert store.get('favorite')


def test_schema1_backup_failure_blocks_overwrite_and_keeps_records(tmp_path, monkeypatch):
    path = tmp_path / 'db.json'
    raw = _schema1_bytes()
    path.write_bytes(raw)
    original_open = open
    def fail_exclusive(name, mode='r', *args, **kwargs):
        if 'schema1-backup-' in str(name) and mode == 'xb':
            raise OSError('simulated backup failure')
        return original_open(name, mode, *args, **kwargs)
    monkeypatch.setattr('builtins.open', fail_exclusive)
    store = SearchStore(path)
    assert store.get('favorite')['query'] == 'kept'
    assert path.read_bytes() == raw
    assert store._load_blocked
    assert '备份' in store.last_error
    with pytest.raises(OSError):
        store.set_alias('favorite', 'changed')
    assert path.read_bytes() == raw


def test_schema_version_bool_is_rejected_as_corrupt(tmp_path):
    path = tmp_path / 'db.json'
    path.write_text(json.dumps({'schema_version': True, 'records': []}), encoding='utf-8')
    store = SearchStore(path)
    assert store.last_error
    assert list(tmp_path.glob('db.json.corrupt*'))

