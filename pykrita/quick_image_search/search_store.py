"""Pure standard-library persistent search history and favorites store."""
import copy
import json
import math
import os
import tempfile
import time
import uuid

_SCHEMA_VERSION = 2
_MAX_FILE_BYTES = 5 * 1024 * 1024
_MAX_RECORDS = 10000
_MAX_QUERY = 4096
_SOURCES = {"pinterest", "google"}
_FIELDS = {"id", "source", "query", "original_query", "favorite", "created_at", "favorited_at", "last_used", "alias", "favorite_order"}
_LEGACY_FIELDS = _FIELDS - {"alias", "favorite_order"}


class SearchStore:
    def __init__(self, path, history_limit=50, clock=time.time):
        if not isinstance(history_limit, int) or isinstance(history_limit, bool) or history_limit < 0:
            raise ValueError("history_limit must be a non-negative integer")
        self.path = os.fspath(path)
        self.history_limit = history_limit
        self.clock = clock
        self.last_error = ""
        self._load_blocked = False
        self._records = []
        self._load()

    @staticmethod
    def _validate(source, query):
        if not isinstance(source, str) or not isinstance(query, str):
            raise TypeError("source and query must be strings")
        if source not in _SOURCES:
            raise ValueError("source must be pinterest or google")
        query = query.strip()
        if len(query) > _MAX_QUERY:
            raise ValueError("query too long")
        return query

    def _load(self):
        try:
            with open(self.path, "rb") as f:
                raw = f.read(_MAX_FILE_BYTES + 1)
            if len(raw) > _MAX_FILE_BYTES:
                raise ValueError("store file exceeds size limit")
            doc = json.loads(raw.decode("utf-8"))
            version = doc.get("schema_version") if isinstance(doc, dict) else None
            if (not isinstance(doc, dict) or type(version) is not int or version not in (1, _SCHEMA_VERSION)
                    or not isinstance(doc.get("records"), list)):
                raise ValueError("invalid store schema")
            legacy = version == 1
            if len(doc["records"]) > _MAX_RECORDS:
                raise ValueError("too many records")
            seen = set()
            queries = set()
            records = []
            for item in doc["records"]:
                if not isinstance(item, dict) or set(item) != (_LEGACY_FIELDS if legacy else _FIELDS):
                    raise ValueError("invalid record fields")
                r = {k: item[k] for k in (_LEGACY_FIELDS if legacy else _FIELDS)}
                if legacy:
                    r["alias"] = ""
                    r["favorite_order"] = None
                if (not isinstance(r["id"], str) or not r["id"] or r["id"] in seen or
                    not isinstance(r["source"], str) or r["source"] not in _SOURCES or
                    not isinstance(r["query"], str) or not r["query"].strip() or len(r["query"]) > _MAX_QUERY or
                    r["query"] != r["query"].strip() or (r["source"], r["query"]) in queries or
                    not isinstance(r["original_query"], str) or len(r["original_query"]) > _MAX_QUERY or not isinstance(r["favorite"], bool) or
                    not self._valid_time(r["created_at"]) or not self._valid_time(r["favorited_at"], nullable=True) or
                    not self._valid_time(r["last_used"], nullable=True) or
                    (r["favorite"] != (r["favorited_at"] is not None)) or
                    not isinstance(r["alias"], str) or len(r["alias"]) > 256 or r["alias"] != r["alias"].strip() or
                    (not legacy and r["favorite"] and (not isinstance(r["favorite_order"], int) or isinstance(r["favorite_order"], bool) or r["favorite_order"] < 0)) or
                    (not legacy and not r["favorite"] and r["favorite_order"] is not None)):
                    raise ValueError("invalid record data")
                seen.add(r["id"])
                queries.add((r["source"], r["query"]))
                records.append(r)
            if legacy:
                for order, r in enumerate(sorted((x for x in records if x["favorite"]), key=lambda x: x["favorited_at"])):
                    r["favorite_order"] = order
            orders = [r["favorite_order"] for r in records if r["favorite"]]
            if len(set(orders)) != len(orders):
                raise ValueError("duplicate favorite order")
            self._records = records
            self._prune_recent()
            if legacy:
                try:
                    self._backup_schema1(raw)
                except Exception as backup_error:
                    self._load_blocked = True
                    self.last_error = 'schema1 格式升级未完成：原文件备份失败，已禁止覆盖：' + str(backup_error)
                    return
                try:
                    self._save()
                except Exception as migration_error:
                    self.last_error = 'schema1 格式升级未保存，原文件及有效记录已保留：' + str(migration_error)
        except FileNotFoundError:
            pass
        except Exception as exc:
            self.last_error = str(exc)
            try:
                backup = self.path + ".corrupt"
                n = 1
                while os.path.exists(backup):
                    backup = self.path + ".corrupt" + str(n)
                    n += 1
                os.replace(self.path, backup)
            except OSError as backup_error:
                self._load_blocked = True
                self.last_error += '; 无法备份原文件，已禁止覆盖：' + str(backup_error)
            self._records = []

    def _backup_schema1(self, raw):
        directory = os.path.dirname(os.path.abspath(self.path))
        prefix = self.path + '.schema1-backup-'
        while True:
            backup = prefix + uuid.uuid4().hex
            try:
                with open(backup, 'xb') as f:
                    f.write(raw)
                    f.flush()
                    os.fsync(f.fileno())
                return backup
            except FileExistsError:
                continue

    @staticmethod
    def _valid_time(value, nullable=False):
        return (nullable and value is None) or (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value))

    def _prune_recent(self):
        recent = sorted((r for r in self._records if r["last_used"] is not None and not r["favorite"]), key=lambda r: r["last_used"], reverse=True)
        keep = {r["id"] for r in recent[:self.history_limit]}
        self._records = [r for r in self._records if r["favorite"] or r["last_used"] is None or r["id"] in keep]
        self._records = [r for r in self._records if r["favorite"] or r["last_used"] is not None]

    def _save(self):
        if self._load_blocked:
            raise OSError('原搜索文件无法备份，拒绝覆盖。')
        raw = json.dumps({"schema_version": _SCHEMA_VERSION, "records": self._records}, ensure_ascii=False,
                         allow_nan=False, separators=(",", ":")).encode('utf-8')
        if len(self._records) > _MAX_RECORDS or len(raw) > _MAX_FILE_BYTES:
            raise ValueError('搜索记录已达本地存储容量限制。')
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix="." + os.path.basename(self.path) + ".", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.path)
        except Exception:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise

    def _change(self, operation):
        old = copy.deepcopy(self._records)
        try:
            result = operation()
            self._save()
        except Exception as error:
            self._records = old
            self.last_error = str(error)
            raise
        self.last_error = ''
        return copy.deepcopy(result)

    def lookup(self, source, query):
        query = self._validate(source, query)
        return copy.deepcopy(next((r for r in self._records if r["source"] == source and r["query"] == query), None))

    def get(self, record_id):
        if not isinstance(record_id, str):
            raise TypeError("record_id must be a string")
        return copy.deepcopy(next((r for r in self._records if r["id"] == record_id), None))

    def record_search(self, source, query, original_query=""):
        query = self._validate(source, query)
        if not isinstance(original_query, str) or len(original_query) > _MAX_QUERY:
            raise TypeError("original_query must be a string")
        if not query:
            return None
        def op():
            now = self.clock()
            r = next((x for x in self._records if x["source"] == source and x["query"] == query), None)
            if r is None:
                r = {"id": uuid.uuid4().hex, "source": source, "query": query, "original_query": original_query, "favorite": False, "created_at": now, "favorited_at": None, "last_used": now, "alias": "", "favorite_order": None}
                self._records.append(r)
            else:
                r["last_used"] = now
                if original_query and not r["original_query"]:
                    r["original_query"] = original_query
            self._prune_recent()
            return r
        return self._change(op)

    def toggle_favorite(self, source, query, original_query=""):
        query = self._validate(source, query)
        if not isinstance(original_query, str) or len(original_query) > _MAX_QUERY:
            raise TypeError("original_query must be a string")
        if not query:
            return None
        def op():
            r = next((x for x in self._records if x["source"] == source and x["query"] == query), None)
            now = self.clock()
            if r is None:
                r = {"id": uuid.uuid4().hex, "source": source, "query": query, "original_query": original_query, "favorite": True, "created_at": now, "favorited_at": now, "last_used": None, "alias": "", "favorite_order": self._next_favorite_order()}
                self._records.append(r)
            elif r["favorite"]:
                r["favorite"] = False
                r["favorited_at"] = None
                r["favorite_order"] = None
                if r["last_used"] is None:
                    self._records.remove(r)
            else:
                r["favorite"] = True
                r["favorited_at"] = now
                r["favorite_order"] = self._next_favorite_order()
                if original_query and not r["original_query"]:
                    r["original_query"] = original_query
            self._prune_recent()
            return r if r in self._records else None
        return self._change(op)

    def favorites(self):
        return copy.deepcopy(sorted((r for r in self._records if r["favorite"]), key=lambda r: r["favorite_order"]))

    def _next_favorite_order(self):
        return max((r["favorite_order"] for r in self._records if r["favorite"] and r["favorite_order"] is not None), default=-1) + 1

    def set_alias(self, record_id, alias):
        if not isinstance(record_id, str):
            raise TypeError("record_id must be a string")
        if not isinstance(alias, str):
            raise TypeError("alias must be a string")
        alias = alias.strip()
        if len(alias) > 256:
            raise ValueError("alias too long")
        def op():
            r = next((x for x in self._records if x["id"] == record_id), None)
            if r is None or not r["favorite"]:
                raise ValueError("record is not a favorite")
            r["alias"] = alias
            return r
        return self._change(op)

    def reorder_favorites(self, record_ids):
        if not isinstance(record_ids, (list, tuple)):
            raise TypeError("record_ids must be a list or tuple")
        if any(not isinstance(ident, str) for ident in record_ids):
            raise TypeError("record_ids must contain only strings")
        def op():
            favorites = [r for r in self._records if r["favorite"]]
            ids = [r["id"] for r in favorites]
            if len(record_ids) != len(set(record_ids)) or set(record_ids) != set(ids):
                raise ValueError("record_ids must be an exact permutation of favorites")
            by_id = {r["id"]: r for r in favorites}
            for order, ident in enumerate(record_ids):
                by_id[ident]["favorite_order"] = order
            return None
        self._change(op)

    def recent(self):
        return copy.deepcopy(sorted((r for r in self._records if r["last_used"] is not None and not r["favorite"]), key=lambda r: r["last_used"], reverse=True)[:self.history_limit])

    def remove_history(self, record_id):
        if not isinstance(record_id, str):
            raise TypeError("record_id must be a string")
        def op():
            r = next((x for x in self._records if x["id"] == record_id), None)
            if r is not None and not r["favorite"]:
                self._records.remove(r)
            return None
        self._change(op)

    def clear_recent(self):
        def op():
            self._records = [r for r in self._records if r["favorite"]]
            return None
        self._change(op)
