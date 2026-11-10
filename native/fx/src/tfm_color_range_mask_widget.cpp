#include "tfm_color_range_mask_widget.h"
#include "tfm_drag_spinbox.h"

#include <QCheckBox>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFormLayout>

#include <filter/kis_filter_configuration.h>
#include <KisGlobalResourcesInterface.h>
#include <klocalizedstring.h>

ColorRangeMaskConfigurationWidget::ColorRangeMaskConfigurationWidget(const QString &id, QWidget *parent)
    : KisConfigWidget(parent)
    , m_id(id)
{
    auto *layout = new QFormLayout(this);

    m_channel = new QComboBox(this);
    m_channel->addItem(i18n("灰色"), QStringLiteral("gray"));
    m_channel->addItem(QStringLiteral("R"), QStringLiteral("r"));
    m_channel->addItem(QStringLiteral("G"), QStringLiteral("g"));
    m_channel->addItem(QStringLiteral("B"), QStringLiteral("b"));
    m_channel->addItem(i18n("Hue"), QStringLiteral("hue"));
    m_channel->addItem(i18n("Saturation"), QStringLiteral("saturation"));
    m_channel->setToolTip(i18n("Hue uses a circular range in turns (0 to 1 = 0 to 360 degrees). "
                              "Min > Max wraps across red. Gray pixels (zero saturation, including black and white) "
                              "are excluded from hue selection; Invert includes them. "
                              "Saturation uses HSV saturation from 0 (gray) to 1 (fully saturated)."));
    layout->addRow(i18n("Channel"), m_channel);

    auto addRange = [&](const QString &key, const QString &label, double value, double maximum = 1.0) {
        auto *box = new TfmDragSpinBox(this);
        box->setRange(0.0, maximum);
        box->setSingleStep(0.01);
        box->setDecimals(2);
        box->setValue(value);
        m_boxes.insert(key, box);
        layout->addRow(label, box);
        connect(box, QOverload<double>::of(&QDoubleSpinBox::valueChanged),
                this, &KisConfigWidget::sigConfigurationItemChanged);
    };
    addRange(QStringLiteral("range_min"), i18n("Range Min"), 0.0);
    addRange(QStringLiteral("range_max"), i18n("Range Max"), 1.0);
    addRange(QStringLiteral("softness"), i18n("Softness"), 0.05, 0.5);

    m_invert = new QCheckBox(i18n("Invert"), this);
    layout->addRow(m_invert);
    connect(m_invert, &QCheckBox::toggled, this, &KisConfigWidget::sigConfigurationItemChanged);

    m_preserve = new QCheckBox(i18n("Preserve RGB, modify alpha only"), this);
    m_preserve->setChecked(true);
    m_preserve->setEnabled(false);
    m_preserve->setToolTip(i18n("RGB is always preserved; this filter modifies alpha only."));
    layout->addRow(m_preserve);
    connect(m_preserve, &QCheckBox::toggled, this, &KisConfigWidget::sigConfigurationItemChanged);

    connect(m_channel, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, &KisConfigWidget::sigConfigurationItemChanged);
}

KisPropertiesConfigurationSP ColorRangeMaskConfigurationWidget::configuration() const
{
    auto *c = new KisFilterConfiguration(m_id, 1, KisGlobalResourcesInterface::instance());
    c->setProperty("channel", m_channel->currentData().toString());
    for (auto it = m_boxes.cbegin(); it != m_boxes.cend(); ++it) c->setProperty(it.key(), it.value()->value());
    c->setProperty("invert", m_invert->isChecked());
    c->setProperty("preserve_rgb", m_preserve->isChecked());
    return c;
}

void ColorRangeMaskConfigurationWidget::setConfiguration(const KisPropertiesConfigurationSP c)
{
    if (!c) return;
    m_channel->blockSignals(true); m_invert->blockSignals(true); m_preserve->blockSignals(true);
    for (auto it = m_boxes.cbegin(); it != m_boxes.cend(); ++it) it.value()->blockSignals(true);
    const int index = m_channel->findData(c->getString("channel", "gray"));
    m_channel->setCurrentIndex(index >= 0 ? index : 0);
    for (auto it = m_boxes.cbegin(); it != m_boxes.cend(); ++it) {
        const double fallback = it.key() == QLatin1String("range_max") ? 1.0 :
                                it.key() == QLatin1String("softness") ? 0.05 : 0.0;
        it.value()->setValue(c->getDouble(it.key(), fallback));
    }
    m_invert->setChecked(c->getBool("invert", false));
    m_preserve->setChecked(true);
    m_channel->blockSignals(false); m_invert->blockSignals(false); m_preserve->blockSignals(false);
    for (auto it = m_boxes.cbegin(); it != m_boxes.cend(); ++it) it.value()->blockSignals(false);
}
