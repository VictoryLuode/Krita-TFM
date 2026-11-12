"""Convert every layer in the open document to Krita's default color space.

The default is the model, depth, and profile used for new images
(``colorModelDef``, ``colorDepthDef``, ``colorProfileDef``). The image color
space is left alone: only layers in the layer stack are converted.
"""

try:
    from .i18n import tr
except ImportError:  # loaded as a flat module by offline unit tests
    def tr(english, chinese=None):
        return english


CONVERTIBLE = frozenset({
    "paintlayer",
    "grouplayer",
    "filelayer",
    "filterlayer",
    "filllayer",
    "vectorlayer",
    "referenceimageslayer",
})

_MODEL_LABELS = {
    "RGBA": "RGB with alpha",
    "GRAYA": "Grayscale with alpha",
    "CMYKA": "CMYK with alpha",
    "LABA": "L*a*b* with alpha",
    "YCbCrA": "YCbCr with alpha",
    "XYZA": "XYZ with alpha",
}
_DEPTH_LABELS = {
    "U8": "8-bit integer",
    "U16": "16-bit integer",
    "F16": "16-bit float",
    "F32": "32-bit float",
}
_TYPE_LABELS = {
    "paintlayer": "paint layer",
    "grouplayer": "group",
    "filelayer": "file layer",
    "filterlayer": "filter layer",
    "filllayer": "fill layer",
    "vectorlayer": "vector layer",
    "referenceimageslayer": "reference images",
    "clonelayer": "clone layer",
}

_FALLBACK = ("RGBA", "U8", "sRGB-elle-V2-srgbtrc.icc")


def default_color_space(read_setting=None):
    """Return ``(model, depth, profile)`` for new images."""
    if read_setting is None:
        from krita import Krita
        read_setting = Krita.instance().readSetting

    def value(key, fallback):
        try:
            raw = read_setting("", key, fallback)
        except Exception:
            return fallback
        if not isinstance(raw, str) or not raw.strip():
            return fallback
        return raw.strip()

    return (
        value("colorModelDef", _FALLBACK[0]),
        value("colorDepthDef", _FALLBACK[1]),
        value("colorProfileDef", _FALLBACK[2]),
    )


def format_color_space(model, depth, profile):
    return "{}, {}, {}".format(
        _MODEL_LABELS.get(model, model),
        _DEPTH_LABELS.get(depth, depth),
        profile,
    )


def node_type(node):
    try:
        return node.type() or ""
    except Exception:
        return ""


def space_of(node):
    try:
        model = node.colorModel() or ""
        depth = node.colorDepth() or ""
        profile = node.colorProfile() or ""
    except Exception:
        return None
    if not model or not depth or not profile:
        return None
    return (model, depth, profile)


def child_nodes(node):
    try:
        children = node.childNodes()
    except Exception:
        return []
    return list(children) if children else []


def node_name(node):
    try:
        name = node.name() or ""
    except Exception:
        name = ""
    name = name.strip()
    return name or "(unnamed)"


def describe_node(node):
    kind = node_type(node)
    label = _TYPE_LABELS.get(kind, kind or "layer")
    return "{} ({})".format(node_name(node), label)


def iter_convertible(root):
    def walk(node):
        if node_type(node) in CONVERTIBLE:
            yield node
        for child in child_nodes(node):
            yield from walk(child)

    for child in child_nodes(root):
        yield from walk(child)


def mismatched_layers(root, target):
    return [node for node in iter_convertible(root) if space_of(node) != target]


def apply_conversion(root, target):
    """Convert mismatched layers. A converted layer covers its descendants.

    Krita's layer conversion visits the whole subtree, but it refuses to start
    when the layer it is called on already matches. Matching groups are therefore
    walked so nested layers still get converted.
    """
    def walk(node):
        if node_type(node) in CONVERTIBLE and space_of(node) != target:
            try:
                ok = bool(node.setColorSpace(target[0], target[1], target[2]))
            except Exception:
                ok = False
            if ok and space_of(node) == target:
                return
        for child in child_nodes(node):
            walk(child)

    for child in child_nodes(root):
        walk(child)


def target_problem(app, target):
    """Return an error string when the default color space is not installed."""
    model, depth, profile = target
    try:
        models = list(app.colorModels())
    except Exception:
        models = None
    if models is not None and model not in models:
        return tr("The default color model is not available: {}.", "默认色彩模型不可用：{}。").format(model)
    try:
        depths = list(app.colorDepths(model))
    except Exception:
        depths = None
    if depths is not None and depth not in depths:
        return tr("The default color depth is not available: {}.", "默认色彩深度不可用：{}。").format(depth)
    try:
        profiles = list(app.profiles(model, depth))
    except Exception:
        profiles = None
    if profiles is not None and profile not in profiles:
        return tr("The default color profile is not available:\n{}", "默认色彩配置文件不可用：\n{}").format(profile)
    return ""


def _document_space(document):
    try:
        return (document.colorModel(), document.colorDepth(), document.colorProfile())
    except Exception:
        return None


def _join_names(nodes):
    shown = nodes[:8]
    text = ", ".join(describe_node(node) for node in shown)
    extra = len(nodes) - len(shown)
    if extra:
        text += " and {} more".format(extra)
    return text


def run_convert(parent=None):
    """Ask, then convert every layer in the active document. Returns True on success."""
    from krita import Krita
    from .menus.qtcompat import QApplication, QMessageBox, Qt

    app = Krita.instance()
    document = app.activeDocument()
    if document is None:
        QMessageBox.information(parent, tr("Convert Layers", "转换图层"), tr("Open a document first.", "请先打开文档。"))
        return False
    target = default_color_space(app.readSetting)
    problem = target_problem(app, target)
    if problem:
        QMessageBox.warning(parent, tr("Convert Layers", "转换图层"), problem)
        return False
    try:
        root = document.rootNode()
    except Exception:
        root = None
    if root is None:
        QMessageBox.information(parent, tr("Convert Layers", "转换图层"), tr("This document has no layer stack.", "此文档没有图层栈。"))
        return False
    pending = mismatched_layers(root, target)
    target_text = format_color_space(*target)
    if not pending:
        if any(iter_convertible(root)):
            message = tr("Every layer is already in your default color space:\n\n{}.", "所有图层已是默认色彩空间：\n\n{}。").format(target_text)
        else:
            message = tr("This document has no layers.", "此文档没有图层。")
        QMessageBox.information(parent, tr("Convert Layers", "转换图层"), message)
        return False
    names = [describe_node(node) for node in pending]
    preview = "\n".join("• " + name for name in names[:20])
    if len(names) > 20:
        preview += "\n• … and {} more".format(len(names) - 20)
    message = tr(
        "Convert every mismatched layer to your default color space?\n\n"
        "{}\n\n"
        "{} {} will be converted:\n{}\n\n"
        "Pixels are converted, and Undo can restore them.",
        "将所有不匹配的图层转换为默认色彩空间？\n\n"
        "{}\n\n"
        "将转换 {} {}：\n{}\n\n"
        "像素会被转换，可用撤销恢复。",
    ).format(
        target_text,
        len(pending),
        tr("layer", "图层") if len(pending) == 1 else tr("layers", "图层"),
        preview,
    )
    image = _document_space(document)
    if image and image != target:
        message += tr("\n\nThe image color space stays {}.", "\n\n图像色彩空间保持为 {}。").format(format_color_space(*image))
    buttons = QMessageBox.StandardButton
    if QMessageBox.question(
            parent, tr("Convert Layers", "转换图层"), message,
            buttons.Yes | buttons.No, buttons.Yes) != buttons.Yes:
        return False
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        apply_conversion(root, target)
        try:
            document.waitForDone()
        except Exception:
            pass
        try:
            document.refreshProjection()
        except Exception:
            pass
    finally:
        QApplication.restoreOverrideCursor()
    remaining = mismatched_layers(root, target)
    changed = len(pending) - len(remaining)
    if not remaining:
        QMessageBox.information(
            parent, "Convert Layers",
            tr("Converted {} {} to {}.", "已将 {} {} 转换为 {}。").format(
                changed, tr("layer", "图层") if changed == 1 else tr("layers", "图层"), target_text))
        return True
    detail = tr("Still in another color space: {}.", "仍处于其他色彩空间：{}。").format(_join_names(remaining))
    if any(node_type(node) == "filelayer" for node in remaining):
        detail += tr("\n\nFile layers keep the color space of the linked file.", "\n\n文件图层保留所链接文件的色彩空间。")
    if changed:
        QMessageBox.warning(
            parent, "Convert Layers",
            tr("Converted {} {}.\n\n{}", "已转换 {} {}。\n\n{}").format(
                changed, tr("layer", "图层") if changed == 1 else tr("layers", "图层"), detail))
        return True
    QMessageBox.warning(parent, tr("Convert Layers", "转换图层"), tr("Could not convert the layers.\n\n{}", "无法转换图层。\n\n{}").format(detail))
    return False
