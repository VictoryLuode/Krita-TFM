#pragma once

#include <filter/kis_filter.h>

class KisFilterVibrance final : public KisFilter
{
public:
    KisFilterVibrance();
    static KoID id() { return KoID("tfm_vibrance", i18n("Vibrance")); }
    KisFilterConfigurationSP defaultConfiguration(KisResourcesInterfaceSP) const override;
    KisConfigWidget *createConfigurationWidget(QWidget *, const KisPaintDeviceSP, bool) const override;
    void processImpl(KisPaintDeviceSP, const QRect &, const KisFilterConfigurationSP, KoUpdater *) const override;
};
