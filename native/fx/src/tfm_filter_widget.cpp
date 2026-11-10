#include "tfm_filter_widget.h"
#include "filter_metadata.h"
#include "tfm_drag_spinbox.h"
#include <QCheckBox>
#include <QColorDialog>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QPushButton>
#include <QSignalBlocker>
#include <filter/kis_filter_configuration.h>
#include <KisGlobalResourcesInterface.h>
#include <klocalizedstring.h>

TfmFilterWidget::TfmFilterWidget(const QString &id,
        const QVector<TfmSlider> &sliders, QWidget *parent, bool monochrome,
        const QVector<TfmPreset> &presets, const QVector<TfmToggle> &toggles,
        const QVector<TfmColor> &colors)
    : KisConfigWidget(parent), m_id(id), m_specs(sliders), m_presets(presets)
{
    auto *layout = new QFormLayout(this);
    // Layout and translated labels stay handwritten; values/ranges have one source.
    for (auto &spec : m_specs) {
        if (const auto *meta = tfm_metadata::parameter(id, spec.key)) {
            spec.min = meta->min; spec.max = meta->max; spec.value = meta->value.toDouble();
        }
    }
    for (auto &spec : m_presets)
        if (const auto *meta = tfm_metadata::parameter(id, spec.key)) spec.value = meta->value.toString();
    for (const auto &preset : m_presets) {
        auto *combo = new QComboBox(this);
        for (const auto &option : preset.options) combo->addItem(option.second, option.first);
        combo->setCurrentIndex(combo->findData(preset.value));
        m_combos.insert(preset.key, combo);
        layout->addRow(preset.label, combo);
        connect(combo, QOverload<int>::of(&QComboBox::currentIndexChanged), this, [this]() {
            updateModeControls();
            emit sigConfigurationItemChanged();
        });
    }
    for (const auto &spec : m_specs) {
        auto *box = new TfmDragSpinBox(this);
        box->setRange(spec.min, spec.max); box->setSingleStep(spec.step); box->setDecimals(spec.decimals); box->setValue(spec.value);
        m_boxes.insert(spec.key, box); layout->addRow(spec.label, box);
        connect(box, QOverload<double>::of(&QDoubleSpinBox::valueChanged), this, &KisConfigWidget::sigConfigurationItemChanged);
    }
    for (const auto &toggle : toggles) {
        auto *check = new QCheckBox(toggle.label, this);
        const auto *meta = tfm_metadata::parameter(id, toggle.key);
        check->setChecked(meta ? meta->value.toBool() : toggle.value);
        m_toggles.insert(toggle.key, check);
        layout->addRow(check);
        connect(check, &QCheckBox::toggled, this, &KisConfigWidget::sigConfigurationItemChanged);
    }
    for (const auto &color : colors) {
        auto *button = new QPushButton(this);
        button->setMinimumWidth(72);
        m_colors.insert(color.key, button);
        const auto *meta = tfm_metadata::parameter(id, color.key);
        m_colorValues.insert(color.key, meta ? meta->value.toString() : color.value);
        layout->addRow(color.label, button);
        connect(button, &QPushButton::clicked, this, [this, key = color.key]() {
            const QColor picked = QColorDialog::getColor(QColor(m_colorValues.value(key)), this, i18n("Ray colour"));
            if (!picked.isValid()) return;
            m_colorValues.insert(key, picked.name());
            refreshSwatch(key);
            emit sigConfigurationItemChanged();
        });
        refreshSwatch(color.key);
    }
    if (monochrome) {
        m_mono = new QCheckBox(i18n("Monochrome"), this); m_mono->setChecked(true); layout->addRow(m_mono);
        connect(m_mono, &QCheckBox::toggled, this, &KisConfigWidget::sigConfigurationItemChanged);
    }
    updateModeControls();
}

void TfmFilterWidget::updateModeControls()
{
    // Halation exposes two mutually exclusive control groups. Keep the
    // inactive group visibly disabled so a click cannot appear to do nothing.
    if (QComboBox *mode = m_combos.value(QStringLiteral("glow_mode"))) {
        const bool channelMode = mode->currentData().toString() == QLatin1String("channels");
        for (auto it = m_toggles.cbegin(); it != m_toggles.cend(); ++it) it.value()->setEnabled(channelMode);
        for (auto it = m_colors.cbegin(); it != m_colors.cend(); ++it) it.value()->setEnabled(!channelMode);
        return;
    }
}

void TfmFilterWidget::refreshSwatch(const QString &key)
{
    QPushButton *button = m_colors.value(key);
    if (!button) return;
    const QColor value(m_colorValues.value(key));
    // Show the colour itself rather than its hex string: a swatch is read at a glance.
    button->setText(m_colorValues.value(key));
    button->setStyleSheet(QStringLiteral("QPushButton { background-color: %1; color: %2; border: 1px solid #00000060; padding: 2px 6px; }")
                              .arg(value.name(), value.lightnessF() > 0.55 ? QStringLiteral("#101010") : QStringLiteral("#f0f0f0")));
}

KisPropertiesConfigurationSP TfmFilterWidget::configuration() const
{
    auto *config = new KisFilterConfiguration(m_id, 1, KisGlobalResourcesInterface::instance());
    for (auto it = m_combos.cbegin(); it != m_combos.cend(); ++it) config->setProperty(it.key(), it.value()->currentData().toString());
    for (auto it = m_boxes.cbegin(); it != m_boxes.cend(); ++it) config->setProperty(it.key(), it.value()->value());
    for (auto it = m_toggles.cbegin(); it != m_toggles.cend(); ++it) config->setProperty(it.key(), it.value()->isChecked());
    for (auto it = m_colorValues.cbegin(); it != m_colorValues.cend(); ++it) config->setProperty(it.key(), it.value());
    if (m_mono) config->setProperty("monochrome", m_mono->isChecked());
    return config;
}

void TfmFilterWidget::setConfiguration(const KisPropertiesConfigurationSP config)
{
    if (!config) return;
    const QSignalBlocker blocker(this);
    for (auto it = m_combos.cbegin(); it != m_combos.cend(); ++it) {
        const QString fallback = (m_id == QLatin1String("tfm_halation") && it.key() == QLatin1String("glow_mode"))
            ? QStringLiteral("color") : QString();
        QString stored = config->getString(it.key(), fallback);
        const int index = it.value()->findData(stored);
        if (index >= 0) it.value()->setCurrentIndex(index);
    }
    for (const auto &spec : m_specs) {
        const double fallback = (m_id == QLatin1String("tfm_bloom") && spec.key == QLatin1String("diffusion")) ? 0.0 : spec.value;
        m_boxes.value(spec.key)->setValue(config->getDouble(spec.key, fallback));
    }
    for (auto it = m_toggles.cbegin(); it != m_toggles.cend(); ++it) {
        const bool fallback = m_id == QLatin1String("tfm_halation");
        it.value()->setChecked(config->getBool(it.key(), fallback));
    }
    for (auto it = m_colors.cbegin(); it != m_colors.cend(); ++it) {
        const QString fallback = (m_id == QLatin1String("tfm_halation") && it.key() == QLatin1String("glow_color"))
            ? QStringLiteral("#ff6b38") : QStringLiteral("#ffffff");
        const QString stored = config->getString(it.key(), fallback);
        m_colorValues.insert(it.key(), stored);
        refreshSwatch(it.key());
    }
    if (m_mono) m_mono->setChecked(config->getBool("monochrome", true));
    updateModeControls();
}
