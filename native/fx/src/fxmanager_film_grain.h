#pragma once

#include <filter/kis_filter.h>

class KisFilterFilmGrain final : public KisFilter
{
public:
    KisFilterFilmGrain();
    static KoID id() { return KoID("tfm_filmgrain", i18n("Film Grain")); }
    KisFilterConfigurationSP defaultConfiguration(KisResourcesInterfaceSP) const override;
    KisConfigWidget *createConfigurationWidget(QWidget *, const KisPaintDeviceSP, bool) const override;
    void processImpl(KisPaintDeviceSP, const QRect &, const KisFilterConfigurationSP, KoUpdater *) const override;
};
