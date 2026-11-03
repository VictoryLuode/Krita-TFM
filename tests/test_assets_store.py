"""Asset folder storage, and pixel packing when Krita's PyQt is available."""

import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


store = load_module("tfm_assets_store", ROOT / "pykrita" / "tfm" / "assets" / "store.py")
pixels = load_module("tfm_assets_pixels", ROOT / "pykrita" / "tfm" / "assets" / "pixels.py")

assert pixels.expand_u8_to_u16(bytes((0, 1, 128, 255))) == bytes((
    0x00, 0x00,
    0x01, 0x01,
    0x80, 0x80,
    0xFF, 0xFF,
))
assert pixels.downsample_u16_bgra(pixels.expand_u8_to_u16(bytes((0, 1, 128, 255)))) == bytes((0, 1, 128, 255))
assert store.safe_name("  hello/world? ") == "hello world"
assert store.safe_name("...") == "Image"
assert store.safe_name("con") == "Image"
assert store.safe_name("ok", "Folder") == "ok"

with tempfile.TemporaryDirectory() as tmp:
    root = store.ensure_assets(os.path.join(tmp, "assets"))
    assert store.list_folders(root) == []
    assert store.list_images(root, "") == []

    first = store.create_folder(root, "", "Characters")
    second = store.create_folder(root, first, "Faces")
    again = store.create_folder(root, "", "Characters")
    assert first == "Characters"
    assert second == "Characters/Faces"
    assert again == "Characters 2"
    assert store.list_folders(root) == ["Characters", "Characters/Faces", "Characters 2"]

    for bad in ("../outside", "Characters/../../outside", "C:/Windows/notepad.exe", "Characters/../secret"):
        try:
            store.delete_image(root, bad)
        except store.AssetError:
            pass
        else:
            raise AssertionError(bad)
    try:
        store.delete_folder(root, "")
    except store.AssetError:
        pass
    else:
        raise AssertionError("root delete")

    outside = Path(tmp) / "escape.png"
    outside.write_bytes(b"nope")
    try:
        store.import_file(root, "../", str(outside))
    except store.AssetError:
        pass
    else:
        raise AssertionError("escaped import")
    assert list(Path(tmp).glob("*.png")) == [outside]

    source = Path(tmp) / "source.png"
    source.write_bytes(b"png-bytes")
    (Path(tmp) / "notes.txt").write_text("nope", encoding="utf-8")
    copied = store.import_file(root, first, str(source))
    assert copied == "Characters/source.png"
    assert (Path(root) / "Characters" / "source.png").read_bytes() == b"png-bytes"
    assert store.list_images(root, first) == ["source.png"]
    assert store.list_images(root, "") == []

    image = store.image_path(root, copied)
    assert store.read_meta(image) is None
    store.write_meta(image, -12, 40)
    assert store.read_meta(image) == (-12, 40)
    store.write_sidecar(image, {
        "kind": "filterlayer",
        "filter": "hsvadjustment",
        "properties": {"h": 0, "s": -30, "v": 25},
        "opacity": 200,
        "blendingMode": "multiply",
    })
    sidecar = store.read_sidecar(image)
    assert sidecar["kind"] == "filterlayer"
    assert sidecar["filter"] == "hsvadjustment"
    assert sidecar["properties"]["s"] == -30
    store.write_meta(image, 9, 10)
    sidecar = store.read_sidecar(image)
    assert sidecar["kind"] == "filterlayer"
    assert sidecar["filter"] == "hsvadjustment"
    assert store.read_meta(image) == (9, 10)
    (Path(image + ".json")).write_text("{", encoding="utf-8")
    assert store.read_meta(image) is None
    store.write_meta(image, 3, 4)

    same = store.move_image(root, copied, first)
    assert same == copied
    assert store.list_images(root, first) == ["source.png"]
    moved = store.move_image(root, copied, "")
    assert moved == "source.png"
    assert store.read_meta(store.image_path(root, moved)) == (3, 4)
    assert store.list_images(root, first) == []

    renamed = store.rename_image(root, moved, "Hero Shot")
    assert renamed == "Hero Shot.png"
    assert store.read_meta(store.image_path(root, renamed)) == (3, 4)
    cased = store.rename_image(root, renamed, "hero shot")
    assert cased == "hero shot.png"
    assert store.read_meta(store.image_path(root, cased)) == (3, 4)

    other = store.new_image_path(root, "", "hero shot")
    assert other.endswith("hero shot 2.png")
    assert not os.path.exists(other)

    try:
        store.import_file(root, "", str(Path(tmp) / "notes.txt"))
    except store.AssetError:
        pass
    else:
        raise AssertionError("txt import")

    store.delete_image(root, cased)
    assert store.list_images(root, "") == []
    assert not list(Path(root).glob("*.json"))

    renamed_folder = store.rename_folder(root, first, "People")
    assert renamed_folder == "People"
    assert "People/Faces" in store.list_folders(root)
    store.delete_folder(root, renamed_folder)
    assert store.list_folders(root) == ["Characters 2"]

    people = store.create_folder(root, "", "People")
    street = store.create_folder(root, people, "Street")
    layer = store.new_image_path(root, street, "Layer")
    Path(layer).write_bytes(b"png")
    moved_street = store.move_folder(root, street, "")
    assert moved_street == "Street"
    assert store.list_images(root, "Street") == ["Layer.png"]
    assert "People/Street" not in store.list_folders(root)
    assert store.move_folder(root, moved_street, "") == "Street"
    assert store.move_folder(root, "Street", people) == "People/Street"
    try:
        store.move_folder(root, people, "People/Street")
    except store.AssetError:
        pass
    else:
        raise AssertionError("move into self")
    store.delete_folder(root, people)
    assert "People" not in store.list_folders(root)
    assert "Street" not in store.list_folders(root)


def krita_root():
    candidates = []
    env = os.environ.get("KRITA_ROOT")
    if env:
        candidates.append(Path(env))
    found = shutil.which("krita")
    if found:
        resolved = Path(found).resolve()
        candidates.append(resolved.parents[1] if resolved.parent.name.lower() == "bin" else resolved.parent)
    for candidate in candidates:
        if (candidate / "lib" / "site-packages").is_dir() and (candidate / "bin").is_dir():
            return candidate
    return None


def test_pixels():
    root = krita_root()
    site = root / "lib" / "site-packages" if root else None
    if site is None or not site.is_dir():
        print("SKIP pixel packing: Krita PyQt not found")
        return
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(root / "bin"))
    os.environ["QT_PLUGIN_PATH"] = str(root / "bin")
    sys.path.insert(0, str(site))
    sys.path.insert(0, str(ROOT / "pykrita"))
    from PyQt5.QtCore import QByteArray
    from PyQt5.QtGui import QImage
    from PyQt5.QtWidgets import QApplication
    import types
    app = QApplication.instance() or QApplication([])
    del app
    krita = types.ModuleType("krita")

    class Extension:
        def __init__(self, parent):
            pass

    class FakeKrita:
        def addExtension(self, extension):
            pass

        def actions(self):
            return []

        def readSetting(self, group, key, default):
            return default

    fake = FakeKrita()

    class Krita:
        @staticmethod
        def instance():
            return fake

    krita.Extension = Extension
    krita.Krita = Krita
    sys.modules["krita"] = krita
    from tfm.assets.pixels import pack_bgra8, qbytearray_from, qimage_from_bgra8

    image = QImage(2, 1, QImage.Format.Format_ARGB32)
    image.fill(0)
    image.setPixel(0, 0, 0x04010203)
    image.setPixel(1, 0, 0xFF000000)
    packed, width, height = pack_bgra8(image)
    assert (width, height) == (2, 1)
    assert packed == bytes((3, 2, 1, 4, 0, 0, 0, 255))
    array = qbytearray_from(packed)
    assert isinstance(array, QByteArray)
    assert array.size() == len(packed)
    assert bytes(array) == packed
    restored = qimage_from_bgra8(packed, width, height)
    assert restored is not None and not restored.isNull()
    assert pack_bgra8(restored)[0] == packed
    print("pixel packing ok")


test_pixels()
print("assets store ok")
