from pathlib import Path
import unittest

SOURCE = (Path(__file__).resolve().parents[1] / 'src' / 'fxmanager_background_removal.cpp').read_text(encoding='utf-8')


class BackgroundMaskOutputTests(unittest.TestCase):
    def test_default_and_unknown_modes_use_cutout(self):
        resolver = SOURCE.split('QString outputMode(', 1)[1].split('QString foregroundMode(', 1)[0]
        self.assertIn('getString("output_mode", QString::fromLatin1(kCutoutOutput))', resolver)
        self.assertIn('? QString::fromLatin1(kGrayscaleMaskOutput) : QString::fromLatin1(kCutoutOutput)', resolver)
        self.assertIn('config->setProperty("output_mode", QString::fromLatin1(kCutoutOutput))', SOURCE)

    def test_applied_snapshot_round_trips_selection(self):
        widget = SOURCE.split('class BackgroundRemovalConfigurationWidget', 1)[1].split('std::vector<uint8_t> rgbPixels', 1)[0]
        self.assertIn('m_outputMode->findData(outputMode(config))', widget)
        self.assertIn('config->setProperty("output_mode", m_outputMode->currentData().toString())', widget)
        self.assertIn('m_applied = editedConfiguration();', widget)
        self.assertIn('return m_applied ? m_applied : editedConfiguration();', widget)
        self.assertIn('independent of the original alpha', widget)

    def test_grayscale_disables_foreground_without_changing_its_selection(self):
        widget = SOURCE.split('class BackgroundRemovalConfigurationWidget', 1)[1].split('std::vector<uint8_t> rgbPixels', 1)[0]
        self.assertIn('QComboBox::currentIndexChanged', widget)
        self.assertGreaterEqual(widget.count('m_foregroundMode->setEnabled('), 2)
        self.assertIn('!= QString::fromLatin1(kGrayscaleMaskOutput)', widget)
        self.assertEqual(widget.count('emit sigConfigurationItemChanged()'), 1)

    def test_mask_branch_uses_processed_mask_and_skips_refinement(self):
        processing = SOURCE.split('visp::image_data mask = runtime.removeBackground', 1)[1]
        adjustment = processing.index('for (auto &value : values) value = lookup[value]')
        branch = processing.index('if (outputMode(config) == QString::fromLatin1(kGrayscaleMaskOutput))')
        refined = processing.index('} else if (foregroundMode(config)')
        self.assertLess(adjustment, branch)
        mask_branch = processing[branch:refined]
        self.assertIn('fxmanager::background_removal::grayscaleMaskImage(', mask_branch)
        self.assertIn('bytes.data(), image.width(), image.height()', mask_branch)
        self.assertNotIn('qAlpha', mask_branch)
        self.assertNotIn('image_estimate_foreground', mask_branch)
        helper = (Path(__file__).resolve().parents[1] / 'src' / 'fxmanager_background_mask.h').read_text(encoding='utf-8')
        self.assertIn('row[x] = qRgb(gray, gray, gray)', helper)
        self.assertIn('image_estimate_foreground', processing[refined:])


if __name__ == '__main__':
    unittest.main()
