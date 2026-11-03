"""Layer color-space conversion planning, without a live Krita document."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "tfm_color_space", ROOT / "pykrita" / "tfm" / "color_space.py")
color_space = importlib.util.module_from_spec(spec)
spec.loader.exec_module(color_space)

TARGET = ("RGBA", "U8", "sRGB-elle-V2-srgbtrc.icc")
OTHER = ("RGBA", "F16", "Rec2020-elle-V4-g10.icc")


class Node:
    def __init__(self, kind, space, name, children=None):
        self.kind = kind
        self.space = space
        self.label = name
        self.children = children or []
        self.calls = 0
        self.stick = True

    def type(self):
        return self.kind

    def name(self):
        return self.label

    def colorModel(self):
        return self.space[0]

    def colorDepth(self):
        return self.space[1]

    def colorProfile(self):
        return self.space[2]

    def childNodes(self):
        return self.children

    def setColorSpace(self, model, depth, profile):
        self.calls += 1
        if self.stick:
            self.space = (model, depth, profile)
        return True


def test_default_reads_new_image_settings():
    seen = []

    def read_setting(group, key, default):
        seen.append((group, key, default))
        return {"colorModelDef": "RGBA", "colorDepthDef": "F32", "colorProfileDef": " custom.icc " }[key]

    assert color_space.default_color_space(read_setting) == ("RGBA", "F32", "custom.icc")
    assert {key for _, key, _ in seen} == {"colorModelDef", "colorDepthDef", "colorProfileDef"}
    assert {group for group, _, _ in seen} == {""}


def test_blank_settings_fall_back():
    assert color_space.default_color_space(lambda group, key, default: "  ") == TARGET
    assert color_space.format_color_space(*TARGET) == (
        "RGB with alpha, 8-bit integer, sRGB-elle-V2-srgbtrc.icc")


def test_matching_group_still_converts_nested_layer():
    paint = Node("paintlayer", OTHER, "Sketch")
    group = Node("grouplayer", TARGET, "Group", [paint])
    mask = Node("transparencymask", OTHER, "Mask", [])
    paint.children = [mask]
    root = Node("grouplayer", OTHER, "root", [group])
    assert [node.label for node in color_space.mismatched_layers(root, TARGET)] == ["Sketch"]
    color_space.apply_conversion(root, TARGET)
    assert group.calls == 0 and paint.calls == 1 and mask.calls == 0
    assert paint.space == TARGET


def test_converted_parent_covers_descendants():
    child = Node("paintlayer", OTHER, "Child")
    group = Node("grouplayer", OTHER, "Group", [child])
    root = Node("grouplayer", TARGET, "root", [group])
    color_space.apply_conversion(root, TARGET)
    assert group.calls == 1 and child.calls == 0
    assert group.space == TARGET


def test_unstick_parent_still_reaches_children():
    child = Node("paintlayer", OTHER, "Child")
    group = Node("filelayer", OTHER, "Linked", [child])
    group.stick = False
    root = Node("grouplayer", TARGET, "root", [group])
    color_space.apply_conversion(root, TARGET)
    assert group.calls == 1 and child.calls == 1
    assert child.space == TARGET


def test_skips_root_clone_and_matching_layers():
    clone = Node("clonelayer", OTHER, "Clone")
    done = Node("paintlayer", TARGET, "Done")
    root = Node("grouplayer", OTHER, "root", [clone, done])
    assert color_space.mismatched_layers(root, TARGET) == []
    color_space.apply_conversion(root, TARGET)
    assert clone.calls == 0 and done.calls == 0 and root.calls == 0


def test_target_problem_reports_missing_profile():
    class App:
        def colorModels(self):
            return ["RGBA"]

        def colorDepths(self, model):
            return ["U8"]

        def profiles(self, model, depth):
            return ["other.icc"]

    assert "not available" in color_space.target_problem(App(), TARGET)
    assert color_space.target_problem(type("App", (), {})(), TARGET) == ""


if __name__ == "__main__":
    test_default_reads_new_image_settings()
    test_blank_settings_fall_back()
    test_matching_group_still_converts_nested_layer()
    test_converted_parent_covers_descendants()
    test_unstick_parent_still_reaches_children()
    test_skips_root_clone_and_matching_layers()
    test_target_problem_reports_missing_profile()
    print("ok")
