#pragma once

#include <filter/kis_filter.h>

class KisFilterVignette final : public KisFilter
{
public:
    KisFilterVignette();
    static KoID id() { return KoID("tfm_vignette", i18n("Vignette")); }
    KisFilterConfigurationSP defaultConfiguration(KisResourcesInterfaceSP) const override;
    KisConfigWidget *createConfigurationWidget(QWidget *, const KisPaintDeviceSP, bool) const override;
    void processImpl(KisPaintDeviceSP, const QRect &, const KisFilterConfigurationSP, KoUpdater *) const override;
};
