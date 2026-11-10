"""Host action execution; configuration persistence lives in config.py."""
from tfm_diagnostics import record_error
import os
import traceback
from . import config as _config

def run_composite_op(op_id):
    """Set the active layer's blend mode by its Krita id (setBlendingMode)."""
    if not isinstance(op_id, str) or not op_id:
        return
    try:
        doc = _config.Krita.instance().activeDocument()
    except Exception:
        return
    if doc is None:
        return
    node = doc.activeNode()
    if node is not None:
        try:
            node.setBlendingMode(op_id)
        except Exception as e:
            record_error("action.layer_blend", e)


def run_brush_blend(op_id):
    """Set the active brush painting blend mode (View.setCurrentBlendingMode)."""
    if not isinstance(op_id, str) or not op_id:
        return
    try:
        win = _config.Krita.instance().activeWindow()
    except Exception:
        return
    if win is None:
        return
    for view in win.views():
        try:
            view.setCurrentBlendingMode(op_id)
            return
        except Exception as error:
            record_error("action.view", error)
            continue


def run_brush_value(spec):
    """Set a quick brush value. spec = 'opacity:N' | 'flow:N' | 'size:N'."""
    if not isinstance(spec, str) or ":" not in spec:
        return
    kind, num = spec.split(":", 1)
    try:
        val = float(num)
    except (TypeError, ValueError):
        return
    try:
        win = _config.Krita.instance().activeWindow()
    except Exception:
        return
    if win is None:
        return
    for view in win.views():
        try:
            if kind == "opacity":
                view.setPaintingOpacity(val / 100.0)
            elif kind == "flow":
                view.setPaintingFlow(val / 100.0)
            elif kind == "size":
                view.setBrushSize(val)
            else:
                return
            return
        except Exception as error:
            record_error("action.view", error)
            continue


def run_set_color(hex_str, target):
    """Set the active foreground/background colour from a #rrggbb hex string."""
    if not isinstance(hex_str, str) or not hex_str.startswith("#"):
        return
    try:
        from .qtcompat import QColor
        from krita import ManagedColor
        qc = QColor(hex_str)
        if not qc.isValid():
            return
        col = ManagedColor.fromQColor(qc)
        win = _config.Krita.instance().activeWindow()
        if win is None:
            return
        for view in win.views():
            try:
                if target == "bg":
                    view.setBackGroundColor(col)
                else:
                    view.setForeGroundColor(col)
                return
            except Exception as error:
                record_error("action.view", error)
                continue
    except Exception as e:
        record_error("action.color", e)


def run_brush(name):
    """Set the active Krita brush preset by its name (View.activateResource)."""
    if not isinstance(name, str) or not name:
        return
    try:
        presets = _config.Krita.instance().resources("preset")
        resource = presets.get(name)
        if resource is None:
            # fallback: legacy configs stored the preset filename
            for p in presets.values():
                try:
                    if p.filename() == name:
                        resource = p
                        break
                except Exception:
                    continue
        if resource is None:
            return
        window = _config.Krita.instance().activeWindow()
        if window is None:
            return
        for view in window.views():
            try:
                view.activateResource(resource)
                return
            except Exception as error:
                record_error("action.view", error)
                continue
    except Exception as e:
        record_error("action.brush", e)


