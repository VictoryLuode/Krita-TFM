#pragma once

#include <filter/kis_filter.h>

class KisFilterLensFlare final : public KisFilter
{
public:
    KisFilterLensFlare();
    static KoID id() { return KoID("tfm_lens_flare", i18n("Lens Flare")); }
    KisFilterConfigurationSP defaultConfiguration(KisResourcesInterfaceSP) const override;
    KisConfigWidget *createConfigurationWidget(QWidget *, const KisPaintDeviceSP, bool) const override;
    void processImpl(KisPaintDeviceSP, const QRect &, const KisFilterConfigurationSP, KoUpdater *) const override;
};

class KisFilterAnamorphicFlare final : public KisFilter
{
public:
    KisFilterAnamorphicFlare();
    static KoID id() { return KoID("tfm_anamorphic_flare", i18n("Anamorphic Flare")); }
    KisFilterConfigurationSP defaultConfiguration(KisResourcesInterfaceSP) const override;
    KisConfigWidget *createConfigurationWidget(QWidget *, const KisPaintDeviceSP, bool) const override;
    void processImpl(KisPaintDeviceSP, const QRect &, const KisFilterConfigurationSP, KoUpdater *) const override;
};
