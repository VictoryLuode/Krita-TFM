#pragma once
#include <QCheckBox>
#include <QHash>
#include <QPair>
#include <QVector>
#include <kis_config_widget.h>
class QComboBox;
class QDoubleSpinBox;
class QPushButton;
struct TfmSlider { QString key,label; double min=0.0,max=1.0,value=0.0,step=0.01; int decimals=2; };
struct TfmPreset { QString key,label; QVector<QPair<QString,QString>> options; QString value; };
struct TfmToggle { QString key,label; bool value=false; };
// Colour is stored as "#rrggbb" so it round-trips through KisPropertiesConfiguration
// without depending on QVariant colour support.
struct TfmColor { QString key,label; QString value=QStringLiteral("#ffffff"); };
class TfmFilterWidget final : public KisConfigWidget {
 Q_OBJECT
public:
 explicit TfmFilterWidget(const QString &id,const QVector<TfmSlider> &sliders,QWidget *parent=nullptr,bool monochrome=false,
                                const QVector<TfmPreset> &presets={},const QVector<TfmToggle> &toggles={},
                                const QVector<TfmColor> &colors={});
 KisPropertiesConfigurationSP configuration() const override; void setConfiguration(const KisPropertiesConfigurationSP) override;
private: void refreshSwatch(const QString &key);
 void updateModeControls();
 QString m_id; QVector<TfmSlider> m_specs; QVector<TfmPreset> m_presets; QHash<QString,QDoubleSpinBox*> m_boxes;
 QHash<QString,QComboBox*> m_combos; QHash<QString,QCheckBox*> m_toggles; QHash<QString,QPushButton*> m_colors;
 QHash<QString,QString> m_colorValues; QCheckBox *m_mono=nullptr;
};
