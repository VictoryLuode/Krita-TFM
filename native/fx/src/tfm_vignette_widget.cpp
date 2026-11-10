#include "tfm_vignette_widget.h"
#include "tfm_drag_spinbox.h"

#include <QDoubleSpinBox>
#include <QFormLayout>
#include <filter/kis_filter_configuration.h>
#include <KisGlobalResourcesInterface.h>
#include <klocalizedstring.h>

VignetteConfigurationWidget::VignetteConfigurationWidget(const QString &id, QWidget *parent)
    : KisConfigWidget(parent), m_id(id)
{
    auto *layout = new QFormLayout(this);
    auto add = [&](const QString &key, const QString &label, double min, double max, double value, double step) {
        auto *box = new TfmDragSpinBox(this);
        box->setRange(min, max);
        box->setSingleStep(step);
        box->setDecimals(3);
        box->setValue(value);
        m_boxes.insert(key, box);
        layout->addRow(label, box);
        connect(box, QOverload<double>::of(&QDoubleSpinBox::valueChanged),
                this, &KisConfigWidget::sigConfigurationItemChanged);
    };

    add(QStringLiteral("factor"), i18n("Factor"), 0.0, 1.0, 1.0, 0.01);
    add(QStringLiteral("feather"), i18n("Feather"), 0.0, 1.0, 0.4, 0.01);
    add(QStringLiteral("corner_roundness"), i18n("Corner Roundness"), 0.0, 1.0, 1.0, 0.01);
    add(QStringLiteral("scale_x"), i18n("Scale X"), 0.0001, 4.0, 0.8, 0.01);
    add(QStringLiteral("scale_y"), i18n("Scale Y"), 0.0001, 4.0, 0.8, 0.01);
    add(QStringLiteral("offset_x"), i18n("Offset X"), -2.0, 2.0, 0.0, 0.01);
    add(QStringLiteral("offset_y"), i18n("Offset Y"), -2.0, 2.0, 0.0, 0.01);
    add(QStringLiteral("angle"), i18n("Angle"), -180.0, 180.0, 0.0, 1.0);
}

KisPropertiesConfigurationSP VignetteConfigurationWidget::configuration() const
{
    auto *c = new KisFilterConfiguration(m_id, 1, KisGlobalResourcesInterface::instance());
    for (auto it = m_boxes.cbegin(); it != m_boxes.cend(); ++it) {
        c->setProperty(it.key(), it.value()->value());
    }
    return c;
}

void VignetteConfigurationWidget::setConfiguration(const KisPropertiesConfigurationSP c)
{
    if (!c) return;
    const double factor = c->getDouble("factor", c->getDouble("intensity", 1.0));
    const double feather = c->getDouble("feather", c->getDouble("smoothness", 0.4));
    const double roundness = c->getDouble("corner_roundness", c->getDouble("roundness", 1.0));
    const QHash<QString, double> values = {
        {QStringLiteral("factor"), factor},
        {QStringLiteral("feather"), feather},
        {QStringLiteral("corner_roundness"), roundness},
        {QStringLiteral("scale_x"), c->getDouble("scale_x", 0.8)},
        {QStringLiteral("scale_y"), c->getDouble("scale_y", 0.8)},
        {QStringLiteral("offset_x"), c->getDouble("offset_x", 0.0)},
        {QStringLiteral("offset_y"), c->getDouble("offset_y", 0.0)},
        {QStringLiteral("angle"), c->getDouble("angle", 0.0)},
    };
    for (auto it = m_boxes.begin(); it != m_boxes.end(); ++it) {
        it.value()->blockSignals(true);
        it.value()->setValue(values.value(it.key(), it.value()->value()));
        it.value()->blockSignals(false);
    }
}

