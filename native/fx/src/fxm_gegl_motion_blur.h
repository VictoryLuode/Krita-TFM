#pragma once

#include <QRect>
#include <filter/kis_filter.h>
#include <kis_config_widget.h>

class FxmBlurPointPreview;
class QDoubleSpinBox;
class QLabel;
class QSlider;

class FxmGeglMotionBlur final : public KisFilter
{
public:
    enum class Variant {
        Circular,
        Zoom
    };

    explicit FxmGeglMotionBlur(Variant variant);

    static KoID circularId() { return KoID("tfm_motion_blur_circular", i18n("Circular Motion Blur")); }
    static KoID zoomId() { return KoID("tfm_motion_blur_zoom", i18n("Zoom Motion Blur")); }

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
        Widget(Variant variant, const QRect &deviceFrame, const KisPaintDeviceSP &device, QWidget *parent = nullptr);
        void setConfiguration(const KisPropertiesConfigurationSP config) override;
        KisPropertiesConfigurationSP configuration() const override;

    private:
        Variant m_variant;
        FxmBlurPointPreview *m_pointPreview = nullptr;
        QRect m_deviceFrame;
        QRect m_frame;
        bool m_frameInitialized = false;
        QDoubleSpinBox *m_centerXSpin = nullptr;
        QSlider *m_centerXSlider = nullptr;
        QDoubleSpinBox *m_centerYSpin = nullptr;
        QSlider *m_centerYSlider = nullptr;
        QDoubleSpinBox *m_primarySpin = nullptr;
        QSlider *m_primarySlider = nullptr;
        QLabel *m_statusLabel = nullptr;
    };

private:
    Variant m_variant;
};
