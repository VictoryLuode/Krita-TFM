#include "fxmanager_filter_widget.h"
#include "fxmanager_drag_spinbox.h"
#include <QCheckBox>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QSignalBlocker>
#include <filter/kis_filter_configuration.h>
#include <KisGlobalResourcesInterface.h>
#include <klocalizedstring.h>

FxManagerFilterWidget::FxManagerFilterWidget(const QString &id,
        const QVector<FxManagerSlider> &sliders, QWidget *parent, bool monochrome,
        const QVector<FxManagerPreset> &presets)
    : KisConfigWidget(parent), m_id(id), m_specs(sliders), m_presets(presets)
{
    auto *layout = new QFormLayout(this);
    for (const auto &preset : m_presets) {
        auto *combo = new QComboBox(this);
        for (const auto &option : preset.options) combo->addItem(option.second, option.first);
        combo->setCurrentIndex(combo->findData(preset.value));
        m_combos.insert(preset.key, combo);
        layout->addRow(preset.label, combo);
        connect(combo, QOverload<int>::of(&QComboBox::currentIndexChanged), this, &KisConfigWidget::sigConfigurationItemChanged);
    }
    for (const auto &spec : m_specs) {
        auto *box = new FxManagerDragSpinBox(this);
        box->setRange(spec.min, spec.max); box->setSingleStep(spec.step); box->setDecimals(spec.decimals); box->setValue(spec.value);
        m_boxes.insert(spec.key, box); layout->addRow(spec.label, box);
        connect(box, QOverload<double>::of(&QDoubleSpinBox::valueChanged), this, &KisConfigWidget::sigConfigurationItemChanged);
    }
    if (monochrome) {
        m_mono = new QCheckBox(i18n("Monochrome"), this); m_mono->setChecked(true); layout->addRow(m_mono);
        connect(m_mono, &QCheckBox::toggled, this, &KisConfigWidget::sigConfigurationItemChanged);
    }
}

KisPropertiesConfigurationSP FxManagerFilterWidget::configuration() const
{
    auto *config = new KisFilterConfiguration(m_id, 1, KisGlobalResourcesInterface::instance());
    for (auto it = m_combos.cbegin(); it != m_combos.cend(); ++it) config->setProperty(it.key(), it.value()->currentData().toString());
    for (auto it = m_boxes.cbegin(); it != m_boxes.cend(); ++it) config->setProperty(it.key(), it.value()->value());
    if (m_mono) config->setProperty("monochrome", m_mono->isChecked());
    return config;
}

void FxManagerFilterWidget::setConfiguration(const KisPropertiesConfigurationSP config)
{
    if (!config) return;
    const QSignalBlocker blocker(this);
    for (auto it = m_combos.cbegin(); it != m_combos.cend(); ++it) {
        const int index = it.value()->findData(config->getString(it.key(), QString()));
        if (index >= 0) it.value()->setCurrentIndex(index);
    }
    for (const auto &spec : m_specs) {
        const double fallback = (m_id == QLatin1String("tfm_bloom") && spec.key == QLatin1String("diffusion")) ? 0.0 : spec.value;
        m_boxes.value(spec.key)->setValue(config->getDouble(spec.key, fallback));
    }
    if (m_mono) m_mono->setChecked(config->getBool("monochrome", true));
}
