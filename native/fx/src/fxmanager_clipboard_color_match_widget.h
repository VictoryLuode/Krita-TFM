#pragma once

#include <QByteArray>
#include <QHash>
#include <QImage>
#include <QString>

#include <kis_config_widget.h>
#include <kis_paint_device.h>
#include "fxmanager_statistical_transfer.h"

class QCheckBox;
class QComboBox;
class QDoubleSpinBox;
class QFormLayout;
class QLabel;
class QPushButton;
class QGroupBox;
class QSlider;
class QVBoxLayout;
class ClipboardColorMatchConfigurationWidget final : public KisConfigWidget
{
    Q_OBJECT
public:
    explicit ClipboardColorMatchConfigurationWidget(const QString &id,
                                                    const KisPaintDeviceSP &device,
                                                    QWidget *parent = nullptr);
    ~ClipboardColorMatchConfigurationWidget() override;

    KisPropertiesConfigurationSP configuration() const override;
    void setConfiguration(const KisPropertiesConfigurationSP config) override;

private:
    struct LabStats {
        double meanL = 0.0;
        double meanA = 0.0;
        double meanB = 0.0;
        double stdL = 0.0;
        double stdA = 0.0;
        double stdB = 0.0;
        int width = 0;
        int height = 0;
        bool valid = false;
        QString hash;
        fxmanager::statistical::Profile distribution;
    };
    void refreshClipboard();
    void reanalyzeTarget();
    void analyzeReference();
    void addRegionControls(QVBoxLayout *layout, const QString &prefix, const QString &title);
    void updateRegionControls(const QString &prefix);
    QRect analysisRect(const QRect &bounds, const QString &prefix) const;
    void addSliderControl(QFormLayout *layout, const QString &key, const QString &label, double value);
    void browseFile();

    void updateSourceUi();
    void setReferenceImage(const QImage &image, const QString &source, const QString &path = QString());
    bool calculateStats(const QImage &image, LabStats *stats) const;
    bool calculateDeviceStats(LabStats *stats) const;
    QRect deviceBounds() const;
    void updateReferenceUi();
    void addPercentControl(QFormLayout *layout, const QString &key, const QString &label, double value);

    QString m_id;
    KisPaintDeviceSP m_device;
    int m_statisticalVersion = 3;
    QComboBox *m_source = nullptr;
    QLabel *m_preview = nullptr;
    QLabel *m_reference = nullptr;
    QLabel *m_status = nullptr;
    QPushButton *m_refresh = nullptr;
    QPushButton *m_browse = nullptr;

    QHash<QString, QCheckBox *> m_regionEnabled;
    QHash<QString, QDoubleSpinBox *> m_regionBoxes;
    QImage m_referenceImage;
    QHash<QString, QDoubleSpinBox *> m_boxes;
    QCheckBox *m_preserveAlpha = nullptr;
    QCheckBox *m_gamutProtection = nullptr;
    QGroupBox *m_advanced = nullptr;
    QHash<QString, QSlider *> m_sliders;
    QString m_filePath;
    QString m_referenceSource = QStringLiteral("clipboard");
    QByteArray m_previewData;

    LabStats m_stats;
    LabStats m_sourceStats;
};
