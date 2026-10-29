#pragma once

#include <QHash>
#include <QString>

#include <kis_config_widget.h>

class QCheckBox;
class QComboBox;
class QDoubleSpinBox;
class QWidget;

/// Krita's native parameter panel for the Color Range Mask filter.
class ColorRangeMaskConfigurationWidget final : public KisConfigWidget
{
    Q_OBJECT
public:
    explicit ColorRangeMaskConfigurationWidget(const QString &id, QWidget *parent = nullptr);

    KisPropertiesConfigurationSP configuration() const override;
    void setConfiguration(const KisPropertiesConfigurationSP config) override;

private:
    QString m_id;
    QComboBox *m_channel = nullptr;
    QHash<QString, QDoubleSpinBox *> m_boxes;
    QCheckBox *m_invert = nullptr;
    QCheckBox *m_preserve = nullptr;
};
