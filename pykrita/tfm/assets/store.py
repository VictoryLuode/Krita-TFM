"""Folder tree of asset library entries next to the other TFM data files."""

import json
import os
import re
import shutil
import tempfile
import uuid

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp")
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class AssetError(Exception):
    """An asset-library change the panel can show directly."""


def default_assets_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    resource = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    assets = os.path.join(resource, "TFM", "assets")
    legacy = os.path.join(resource, "TFM", "library")
    if not os.path.isdir(assets) and os.path.isdir(legacy):
        try:
            os.rename(legacy, assets)
        except OSError:
            return legacy
    return assets


def ensure_assets(root=None):
    path = default_assets_dir() if root is None else root
    os.makedirs(path, exist_ok=True)
    return path


def safe_name(name, fallback="Image"):
    text = _INVALID.sub(" ", name or "")
    text = re.sub(r"\s+", " ", text).strip().rstrip(". ")
    if not text or text in {".", ".."} or text.upper() in _RESERVED:
        text = fallback
    return text[:80] or fallback


def list_folders(root):
    folders = []
    base = os.path.abspath(root)
    for dirpath, dirnames, _filenames in os.walk(base):
        dirnames[:] = sorted(
            (name for name in dirnames if _part_ok(name)),
            key=str.casefold,
        )
        rel = os.path.relpath(dirpath, base)
        if rel == ".":
            continue
        folders.append(rel.replace("\\", "/"))
    return folders


def list_images(root, folder_rel):
    directory = _folder(root, folder_rel)
    if not os.path.isdir(directory):
        return []
    names = []
    for name in os.listdir(directory):
        if not _part_ok(name):
            continue
        if os.path.splitext(name)[1].lower() not in IMAGE_SUFFIXES:
            continue
        if os.path.isfile(os.path.join(directory, name)):
            names.append(name)
    names.sort(key=str.casefold)
    return names


def create_folder(root, parent_rel, name):
    parent = _folder(root, parent_rel)
    os.makedirs(parent, exist_ok=True)
    stem = safe_name(name, "New Folder")
    dest_name = _unique_stem(parent, stem, "")
    path = os.path.join(parent, dest_name)
    try:
        os.mkdir(path)
    except OSError as error:
        raise AssetError("Could not create that folder.") from error
    return relative_path(root, path)


def rename_folder(root, rel, name):
    if not rel:
        raise AssetError("The asset library itself cannot be renamed.")
    source = _folder(root, rel)
    parent = os.path.dirname(source)
    stem = safe_name(name, "Folder")
    dest_name = _unique_stem(parent, stem, "", ignore=source)
    destination = os.path.join(parent, dest_name)
    if os.path.normcase(destination) == os.path.normcase(source) and destination == source:
        return rel.replace("\\", "/")
    try:
        _rename_path(source, destination)
    except OSError as error:
        raise AssetError("Could not rename that folder.") from error
    new_rel = relative_path(root, destination)
    _retarget_order(root, rel, new_rel)
    return new_rel


def move_folder(root, rel, dest_parent):
    rel = _clean_rel(rel)
    dest_parent = _clean_rel(dest_parent)
    if not rel:
        raise AssetError("That folder is not in the asset library.")
    if dest_parent == rel or dest_parent.startswith(rel + "/"):
        raise AssetError("A folder cannot be moved into itself.")
    source_parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
    if source_parent == dest_parent:
        return rel
    source = _folder(root, rel)
    if not os.path.isdir(source):
        raise AssetError("That folder is not in the asset library.")
    parent_path = _folder(root, dest_parent)
    try:
        os.makedirs(parent_path, exist_ok=True)
        destination = os.path.join(
            parent_path,
            _unique_stem(parent_path, os.path.basename(source), "", ignore=source),
        )
        _rename_path(source, destination)
    except OSError as error:
        raise AssetError("Could not move that folder.") from error
    new_rel = relative_path(root, destination)
    _retarget_order(root, rel, new_rel)
    return new_rel


def delete_folder(root, rel):
    if not rel:
        raise AssetError("The asset library itself cannot be removed.")
    path = _folder(root, rel)
    try:
        shutil.rmtree(path)
    except OSError as error:
        raise AssetError("Could not delete that folder.") from error
    _forget_order(root, rel)


def new_image_path(root, folder_rel, stem, suffix=".png"):
    directory = _folder(root, folder_rel)
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as error:
        raise AssetError("Could not create that folder.") from error
    suffix = suffix if suffix.startswith(".") else "." + suffix
    name = _unique_stem(directory, safe_name(stem), suffix.lower()) + suffix.lower()
    return os.path.join(directory, name)


def import_file(root, folder_rel, source):
    if not os.path.isfile(source):
        raise AssetError("That file cannot be read.")
    suffix = os.path.splitext(source)[1].lower()
    if suffix not in IMAGE_SUFFIXES:
        raise AssetError("That file is not a supported image.")
    stem = safe_name(os.path.splitext(os.path.basename(source))[0])
    destination = new_image_path(root, folder_rel, stem, suffix)
    try:
        shutil.copyfile(source, destination)
    except OSError as error:
        raise AssetError("Could not copy that image.") from error
    return relative_path(root, destination)


def move_image(root, rel, dest_folder):
    source = image_path(root, rel)
    if _folder_rel(root, os.path.dirname(source)) == _clean_rel(dest_folder):
        return _clean_rel(rel)
    stem = os.path.splitext(os.path.basename(source))[0]
    suffix = os.path.splitext(source)[1].lower()
    destination = new_image_path(root, dest_folder, stem, suffix)
    try:
        _rename_with_sidecar(source, destination)
    except OSError as error:
        raise AssetError("Could not move that image.") from error
    return relative_path(root, destination)


def rename_image(root, rel, stem):
    source = image_path(root, rel)
    suffix = os.path.splitext(source)[1].lower()
    destination = os.path.join(
        os.path.dirname(source),
        _unique_stem(os.path.dirname(source), safe_name(stem), suffix, ignore=source) + suffix,
    )
    if os.path.abspath(destination) == os.path.abspath(source):
        return rel.replace("\\", "/")
    try:
        _rename_with_sidecar(source, destination)
    except OSError as error:
        raise AssetError("Could not rename that image.") from error
    return relative_path(root, destination)


def delete_image(root, rel):
    path = image_path(root, rel)
    sidecar = path + ".json"
    try:
        os.remove(path)
        if os.path.isfile(sidecar):
            os.remove(sidecar)
    except OSError as error:
        raise AssetError("Could not delete that image.") from error


def image_path(root, rel):
    path = _inside_path(root, rel)
    if not os.path.isfile(path):
        raise AssetError("That asset is no longer in the library.")
    if os.path.splitext(path)[1].lower() not in IMAGE_SUFFIXES:
        raise AssetError("That file is not a supported image.")
    return path


def read_sidecar(path):
    try:
        with open(path + ".json", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_sidecar(path, data):
    if not isinstance(data, dict):
        raise AssetError("Could not save asset metadata.")
    directory = os.path.dirname(path)
    fd, temporary = tempfile.mkstemp(dir=directory, suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path + ".json")
        temporary = ""
    finally:
        if temporary and os.path.exists(temporary):
            os.remove(temporary)


def update_sidecar(path, updates):
    data = read_sidecar(path) or {}
    data.update(updates)
    write_sidecar(path, data)
    return data


def read_meta(path):
    data = read_sidecar(path)
    if not data or data.get("placed") is not True:
        return None
    try:
        return int(data["x"]), int(data["y"])
    except (KeyError, TypeError, ValueError):
        return None


def write_meta(path, x, y):
    update_sidecar(path, {"placed": True, "x": int(x), "y": int(y)})


def relative_path(root, path):
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
    return rel.replace("\\", "/")


def _clean_rel(rel):
    return (rel or "").replace("\\", "/").strip("/")


def _folder_rel(root, path):
    rel = relative_path(root, path)
    return "" if rel == "." else rel


def _part_ok(name):
    return bool(name) and name not in {".", ".."} and not name.startswith(".") and ":" not in name and "/" not in name and "\\" not in name


def _parts(rel):
    text = (rel or "").replace("\\", "/").strip("/")
    if not text:
        return []
    parts = text.split("/")
    if any(not _part_ok(part) for part in parts):
        raise AssetError("That folder is not in the asset library.")
    return parts


def _inside_path(root, rel):
    root_abs = os.path.abspath(root)
    parts = _parts(rel)
    path = os.path.abspath(os.path.join(root_abs, *parts)) if parts else root_abs
    case_root = os.path.normcase(root_abs)
    case_path = os.path.normcase(path)
    if case_path != case_root and not case_path.startswith(case_root + os.sep):
        raise AssetError("That folder is not in the asset library.")
    return path


def _folder(root, rel):
    path = _inside_path(root, rel)
    if os.path.exists(path) and not os.path.isdir(path):
        raise AssetError("That folder is not in the asset library.")
    return path


def _unique_stem(directory, stem, suffix, ignore=None):
    candidate = stem
    number = 2
    ignore_key = os.path.normcase(os.path.abspath(ignore)) if ignore else None
    while number < 10000:
        path = os.path.join(directory, candidate + suffix)
        if ignore_key is not None and os.path.normcase(os.path.abspath(path)) == ignore_key:
            return candidate
        if not os.path.exists(path):
            return candidate
        candidate = "{} {}".format(stem, number)
        number += 1
    raise AssetError("Too many files with that name.")


def _rename_path(source, destination):
    if os.path.abspath(source) == os.path.abspath(destination):
        return
    if os.path.normcase(os.path.abspath(source)) == os.path.normcase(os.path.abspath(destination)):
        temporary = source + ".__rename__"
        os.rename(source, temporary)
        os.rename(temporary, destination)
        return
    os.rename(source, destination)


_ORDER_FILE = ".tfm-order.json"


def merged_children(root, parent_rel):
    """Ordered children of one folder: saved order, then new folders at the end."""
    parent_rel = _clean_rel(parent_rel)
    names = _direct_folder_names(root, parent_rel)
    known = set(names)
    result = []
    seen = set()
    for entry in _load_order(root).get(parent_rel, []):
        if entry["type"] == "folder":
            name = entry["name"]
            if name in known and name not in seen:
                result.append(dict(entry))
                seen.add(name)
        else:
            result.append(dict(entry))
    for name in names:
        if name not in seen:
            result.append({"type": "folder", "name": name})
    return result


def insert_marker(root, parent_rel, kind, before=None, text="标题"):
    if kind not in ("separator", "title"):
        raise AssetError("That item cannot be added.")
    parent_rel = _clean_rel(parent_rel)
    if parent_rel and not os.path.isdir(_folder(root, parent_rel)):
        raise AssetError("That folder is not in the asset library.")
    children = merged_children(root, parent_rel)
    entry = {"type": kind, "id": _marker_id(root)}
    if kind == "title":
        entry["text"] = _clean_title(text) or "标题"
    children.insert(_entry_index(children, before), entry)
    _write_parent(root, parent_rel, children)
    return entry


def rename_title(root, marker_id, text):
    cleaned = _clean_title(text)
    if not cleaned:
        raise AssetError("The title cannot be empty.")
    order = _load_order(root)
    for entries in order.values():
        for entry in entries:
            if entry.get("type") == "title" and entry.get("id") == marker_id:
                entry["text"] = cleaned
                _save_order(root, order)
                return cleaned
    raise AssetError("That title is no longer in the library.")


def remove_marker(root, marker_id):
    if not marker_id:
        raise AssetError("That item is no longer in the library.")
    order = _load_order(root)
    found = False
    for key in list(order):
        kept = [entry for entry in order[key] if entry.get("id") != marker_id]
        if len(kept) != len(order[key]):
            found = True
            if kept:
                order[key] = kept
            else:
                order.pop(key)
    if not found:
        raise AssetError("That item is no longer in the library.")
    _save_order(root, order)


def relocate_node(root, kind, key, dest_parent, before=None):
    """Move a folder, separator, or title to dest_parent, inserted before `before`."""
    dest_parent = _clean_rel(dest_parent)
    if dest_parent and not os.path.isdir(_folder(root, dest_parent)):
        raise AssetError("That folder is not in the asset library.")
    if kind == "folder":
        return _relocate_folder(root, key, dest_parent, before)
    if kind not in ("separator", "title"):
        raise AssetError("That item cannot be moved.")
    return _relocate_marker(root, kind, key, dest_parent, before)


def _relocate_folder(root, rel, dest_parent, before):
    rel = _clean_rel(rel)
    source_parent, leaf = _split_rel(rel)
    if (
        before
        and before.get("type") == "folder"
        and before.get("name") == leaf
        and source_parent == dest_parent
    ):
        return rel
    if not rel or dest_parent == rel or dest_parent.startswith(rel + "/"):
        raise AssetError("A folder cannot be moved into itself.")
    new_rel = rel
    if source_parent != dest_parent:
        new_rel = move_folder(root, rel, dest_parent)
        leaf = new_rel.rsplit("/", 1)[-1]
    children = [
        entry for entry in merged_children(root, dest_parent)
        if not (entry.get("type") == "folder" and entry.get("name") == leaf)
    ]
    children.insert(_entry_index(children, before), {"type": "folder", "name": leaf})
    _write_parent(root, dest_parent, children)
    return new_rel


def _relocate_marker(root, kind, marker_id, dest_parent, before):
    if (
        before
        and before.get("type") == kind
        and before.get("id") == marker_id
    ):
        return marker_id
    order = _load_order(root)
    found = None
    found_parent = None
    for parent, entries in order.items():
        for entry in entries:
            if entry.get("type") == kind and entry.get("id") == marker_id:
                found = dict(entry)
                found_parent = parent
                break
        if found is not None:
            break
    if found is None:
        raise AssetError("That item is no longer in the library.")
    if found_parent == dest_parent:
        children = [
            entry for entry in merged_children(root, dest_parent)
            if not (entry.get("type") == kind and entry.get("id") == marker_id)
        ]
        children.insert(_entry_index(children, before), found)
        _write_parent(root, dest_parent, children)
        return marker_id
    source = [
        entry for entry in merged_children(root, found_parent)
        if not (entry.get("type") == kind and entry.get("id") == marker_id)
    ]
    _write_parent(root, found_parent, source)
    children = merged_children(root, dest_parent)
    children.insert(_entry_index(children, before), found)
    _write_parent(root, dest_parent, children)
    return marker_id


def _direct_folder_names(root, parent_rel):
    path = _folder(root, parent_rel)
    if not os.path.isdir(path):
        return []
    try:
        listed = os.listdir(path)
    except OSError:
        return []
    names = [
        name for name in listed
        if _part_ok(name) and os.path.isdir(os.path.join(path, name))
    ]
    names.sort(key=str.casefold)
    return names


def _order_path(root):
    return os.path.join(os.path.abspath(root), _ORDER_FILE)


def _load_order(root):
    try:
        with open(_order_path(root), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    order = {}
    for key, entries in data.items():
        if not isinstance(key, str) or not isinstance(entries, list):
            continue
        cleaned = []
        seen_names = set()
        seen_ids = set()
        for entry in entries:
            item = _clean_order_entry(entry, seen_names, seen_ids)
            if item is not None:
                cleaned.append(item)
        if cleaned:
            order[_clean_rel(key)] = cleaned
    return order


def _clean_order_entry(entry, seen_names, seen_ids):
    if not isinstance(entry, dict):
        return None
    kind = entry.get("type")
    if kind == "folder":
        name = entry.get("name")
        if not isinstance(name, str) or not _part_ok(name) or name in seen_names:
            return None
        seen_names.add(name)
        return {"type": "folder", "name": name}
    if kind not in ("separator", "title"):
        return None
    marker_id = entry.get("id")
    if not isinstance(marker_id, str) or not marker_id or marker_id in seen_ids:
        return None
    seen_ids.add(marker_id)
    item = {"type": kind, "id": marker_id}
    if kind == "title":
        item["text"] = _clean_title(entry.get("text")) or "标题"
    return item


def _save_order(root, order):
    path = _order_path(root)
    stored = {key: value for key, value in order.items() if value}
    if not stored:
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError as error:
                raise AssetError("Could not save the category order.") from error
        return
    fd, temporary = tempfile.mkstemp(dir=os.path.abspath(root), suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(stored, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
        temporary = ""
    except OSError as error:
        raise AssetError("Could not save the category order.") from error
    finally:
        if temporary and os.path.exists(temporary):
            os.remove(temporary)


def _write_parent(root, parent_rel, children):
    order = _load_order(root)
    parent_rel = _clean_rel(parent_rel)
    if children:
        order[parent_rel] = children
    else:
        order.pop(parent_rel, None)
    _save_order(root, order)


def _marker_id(root):
    used = set()
    for entries in _load_order(root).values():
        for entry in entries:
            if entry.get("id"):
                used.add(entry["id"])
    while True:
        marker_id = uuid.uuid4().hex[:8]
        if marker_id not in used:
            return marker_id


def _clean_title(text):
    cleaned = re.sub(r"[\x00-\x1f]", " ", str(text or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:80]


def _split_rel(rel):
    rel = _clean_rel(rel)
    if not rel or "/" not in rel:
        return "", rel
    parent, leaf = rel.rsplit("/", 1)
    return parent, leaf


def _entry_index(children, before):
    if not before:
        return len(children)
    for index, entry in enumerate(children):
        if _entry_matches(entry, before):
            return index
    return len(children)


def _entry_matches(entry, before):
    if not isinstance(before, dict) or entry.get("type") != before.get("type"):
        return False
    if entry.get("type") == "folder":
        return entry.get("name") == before.get("name")
    return bool(before.get("id")) and entry.get("id") == before.get("id")


def _retarget_order(root, old_rel, new_rel):
    old_rel = _clean_rel(old_rel)
    new_rel = _clean_rel(new_rel)
    if not old_rel or old_rel == new_rel:
        return
    order = _load_order(root)
    if not order:
        return
    old_parent, old_leaf = _split_rel(old_rel)
    new_parent, new_leaf = _split_rel(new_rel)
    rewritten = {}
    moved = {}
    for key, entries in order.items():
        if key == old_rel or key.startswith(old_rel + "/"):
            moved[new_rel + key[len(old_rel):]] = entries
        else:
            rewritten[key] = entries
    rewritten.update(moved)
    if old_parent == new_parent:
        for entry in rewritten.get(old_parent, []):
            if entry.get("type") == "folder" and entry.get("name") == old_leaf:
                entry["name"] = new_leaf
    else:
        source = [
            entry for entry in rewritten.get(old_parent, [])
            if not (entry.get("type") == "folder" and entry.get("name") == old_leaf)
        ]
        if source:
            rewritten[old_parent] = source
        else:
            rewritten.pop(old_parent, None)
    _save_order(root, rewritten)


def _forget_order(root, rel):
    rel = _clean_rel(rel)
    if not rel:
        return
    order = _load_order(root)
    if not order:
        return
    parent, leaf = _split_rel(rel)
    if parent in order:
        kept = [
            entry for entry in order[parent]
            if not (entry.get("type") == "folder" and entry.get("name") == leaf)
        ]
        if kept:
            order[parent] = kept
        else:
            order.pop(parent, None)
    for key in list(order):
        if key == rel or key.startswith(rel + "/"):
            order.pop(key, None)
    _save_order(root, order)


def _rename_with_sidecar(source, destination):
    sidecar = source + ".json"
    _rename_path(source, destination)
    if os.path.isfile(sidecar):
        _rename_path(sidecar, destination + ".json")
