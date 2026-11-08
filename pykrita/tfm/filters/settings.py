"""Persistent user settings shared by the Python panel and native filter."""

import json
import math
import os
import tempfile

from .catalog import FILTERS, FILTER_DEFAULT_SPECS, VULKAN_FILTER_IDS

_OPTIONS = {
    "backend": "auto",
    "gpu_fallback": "cpu",
    "cpu_threads": 0,
    "cpu_thread_limit": 32,

    "managed_filters": [entry["id"] for entry in FILTERS],
    "enabled_filters": [entry["id"] for entry in FILTERS],
    "show_native_filters": True,
    "filter_defaults": {},
    "filter_backends": {},
}
_BACKENDS = {"auto", "cpu", "gpu"}
_FALLBACKS = {"cpu", "error"}
_THREAD_VALUES = {0, 1, 2, 4, 6, 8, 12, 16, 24, 32}


def _kritarc_path():
    base = os.environ.get("KLOCALAPPDATA") or os.environ.get("LOCALAPPDATA") or ""
    return os.path.join(base, "kritarc") if base else None


def _resource_directory():
    """Read ResourceDirectory straight from kritarc.

    Parsed by hand instead of via QSettings so the native filter and the panel
    agree even when the runtime's Qt settings paths differ, and so the rule can
    be tested outside a Krita session.
    """
    path = _kritarc_path()
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                key, separator, value = line.partition("=")
                if separator and key.strip() == "ResourceDirectory":
                    return value.strip()
    except OSError:
        return ""
    return ""


def _config_path():
    """Use the same settings file as the installed native filter."""
    resource = _resource_directory()
    if resource:
        return os.path.join(resource, "TFM", "settings.json")
    return _app_config_path("TFM")


def _legacy_paths():
    """Read-only compatibility locations, newest path first."""
    resource = _resource_directory()
    paths = []
    if resource:
        paths.append(os.path.join(resource, "pykrita", "fxmanager", "data", "settings.json"))
        paths.append(os.path.join(resource, "FilterManager", "settings.json"))
    else:
        paths.append(_app_config_path("fxmanager"))
    paths.append(_app_config_path("FilterManager"))
    return [path for path in paths if path]


def _app_config_path(name):
    try:
        try:
            from PyQt6.QtCore import QStandardPaths
            location = QStandardPaths.StandardLocation.AppConfigLocation
        except ImportError:
            from PyQt5.QtCore import QStandardPaths
            location = QStandardPaths.AppConfigLocation
        base = QStandardPaths.writableLocation(location)
    except (ImportError, AttributeError):
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, name, "settings.json") if base else None


def _migrate_legacy(path):
    """Atomically publish one legacy file without replacing a winner."""
    if not path or os.path.exists(path):
        return
    legacy = next((candidate for candidate in _legacy_paths() if os.path.isfile(candidate)), None)
    if not legacy or legacy == path:
        return
    temporary = None
    try:
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="settings.migrate.", suffix=".tmp", dir=directory)
        with os.fdopen(fd, "wb") as target, open(legacy, "rb") as source:
            target.write(source.read())
        # A hard link publishes the complete file and fails if another process
        # created the canonical file first.  The legacy file remains untouched.
        os.link(temporary, path)
    except OSError:
        pass
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _read_path(path):
    """Return canonical path first, then the read-only legacy fallback."""
    if path and os.path.isfile(path):
        return path
    return next((candidate for candidate in _legacy_paths() if os.path.isfile(candidate)), None)


def _legacy_id_map():
    mapping = {}
    for entry in FILTERS:
        ident = entry["id"]
        if ident.startswith("tfm_"):
            suffix = ident[len("tfm_"):]
            mapping["filtermanager_" + suffix] = ident
            mapping["fxmanager_" + suffix] = ident
    return mapping


def clean_filter_defaults(values):
    result = {}
    if not isinstance(values, dict):
        return result
    old_ids = _legacy_id_map()
    for ident, entries in values.items():
        ident = old_ids.get(ident, ident) if isinstance(ident, str) else ident
        if ident not in FILTER_DEFAULT_SPECS or not isinstance(entries, dict):
            continue
        clean = {}
        for spec in FILTER_DEFAULT_SPECS[ident]:
            key = spec["key"]
            if key not in entries:
                continue
            value = entries[key]
            default = spec["default"]
            if "options" in spec:
                choices = [item[0] if isinstance(item, (tuple, list)) else item for item in spec["options"]]
                valid = isinstance(value, str) and value in choices
            elif isinstance(default, bool):
                valid = isinstance(value, bool)
            else:
                valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                         and spec["min"] <= value <= spec["max"] and math.isfinite(value))
                if spec.get("type") == "integer":
                    valid = valid and value == int(value)
                    if valid: value = int(value)
            if valid:
                clean[key] = value
        if clean:
            result[ident] = clean
    return result


def _normalise(values):
    result = dict(_OPTIONS)
    if not isinstance(values, dict):
        return result
    result.update({key: value for key, value in values.items() if key not in _OPTIONS and key != "remember_parameters"})
    backend = values.get("backend")
    fallback = values.get("gpu_fallback")
    threads = values.get("cpu_threads")
    managed = values.get("managed_filters")
    enabled = values.get("enabled_filters")
    show_native = values.get("show_native_filters")

    # Convert historical built-in IDs only; preserve unrelated external IDs.
    old_ids = _legacy_id_map()
    if isinstance(managed, list):
        managed = [old_ids.get(item, item) if isinstance(item, str) else item for item in managed]
    if isinstance(enabled, list):
        enabled = [old_ids.get(item, item) if isinstance(item, str) else item for item in enabled]
    if isinstance(result.get("filter_categories"), dict):
        result["filter_categories"] = {
            k: [old_ids.get(item, item) if isinstance(item, str) else item for item in v]
            if isinstance(v, list) else v
            for k, v in result["filter_categories"].items()
        }

    result["filter_defaults"] = clean_filter_defaults(values.get("filter_defaults"))

    filter_backends = values.get("filter_backends")
    cleaned_backends = {}
    if isinstance(filter_backends, dict):
        for ident, choice in filter_backends.items():
            ident = old_ids.get(ident, ident) if isinstance(ident, str) else ident
            if (isinstance(ident, str) and ident in VULKAN_FILTER_IDS
                    and isinstance(choice, str) and choice in _BACKENDS and choice != "auto"):
                cleaned_backends[ident] = choice
    result["filter_backends"] = cleaned_backends

    if isinstance(show_native, bool):
        result["show_native_filters"] = show_native
    if isinstance(backend, str) and backend in _BACKENDS:
        result["backend"] = backend
    if isinstance(fallback, str) and fallback in _FALLBACKS:
        result["gpu_fallback"] = fallback
    if isinstance(threads, int) and not isinstance(threads, bool) and threads in _THREAD_VALUES:
        result["cpu_threads"] = threads
    if isinstance(managed, list):
        managed_ids = [item for item in managed if isinstance(item, str) and item
                       and item not in {"filtermanager_ml_color_match", "fxmanager_ml_color_match", "tfm_ml_color_match"}]
        result["managed_filters"] = managed_ids
    if isinstance(enabled, list):
        result["enabled_filters"] = [item for item in enabled if isinstance(item, str) and item in set(result["managed_filters"])]
    return result


def load(strict=False):
    path = _config_path()
    if not path:
        return dict(_OPTIONS)
    _migrate_legacy(path)
    try:
        try:
            handle = open(path, "r", encoding="utf-8")
        except FileNotFoundError:
            source = _read_path(path)
            if not source:
                return dict(_OPTIONS)
            handle = open(source, "r", encoding="utf-8")
        with handle:
            values = json.load(handle)
        if not isinstance(values, dict):
            raise ValueError("filter settings must be an object")
        return _normalise(values)
    except (OSError, ValueError, TypeError):
        if strict:
            raise
        return dict(_OPTIONS)


def save(values):
    path = _config_path()
    if not path:
        return False
    try:
        merged = _normalise({**load(strict=True), **values})
    except (OSError, ValueError, TypeError):
        return False
    directory = os.path.dirname(path)
    temporary = None
    try:
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="settings.", suffix=".tmp", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(merged, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    except OSError:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        return False
    return True


def config_path():
    return _config_path()
