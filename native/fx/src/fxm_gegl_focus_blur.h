#pragma once

#include <QRect>
#include <filter/kis_filter.h>
#include <kis_config_widget.h>

class QCheckBox;
class QComboBox;
class FxmBlurPointPreview;
class QDoubleSpinBox;
class QLabel;
class QSlider;
class QWidget;

class FxmGeglFocusBlur final : public KisFilter
{
public:
    FxmGeglFocusBlur();

    static KoID id() { return KoID("tfm_focus_blur", i18n("Focus Blur")); }
    static QRect DefaultReferenceFrame() { return QRect(0, 0, 2048, 2048); }
    static QRect resolveReferenceFrame(const KisFilterConfigurationSP &config);

    KisFilterConfigurationSP defaultConfiguration(KisResourcesInterfaceSP resourcesInterface) const override;
    QRect neededRect(const QRect &rect, const KisFilterConfigurationSP config, int lod) const override;
    QRect changedRect(const QRect &rect, const KisFilterConfigurationSP config, int lod) const override;
    bool configurationAllowedForMask(KisFilterConfigurationSP config) const override;
    KisConfigWidget *createConfigurationWidget(QWidget *parent, const KisPaintDeviceSP dev, bool useForMasks) const override;
    void processImpl(KisPaintDeviceSP device,
                     const QRect &rect,
                     const KisFilterConfigurationSP config,
                     KoUpdater *progressUpdater) const override;

    class Widget final : public KisConfigWidget
    {
    public:
        explicit Widget(const QRect &deviceFrame, const KisPaintDeviceSP &device, QWidget *parent = nullptr);
        void setConfiguration(const KisPropertiesConfigurationSP config) override;
        KisPropertiesConfigurationSP configuration() const override;

    private:
        void updateModeVisibility();

        FxmBlurPointPreview *m_pointPreview = nullptr;
        QRect m_deviceFrame;
        QRect m_frame;
        bool m_frameInitialized = false;
        QComboBox *m_blurTypeCombo = nullptr;
        QDoubleSpinBox *m_blurRadiusSpin = nullptr;
        QSlider *m_blurRadiusSlider = nullptr;
        QDoubleSpinBox *m_highlightFactorSpin = nullptr;
        QSlider *m_highlightFactorSlider = nullptr;
        QDoubleSpinBox *m_highlightLowSpin = nullptr;
        QSlider *m_highlightLowSlider = nullptr;
        QDoubleSpinBox *m_highlightHighSpin = nullptr;
        QSlider *m_highlightHighSlider = nullptr;
        QComboBox *m_shapeCombo = nullptr;
        QDoubleSpinBox *m_xSpin = nullptr;
        QSlider *m_xSlider = nullptr;
        QDoubleSpinBox *m_ySpin = nullptr;
        QSlider *m_ySlider = nullptr;
        QDoubleSpinBox *m_radiusSpin = nullptr;
        QSlider *m_radiusSlider = nullptr;
        QDoubleSpinBox *m_focusSpin = nullptr;
        QSlider *m_focusSlider = nullptr;
        QDoubleSpinBox *m_midpointSpin = nullptr;
        QSlider *m_midpointSlider = nullptr;
        QDoubleSpinBox *m_aspectSpin = nullptr;
        QSlider *m_aspectSlider = nullptr;
        QDoubleSpinBox *m_rotationSpin = nullptr;
        QSlider *m_rotationSlider = nullptr;
        QCheckBox *m_highQualityCheck = nullptr;
        QWidget *m_lensGroup = nullptr;
        QLabel *m_statusLabel = nullptr;
    };
};
