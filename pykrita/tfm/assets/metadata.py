"""Read-only asset descriptions; safe to call from thumbnail workers."""
import os
from . import store, filter_asset, group_asset
from qtcompat import QImageReader

def _dimensions(path):
    size = QImageReader(path).size()
    return (size.width(),size.height()) if size.isValid() else None

def asset_tooltip(path, name=None):
    name = name or os.path.basename(path)
    lines = [os.path.splitext(name)[0]]
    sidecar = store.read_sidecar(path) or {}
    kind = sidecar.get("kind")
    if kind == filter_asset.KIND:
        filter_id = sidecar.get("filter") or "?"
        lines.append("Filter layer · {}".format(filter_id))
        lines.append("Saved as a filter preset (parameters included).")
    elif kind == group_asset.KIND:
        children = sidecar.get("children") or []
        lines.append("Layer group · {} item(s)".format(len(children)))
        skipped = sidecar.get("skipped") or []
        if skipped:
            lines.append("Skipped unsupported: {}".format(", ".join(skipped[:6])))
    elif kind == group_asset.PAINT_KIND:
        lines.append("Paint layer")
    else:
        size = _dimensions(path)
        if size is not None:
            lines.append("{} × {}".format(size[0], size[1]))
    masks = sidecar.get("masks") or []
    if masks:
        lines.append("Transparency mask × {}".format(len(masks)))
    meta = store.read_meta(path)
    if meta is not None:
        lines.append("Position {}, {}".format(meta[0], meta[1]))
    return "\n".join(lines)

