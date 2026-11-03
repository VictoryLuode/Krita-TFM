"""Serialize transparency masks attached to Asset Library layers."""

import base64

from . import pixels
from .store import AssetError

KIND = "transparencymask"


def has_transparency_mask(node):
    for child in _children(node):
        if _type(child) == KIND:
            return True
    return False


def append_masks(node, payload, state):
    """Capture supported masks on ``node`` into ``payload['masks']``."""
    if not isinstance(payload, dict):
        return
    masks = []
    for child in _children(node):
        kind = _type(child)
        if kind == KIND:
            item = capture_transparency(child, state)
            if item is not None:
                masks.append(item)
            continue
        if kind.endswith("mask"):
            skipped = state.setdefault("skipped", [])
            skipped.append(child.name() or kind)
    if masks:
        payload["masks"] = masks


def restore_masks(doc, layer, payload):
    if layer is None or not isinstance(payload, dict):
        return
    for item in payload.get("masks") or []:
        if not isinstance(item, dict) or item.get("kind") != KIND:
            continue
        _restore_transparency(doc, layer, item)


def capture_transparency(mask, state):
    payload = {
        "kind": KIND,
        "name": mask.name() or "Transparency Mask",
        "x": 0,
        "y": 0,
        "width": 0,
        "height": 0,
        "pixels": "",
    }
    _copy_common(mask, payload)
    try:
        bounds = mask.bounds()
    except Exception:
        bounds = None
    if bounds is None or bounds.isEmpty() or bounds.width() < 1 or bounds.height() < 1:
        return payload
    width = int(bounds.width())
    height = int(bounds.height())
    needed = width * height
    budget = int(state.get("budget") or 0)
    used = int(state.get("pixels") or 0)
    if budget and used + needed > budget:
        raise AssetError("That transparency mask is too large to save.")
    try:
        raw = bytes(mask.pixelData(bounds.x(), bounds.y(), width, height))
    except Exception as error:
        raise AssetError("Could not read that transparency mask.") from error
    if len(raw) < needed:
        raise AssetError("Could not read that transparency mask.")
    payload["x"] = int(bounds.x())
    payload["y"] = int(bounds.y())
    payload["width"] = width
    payload["height"] = height
    payload["pixels"] = base64.b64encode(raw[:needed]).decode("ascii")
    state["pixels"] = used + needed
    return payload


def _restore_transparency(doc, layer, payload):
    name = payload.get("name") or "Transparency Mask"
    try:
        mask = doc.createTransparencyMask(name)
    except Exception:
        mask = doc.createNode(name, "transparencymask")
    if mask is None:
        raise AssetError("Could not create a transparency mask.")
    if not layer.addChildNode(mask, None):
        raise AssetError("Could not add a transparency mask.")
    _apply_common(mask, payload)
    width = int(payload.get("width") or 0)
    height = int(payload.get("height") or 0)
    encoded = payload.get("pixels") or ""
    if width < 1 or height < 1 or not encoded:
        return
    try:
        raw = base64.b64decode(encoded)
    except Exception as error:
        raise AssetError("Could not restore a transparency mask.") from error
    needed = width * height
    if len(raw) < needed:
        raise AssetError("Could not restore a transparency mask.")
    x = int(payload.get("x") or 0)
    y = int(payload.get("y") or 0)
    if not mask.setPixelData(pixels.qbytearray_from(raw[:needed]), x, y, width, height):
        raise AssetError("Could not write a transparency mask.")


def _children(node):
    if node is None:
        return []
    try:
        return node.childNodes() or []
    except Exception:
        return []


def _type(node):
    try:
        return (node.type() or "").lower()
    except Exception:
        return ""


def _copy_common(node, payload):
    try:
        payload["opacity"] = int(node.opacity())
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
