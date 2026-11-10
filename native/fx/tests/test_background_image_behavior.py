from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


class BackgroundImageBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.filter_source = (SRC / "tfm_background_removal.cpp").read_text(encoding="utf-8")
        cls.runtime_source = (SRC / "tfm_birefnet.cpp").read_text(encoding="utf-8")

    def test_model_directory_has_runtime_fallback_when_resource_directory_is_empty(self):
        self.assertRegex(
            self.runtime_source,
            re.compile(r"resourceDirectory\(\).*?QStandardPaths::writableLocation", re.DOTALL),
            "models must still be discoverable when Krita resource parsing is unavailable",
        )

    def test_model_picker_is_populated_from_models_that_exist(self):
        self.assertIn("No BiRefNet model files found", self.filter_source)
        self.assertIn("availableModels()", self.filter_source)
        self.assertIn("addItem", self.filter_source)

    def test_missing_models_are_reported_as_filter_errors(self):
        self.assertIn("BiRefNet model not found", self.runtime_source)
        widget_source = self.filter_source.split("class BackgroundRemovalConfigurationWidget", 1)[1].split("};", 1)[0]
        self.assertNotIn("backendAvailable(", widget_source)
        self.assertNotIn("setBackend(", widget_source)
        self.assertNotIn("QMessageBox::critical", self.filter_source)
        self.assertIn("Qt::ConnectionType::QueuedConnection", self.filter_source)

    def test_gpu_selection_requires_successful_backend_initialization(self):
        self.assertIn("backend_type::gpu", self.filter_source)
        self.assertIn("visp::backend_init(m_backendType)", self.runtime_source)
        self.assertIn("if (!ensureBackend(&error)) throw", self.runtime_source)

    def test_birefnet_receives_rgb_semantics_and_preserves_original_alpha(self):
        self.assertIn("image_format::rgb_u8", self.filter_source)
        self.assertIn("originalAlpha", self.filter_source)
        self.assertIn("fullMaskPixels", self.filter_source)
        self.assertIn("foregroundPixels[pixel * 4 + 3]", self.filter_source)
        self.assertNotIn("image_format::bgra_u8", self.filter_source)

    def test_vulkan_loader_is_used_by_runtime_initialization(self):
        self.assertIn("loadVulkanBackend", self.runtime_source)
        self.assertIn("runtimeDirectory()", self.runtime_source)
        self.assertIn("ggml-vulkan.dll", self.runtime_source)
        self.assertIn("loadVulkanBackendLocked", self.runtime_source)

    def test_foreground_processing_exposes_fast_and_refined_modes(self):
        self.assertIn("foreground_mode", self.filter_source)
        self.assertIn("fast_mask", self.filter_source)
        self.assertIn("refined_foreground", self.filter_source)
        self.assertIn("foreground_estimation", self.filter_source)

    def test_refined_foreground_downsamples_large_inputs(self):
        self.assertIn("1024", self.filter_source)
        self.assertIn("image_scale", self.filter_source)
        self.assertIn("foregroundRgbData", self.filter_source)
        self.assertIn("foregroundMaskData", self.filter_source)
        self.assertIn("kRefinedForegroundMode", self.filter_source)

    def test_mask_controls_are_saved_and_default_to_existing_output(self):
        self.assertIn('background_apply_preview', self.filter_source)
        self.assertIn('connect(preview, &QPushButton::clicked', self.filter_source)
        widget = self.filter_source.split('class BackgroundRemovalConfigurationWidget', 1)[1].split('std::vector<uint8_t> rgbPixels', 1)[0]
        self.assertEqual(widget.count('emit sigConfigurationItemChanged()'), 1)
        self.assertIn('"preserve_foreground"', self.filter_source)
        self.assertIn('"mask_contrast"', self.filter_source)
        self.assertIn('config->setProperty("preserve_foreground", m_preserve->value())', self.filter_source)
        self.assertIn('config->setProperty("mask_contrast", m_contrast->value())', self.filter_source)
        self.assertIn('config->getInt("preserve_foreground", 0)', self.filter_source)
        self.assertIn('config->getInt("mask_contrast", 0)', self.filter_source)
        self.assertIn('0.5f + (alpha - 0.5f) * (1.0f + contrast / 100.0f)', self.filter_source)
        self.assertIn('QSpinBox *m_preserve', self.filter_source)
        self.assertIn('QSpinBox *m_contrast', self.filter_source)

    def test_mask_controls_have_full_width_synced_sliders(self):
        widget = self.filter_source.split("class BackgroundRemovalConfigurationWidget", 1)[1].split("std::vector<uint8_t> rgbPixels", 1)[0]
        self.assertIn("new QSlider(Qt::Orientation::Horizontal, this)", widget)
        self.assertIn('key + QStringLiteral("_slider")', widget)
        self.assertIn("row->addWidget(slider, 1)", widget)
        self.assertIn("connect(slider, &QSlider::valueChanged, value, &QSpinBox::setValue)", widget)
        self.assertIn("connect(value, QOverload<int>::of(&QSpinBox::valueChanged), slider, &QSlider::setValue)", widget)
        self.assertIn('slider->setRange(minimum, maximum)', widget)
        self.assertIn('setValue(config->getInt("preserve_foreground", 0))', widget)
        self.assertIn('setValue(config->getInt("mask_contrast", 0))', widget)

    def test_background_preview_controls_have_default_auto_preview_and_manual_apply(self):
        widget = self.filter_source.split("class BackgroundRemovalConfigurationWidget", 1)[1].split("std::vector<uint8_t> rgbPixels", 1)[0]
        self.assertIn('setObjectName(QStringLiteral("background_auto_preview"))', widget)
        self.assertIn('automaticPreview->setChecked(true)', widget)
        self.assertIn('connect(automaticPreview, &QCheckBox::toggled', widget)
        self.assertIn('if (m_autoPreview) applyEditedConfiguration()', widget)
        self.assertIn('connect(preview, &QPushButton::clicked, this, [this] { applyEditedConfiguration(); })', widget)
        self.assertIn('m_applied = editedConfiguration();', widget)
        self.assertIn('emit sigConfigurationItemChanged();', widget)

    def test_configuration_restore_blocks_preview_signals_and_resets_snapshot(self):
        widget = self.filter_source.split("class BackgroundRemovalConfigurationWidget", 1)[1].split("std::vector<uint8_t> rgbPixels", 1)[0]
        restore = widget.split('void setConfiguration(', 1)[1].split('KisPropertiesConfigurationSP configuration()', 1)[0]
        self.assertIn('const QSignalBlocker modelSignals(m_model)', restore)
        self.assertIn('const QSignalBlocker preserveSignals(m_preserve)', restore)
        self.assertIn('m_applied = editedConfiguration();', restore)
        self.assertNotIn('emit sigConfigurationItemChanged()', restore)



if __name__ == "__main__":
    unittest.main()
