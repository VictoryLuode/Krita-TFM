"""Serialize group layers (with nested paint/filter/group children) for Asset Library."""

import base64
import os
import tempfile

from . import filter_asset, mask_asset, pixels
from ..menus.qtcompat import QByteArray, QColor, QImage
from .store import AssetError

KIND = "grouplayer"
PAINT_KIND = "paintlayer"
_MAX_DEPTH = 32
_SUPPORTED = frozenset({"grouplayer", "paintlayer", "filterlayer"})


def is_group_layer(node):
    if node is None:
        return False
    try:
        return (node.type() or "").lower() == "grouplayer"
    except Exception:
        return False


def capture(node, doc, pixel_budget=64000000):
    state = {"pixels": 0, "budget": int(pixel_budget), "skipped": []}
    payload = _capture_node(node, doc, state, 0)
    if payload is None or payload.get("kind") != KIND:
        raise AssetError("That layer group could not be saved.")
    if state["skipped"]:
        payload["skipped"] = list(state["skipped"])
    return payload


def capture_paint(node, doc, pixel_budget=64000000):
    state = {"pixels": 0, "budget": int(pixel_budget), "skipped": []}
    payload = _capture_paint(node, doc, state)
    if payload is None or payload.get("kind") != PAINT_KIND:
        raise AssetError("That paint layer could not be saved.")
    if state["skipped"]:
        payload["skipped"] = list(state["skipped"])
    return payload


def create_paint_layer(doc, name, payload, parent, above):
    if parent is None:
        raise AssetError("Open a document first.")
    if not isinstance(payload, dict) or payload.get("kind") != PAINT_KIND:
        raise AssetError("That paint preset is incomplete.")
    node = _create_paint_child(doc, name, payload)
    if node is None:
        raise AssetError("Could not create a paint layer.")
    if not parent.addChildNode(node, above):
        raise AssetError("Could not add the layer.")
    return node


def preview_image(node, edge=256):
    try:
        image = node.thumbnail(int(edge), int(edge))
        if image is not None and not image.isNull():
            return image
    except Exception:
        pass
    image = QImage(int(edge), int(edge), QImage.Format.Format_ARGB32)
    image.fill(QColor(64, 84, 64, 255))
    return image


def create_layer(doc, name, payload, parent, above):
    if parent is None:
        raise AssetError("Open a document first.")
    if not isinstance(payload, dict) or payload.get("kind") != KIND:
        raise AssetError("That group preset is incomplete.")
    group = _create_node(doc, payload, override_name=name)
    if group is None:
        raise AssetError("Could not create a group layer.")
    if not parent.addChildNode(group, above):
        raise AssetError("Could not add the group layer.")
    return group


def _capture_node(node, doc, state, depth):
    if node is None:
        return None
    if depth > _MAX_DEPTH:
        raise AssetError("That layer group is nested too deeply.")
    try:
        kind = (node.type() or "").lower()
    except Exception:
        return None
    if kind.endswith("mask"):
        # Masks belong to their parent layer; group children that are masks are unusual.
        state["skipped"].append(node.name() or kind)
        return None
    if kind not in _SUPPORTED:
        state["skipped"].append(node.name() or kind)
        return None
    if kind == "filterlayer":
        payload = filter_asset.capture(node, state=state)
        _copy_common(node, payload)
        return payload
    if kind == "paintlayer":
        return _capture_paint(node, doc, state)
    payload = {
        "kind": KIND,
        "name": node.name() or "Group",
        "children": [],
    }
    _copy_common(node, payload)
    try:
        payload["passThrough"] = bool(node.passThroughMode())
    except Exception:
        pass
    try:
        payload["collapsed"] = bool(node.collapsed())
    except Exception:
        pass
    try:
        children = node.childNodes() or []
    except Exception:
        children = []
    for child in children:
        item = _capture_node(child, doc, state, depth + 1)
        if item is not None:
            payload["children"].append(item)
    return payload


def _capture_paint(node, doc, state):
    payload = {
        "kind": "paintlayer",
        "name": node.name() or "Layer",
        "x": 0,
        "y": 0,
        "png": "",
    }
    _copy_common(node, payload)
    try:
        bounds = node.bounds()
    except Exception:
        bounds = None
    if bounds is not None and not bounds.isEmpty() and bounds.width() >= 1 and bounds.height() >= 1:
        width = int(bounds.width())
        height = int(bounds.height())
        needed = width * height
        if state["pixels"] + needed > state["budget"]:
            raise AssetError("That layer group is too large to save.")
        try:
            raw = node.pixelData(bounds.x(), bounds.y(), width, height)
            data = bytes(raw)
        except Exception as error:
            raise AssetError("Could not read a paint layer in that group.") from error
        image = _pixels_to_image(doc, data, width, height)
        if image is None or image.isNull():
            raise AssetError("Could not read a paint layer in that group.")
        payload["x"] = int(bounds.x())
        payload["y"] = int(bounds.y())
        payload["png"] = _image_to_png_b64(image)
        state["pixels"] += needed
    mask_asset.append_masks(node, payload, state)
    return payload


def _create_node(doc, payload, override_name=None):
    kind = str((payload or {}).get("kind") or "")
    name = override_name if override_name else (payload.get("name") or kind or "Layer")
    if kind == "filterlayer":
        # create_layer adds to parent; here we only build the node.
        return _create_filter_child(doc, name, payload)
    if kind == "paintlayer":
        return _create_paint_child(doc, name, payload)
    if kind != KIND:
        return None
    group = doc.createGroupLayer(name)
    if group is None:
        raise AssetError("Could not create a group layer.")
    _apply_common(group, payload)
    if "passThrough" in payload:
        try:
            group.setPassThroughMode(bool(payload["passThrough"]))
        except Exception:
            pass
    if "collapsed" in payload:
        try:
            group.setCollapsed(bool(payload["collapsed"]))
        except Exception:
            pass
    for child_payload in payload.get("children") or []:
        if not isinstance(child_payload, dict):
            continue
        child = _create_node(doc, child_payload)
        if child is None:
            continue
        if not group.addChildNode(child, None):
            raise AssetError("Could not rebuild a layer inside the group.")
    return group


def _create_filter_child(doc, name, payload):
    from krita import Krita, Selection

    filter_id = str(payload.get("filter") or "")
    if not filter_id:
        raise AssetError("That group contains an incomplete filter layer.")
    filt = Krita.instance().filter(filter_id)
    if filt is None:
        raise AssetError('Filter "{}" is not available in this Krita.'.format(filter_id))
    properties = payload.get("properties") or {}
    if not isinstance(properties, dict):
        properties = {}
    filter_asset._apply_properties(filt, properties)
    selection = Selection()
    selection.selectAll(doc.rootNode(), 255)
    layer = doc.createFilterLayer(name, filt, selection)
    if layer is None:
        raise AssetError("Could not create a filter layer in the group.")
    try:
        live = layer.filter()
    except Exception:
        live = None
    if live is not None:
        filter_asset._apply_properties(live, properties)
    _apply_common(layer, payload)
    mask_asset.restore_masks(doc, layer, payload)
    return layer


def _create_paint_child(doc, name, payload):
    node = doc.createNode(name, "paintlayer")
    if node is None:
        raise AssetError("Could not create a paint layer in the group.")
    _apply_common(node, payload)
    png = payload.get("png") or ""
    if not png:
        return node
    image = _png_b64_to_image(png)
    if image is None or image.isNull():
        raise AssetError("Could not restore a paint layer in the group.")
    try:
        depth = doc.colorDepth()
    except Exception:
        depth = "U8"
    packed = pixels.paint_bytes(image, depth)
    if not packed or packed[1] < 1:
        raise AssetError("Could not restore a paint layer in the group.")
    raw, width, height = packed
    x = int(payload.get("x") or 0)
    y = int(payload.get("y") or 0)
    if not node.setPixelData(pixels.qbytearray_from(raw), x, y, width, height):
        raise AssetError("Could not write a paint layer in the group.")
    mask_asset.restore_masks(doc, node, payload)
    return node


def _copy_common(node, payload):
    try:
        payload["opacity"] = int(node.opacity())
    except Exception:
        pass
    try:
        mode = node.blendingMode()
        if mode:
            payload["blendingMode"] = str(mode)
    except Exception:
        pass
    try:
        payload["inheritAlpha"] = bool(node.inheritAlpha())
    except Exception:
        pass
    try:
        payload["visible"] = bool(node.visible())
    except Exception:
        pass
    try:
        payload["locked"] = bool(node.locked())
    except Exception:
        pass
    try:
        payload["colorLabel"] = int(node.colorLabel())
    except Exception:
        pass


def _apply_common(node, payload):
    if "opacity" in payload:
        try:
            node.setOpacity(int(payload["opacity"]))
        except Exception:
            pass
    if payload.get("blendingMode"):
        try:
            node.setBlendingMode(str(payload["blendingMode"]))
        except Exception:
            pass
    if "inheritAlpha" in payload:
        try:
            node.setInheritAlpha(bool(payload["inheritAlpha"]))
        except Exception:
            pass
    if "visible" in payload:
        try:
            node.setVisible(bool(payload["visible"]))
        except Exception:
            pass
    if "locked" in payload:
        try:
            node.setLocked(bool(payload["locked"]))
        except Exception:
            pass
    if "colorLabel" in payload:
        try:
            node.setColorLabel(int(payload["colorLabel"]))
        except Exception:
            pass


def _pixels_to_image(doc, data, width, height):
    try:
        model = doc.colorModel()
        depth = doc.colorDepth()
    except Exception:
        return None
    if model != "RGBA":
        return None
    if depth == "U8" and len(data) >= width * height * 4:
        return pixels.qimage_from_bgra8(data[: width * height * 4], width, height)
    if depth == "U16" and len(data) >= width * height * 8:
        return pixels.qimage_from_bgra8(
            pixels.downsample_u16_bgra(data[: width * height * 8]), width, height)
    return None


def _image_to_png_b64(image):
    if image.format() != QImage.Format.Format_ARGB32:
        image = image.convertToFormat(QImage.Format.Format_ARGB32)
    fd, temporary = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        if not image.save(temporary, "PNG"):
            raise AssetError("Could not encode a paint layer in that group.")
        with open(temporary, "rb") as handle:
            return base64.b64encode(handle.read()).decode("ascii")
    finally:
        try:
            os.remove(temporary)
        except OSError:
            pass


def _png_b64_to_image(text):
    try:
        raw = base64.b64decode(text)
    except Exception:
        return None
    image = QImage()
    if not image.loadFromData(QByteArray(raw), "PNG"):
        return None
    return image
