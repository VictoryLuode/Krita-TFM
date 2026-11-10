#pragma once

#include <filter/kis_filter.h>

class KisFilterBloom final : public KisFilter
{
public:
    KisFilterBloom();
    static KoID id() { return KoID("tfm_bloom", i18n("Bloom")); }
    KisFilterConfigurationSP defaultConfiguration(KisResourcesInterfaceSP) const override;
    KisConfigWidget *createConfigurationWidget(QWidget *, const KisPaintDeviceSP, bool) const override;
    void processImpl(KisPaintDeviceSP, const QRect &, const KisFilterConfigurationSP, KoUpdater *) const override;
    QRect neededRect(const QRect &, const KisFilterConfigurationSP, int) const override;
    QRect changedRect(const QRect &, const KisFilterConfigurationSP, int) const override;
};
