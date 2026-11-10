#pragma once

#include <filter/kis_filter.h>

class KisFilterLensDistortion final : public KisFilter
{
public:
    KisFilterLensDistortion();
    static KoID id() { return KoID("tfm_lens_distortion", i18n("Lens Distortion")); }
    KisFilterConfigurationSP defaultConfiguration(KisResourcesInterfaceSP) const override;
    KisConfigWidget *createConfigurationWidget(QWidget *, const KisPaintDeviceSP, bool) const override;
    bool needsTransparentPixels(const KisFilterConfigurationSP, const KoColorSpace *) const override;
    QRect neededRect(const QRect &, const KisFilterConfigurationSP, int) const override;
    void processImpl(KisPaintDeviceSP, const QRect &, const KisFilterConfigurationSP, KoUpdater *) const override;
};
