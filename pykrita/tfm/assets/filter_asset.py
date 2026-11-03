"""Serialize filter layers as Asset Library presets (filter id + parameters)."""

import base64

from krita import Krita, Selection

from ..menus.qtcompat import QColor, QImage
from . import mask_asset
from .store import AssetError

KIND = "filterlayer"


def is_filter_layer(node):
    if node is None:
        return False
    try:
        return (node.type() or "").lower() == "filterlayer"
    except Exception:
        return False


def capture(node, pixel_budget=64000000, state=None):
    try:
        filt = node.filter()
    except Exception as error:
        raise AssetError("Could not read that filter layer.") from error
    if filt is None:
        raise AssetError("That filter layer has no filter.")
    try:
        filter_id = filt.name()
    except Exception:
        filter_id = ""
    if not filter_id:
        raise AssetError("That filter layer has no filter.")
    properties = {}
    try:
        config = filt.configuration()
        raw = config.properties() if config is not None else {}
        for key, value in (raw or {}).items():
            properties[str(key)] = _jsonable(value)
    except Exception as error:
        raise AssetError("Could not read that filter's parameters.") from error
    payload = {
        "kind": KIND,
        "filter": str(filter_id),
        "properties": properties,
    }
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
    own_state = state
    if own_state is None:
        own_state = {"pixels": 0, "budget": int(pixel_budget), "skipped": []}
    mask_asset.append_masks(node, payload, own_state)
    if state is None and own_state.get("skipped"):
        payload["skipped"] = list(own_state["skipped"])
    return payload


def preview_image(node, edge=256):
    try:
        image = node.thumbnail(int(edge), int(edge))
        if image is not None and not image.isNull():
            return image
    except Exception:
        pass
    image = QImage(int(edge), int(edge), QImage.Format.Format_ARGB32)
    image.fill(QColor(52, 72, 108, 255))
    return image


def create_layer(doc, name, payload, parent, above):
    if parent is None:
        raise AssetError("Open a document first.")
    filter_id = str((payload or {}).get("filter") or "")
    if not filter_id:
        raise AssetError("That filter preset is incomplete.")
    filt = Krita.instance().filter(filter_id)
    if filt is None:
        raise AssetError('Filter "{}" is not available in this Krita.'.format(filter_id))
    properties = (payload or {}).get("properties") or {}
    if not isinstance(properties, dict):
        properties = {}
    _apply_properties(filt, properties)
    selection = Selection()
    try:
        selection.selectAll(doc.rootNode(), 255)
    except Exception as error:
        raise AssetError("Could not create a selection for the filter layer.") from error
    layer = doc.createFilterLayer(name or filter_id, filt, selection)
    if layer is None:
        raise AssetError("Could not create a filter layer.")
    live = None
    try:
        live = layer.filter()
    except Exception:
        live = None
    if live is not None:
        _apply_properties(live, properties)
    if "opacity" in payload:
        try:
            layer.setOpacity(int(payload["opacity"]))
        except Exception:
            pass
    if payload.get("blendingMode"):
        try:
            layer.setBlendingMode(str(payload["blendingMode"]))
        except Exception:
            pass
    if not parent.addChildNode(layer, above):
        raise AssetError("Could not add the filter layer.")
    mask_asset.restore_masks(doc, layer, payload)
    return layer


def _apply_properties(filt, properties):
    try:
        config = filt.configuration()
    except Exception:
        return
    if config is None:
        return
    for key, value in properties.items():
        try:
            config.setProperty(str(key), _from_jsonable(value))
        except Exception:
            continue
    try:
        filt.setConfiguration(config)
    except Exception:
        pass


def _jsonable(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return {"__base64__": base64.b64encode(bytes(value)).decode("ascii")}
    try:
        from ..menus.qtcompat import QByteArray
        if isinstance(value, QByteArray):
            return {"__base64__": base64.b64encode(bytes(value)).decode("ascii")}
    except Exception:
        pass
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    try:
        return float(value)
    except Exception:
        pass
    return str(value)


def _from_jsonable(value):
    if isinstance(value, dict) and set(value.keys()) == {"__base64__"}:
        try:
            return base64.b64decode(value["__base64__"])
        except Exception:
            return b""
    return value
