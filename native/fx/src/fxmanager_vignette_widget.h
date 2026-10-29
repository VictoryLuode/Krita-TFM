#pragma once

#include <kis_config_widget.h>
#include <QHash>

class QDoubleSpinBox;

class VignetteConfigurationWidget final : public KisConfigWidget
{
    Q_OBJECT
public:
    explicit VignetteConfigurationWidget(const QString &id, QWidget *parent = nullptr);
    KisPropertiesConfigurationSP configuration() const override;
    void setConfiguration(const KisPropertiesConfigurationSP) override;
private:
    QString m_id;
    QHash<QString, QDoubleSpinBox *> m_boxes;
};
