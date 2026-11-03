"""Folder tree of asset library entries next to the other TFM data files."""

import json
import os
import re
import shutil
import tempfile

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
    return relative_path(root, destination)


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
    return relative_path(root, destination)


def delete_folder(root, rel):
    if not rel:
        raise AssetError("The asset library itself cannot be removed.")
    path = _folder(root, rel)
    try:
        shutil.rmtree(path)
    except OSError as error:
        raise AssetError("Could not delete that folder.") from error


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


def _rename_with_sidecar(source, destination):
    sidecar = source + ".json"
    _rename_path(source, destination)
    if os.path.isfile(sidecar):
        _rename_path(sidecar, destination + ".json")
