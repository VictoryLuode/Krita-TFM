from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class BirefnetContractTests(unittest.TestCase):
    def test_native_filter_and_backend_sources_are_present(self):
        filter_source = (SRC / "fxmanager_background_removal.cpp").read_text(encoding="utf-8")
        filter_header = (SRC / "fxmanager_background_removal.h").read_text(encoding="utf-8")
        self.assertIn("KisFilterBackgroundRemoval", filter_source)
        self.assertIn("background_removal", filter_source)
        self.assertIn("filter/kis_filter.h", filter_header)
        self.assertTrue((SRC / "fxmanager_birefnet.cpp").is_file())
        self.assertIn("birefnet", filter_source)

    def test_only_birefnet_is_registered(self):
        plugin = (SRC / "fxmanager_plugin.cpp").read_text(encoding="utf-8")
        self.assertIn("KisFilterBackgroundRemoval", plugin)
        self.assertNotRegex(plugin, r"\b(?:sam|migan)_(?:load|compute)")
        self.assertNotRegex(plugin, r"KisFilter(?:Sam|Migan)")

    def test_build_wires_pinned_vision_backend(self):
        cmake = (SRC / "CMakeLists.txt").read_text(encoding="utf-8")
        build = (ROOT / "build.py").read_text(encoding="utf-8")
        self.assertIn("fxmanager_background_removal.cpp", cmake)
        self.assertIn("FXMANAGER_VISIONCPP_ROOT", cmake)
        self.assertIn("Missing existing library", build)
        self.assertIn("LINK_LIBRARIES", build)
        self.assertIn("BUILD_WITH_QT6:BOOL=OFF", build)
        self.assertIn("FXMANAGER_GGML_ROOT", cmake)
        self.assertTrue((ROOT / "third_party" / "visioncpp").is_dir())
        self.assertTrue((ROOT / "third_party" / "ggml").is_dir())

    def test_model_policy_keeps_lite_and_dynamic_only(self):
        source = (SRC / "fxmanager_background_removal.cpp").read_text(encoding="utf-8")
        self.assertIn("BiRefNet-lite-F16.gguf", source)
        self.assertIn("BiRefNet-dynamic-F16.gguf", source)
        self.assertIn("foreground_estimation", source)
        self.assertNotIn("MobileSAM", source)
        self.assertNotIn("MIGAN", source)


if __name__ == "__main__":
    unittest.main()
