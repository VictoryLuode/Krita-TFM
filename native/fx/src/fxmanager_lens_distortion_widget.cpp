#include "fxmanager_lens_distortion_widget.h"
#include "fxmanager_drag_spinbox.h"

#include <QCheckBox>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFormLayout>

#include <filter/kis_filter_configuration.h>
#include <KisGlobalResourcesInterface.h>
#include <klocalizedstring.h>

LensDistortionConfigurationWidget::LensDistortionConfigurationWidget(const QString &id, QWidget *parent)
    : KisConfigWidget(parent), m_id(id)
{
    auto *layout = new QFormLayout(this);
    m_mode = new QComboBox(this);
    m_mode->addItem(i18n("Radial"), QStringLiteral("radial"));
    m_mode->addItem(i18n("Horizontal"), QStringLiteral("horizontal"));
    layout->addRow(i18n("Mode"), m_mode);

    auto *distortion = new FxManagerDragSpinBox(this);
    distortion->setRange(-1.0, 1.0);
    distortion->setSingleStep(0.01);
    distortion->setDecimals(3);
    distortion->setValue(0.0);
    m_distortion = distortion;
    layout->addRow(i18n("Distortion"), distortion);
    connect(distortion, QOverload<double>::of(&QDoubleSpinBox::valueChanged), this, &KisConfigWidget::sigConfigurationItemChanged);

    auto *dispersion = new FxManagerDragSpinBox(this);
    dispersion->setRange(0.0, 1.0);
    dispersion->setSingleStep(0.01);
    dispersion->setDecimals(3);
    dispersion->setValue(0.0);
    m_dispersion = dispersion;
    layout->addRow(i18n("Dispersion"), dispersion);
    connect(dispersion, QOverload<double>::of(&QDoubleSpinBox::valueChanged), this, &KisConfigWidget::sigConfigurationItemChanged);

    m_jitter = new QCheckBox(i18n("Jitter"), this);
    layout->addRow(m_jitter);
    connect(m_jitter, &QCheckBox::toggled, this, &KisConfigWidget::sigConfigurationItemChanged);

    m_fit = new QCheckBox(i18n("Fit"), this);
    layout->addRow(m_fit);
    connect(m_fit, &QCheckBox::toggled, this, &KisConfigWidget::sigConfigurationItemChanged);
    connect(m_mode, QOverload<int>::of(&QComboBox::currentIndexChanged), this, [this] {
        updateModeVisibility();
        emit sigConfigurationItemChanged();
    });
    updateModeVisibility();
}

KisPropertiesConfigurationSP LensDistortionConfigurationWidget::configuration() const
{
    auto *c = new KisFilterConfiguration(m_id, 1, KisGlobalResourcesInterface::instance());
    c->setProperty("mode", m_mode->currentData().toString());
    c->setProperty("distortion", m_distortion->value());
    c->setProperty("dispersion", m_dispersion->value());
    c->setProperty("jitter", m_jitter->isChecked());
    c->setProperty("fit", m_fit->isChecked());
    return c;
}

void LensDistortionConfigurationWidget::setConfiguration(const KisPropertiesConfigurationSP c)
{
    if (!c) return;
    const int index = m_mode->findData(c->getString("mode", "radial"));
    m_mode->setCurrentIndex(index >= 0 ? index : 0);
    m_distortion->setValue(c->getDouble("distortion", 0.0));
    m_dispersion->setValue(c->getDouble("dispersion", 0.0));
    m_jitter->setChecked(c->getBool("jitter", false));
    m_fit->setChecked(c->getBool("fit", false));
    updateModeVisibility();
}

void LensDistortionConfigurationWidget::updateModeVisibility()
{
    const bool horizontal = m_mode && m_mode->currentData().toString() == QStringLiteral("horizontal");
    if (m_distortion) m_distortion->setVisible(!horizontal);
    if (m_dispersion) m_dispersion->setVisible(true);
    if (m_jitter) m_jitter->setVisible(!horizontal);
    if (m_fit) m_fit->setVisible(!horizontal);
}
