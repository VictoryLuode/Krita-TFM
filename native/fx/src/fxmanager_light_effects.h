#pragma once

#include <filter/kis_filter.h>

// Procedural stand-in for G'MIC "Light Leaks". G'MIC composites a numbered
// entry from an external leak plate set; this filter synthesises the wash
// itself so the plugin ships no third-party images.
class KisFilterLightLeaks final : public KisFilter
{
public:
    KisFilterLightLeaks();
    static KoID id() { return KoID("tfm_light_leaks", i18n("Light Leaks")); }
    KisFilterConfigurationSP defaultConfiguration(KisResourcesInterfaceSP) const override;
    KisConfigWidget *createConfigurationWidget(QWidget *, const KisPaintDeviceSP, bool) const override;
    void processImpl(KisPaintDeviceSP, const QRect &, const KisFilterConfigurationSP, KoUpdater *) const override;
};

// Localised bright patches, following G'MIC light_patch: density, darkness, lightness.
class KisFilterLightPatch final : public KisFilter
{
public:
    KisFilterLightPatch();
    static KoID id() { return KoID("tfm_light_patch", i18n("Light Patch")); }
    KisFilterConfigurationSP defaultConfiguration(KisResourcesInterfaceSP) const override;
    KisConfigWidget *createConfigurationWidget(QWidget *, const KisPaintDeviceSP, bool) const override;
    void processImpl(KisPaintDeviceSP, const QRect &, const KisFilterConfigurationSP, KoUpdater *) const override;
};
