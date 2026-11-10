#pragma once

#include <kis_config_widget.h>

class QCheckBox;
class QComboBox;
class QDoubleSpinBox;

class LensDistortionConfigurationWidget final : public KisConfigWidget
{
    Q_OBJECT
public:
    explicit LensDistortionConfigurationWidget(const QString &id, QWidget *parent = nullptr);
    KisPropertiesConfigurationSP configuration() const override;
    void setConfiguration(const KisPropertiesConfigurationSP) override;
private:
    void updateModeVisibility();

    QString m_id;
    QComboBox *m_mode = nullptr;
    QDoubleSpinBox *m_distortion = nullptr;
    QDoubleSpinBox *m_dispersion = nullptr;
    QCheckBox *m_jitter = nullptr;
    QCheckBox *m_fit = nullptr;
};
