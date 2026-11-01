#pragma once

#include <filter/kis_filter.h>

class KisFilterHalation final : public KisFilter
{
public:
    KisFilterHalation();
    static KoID id() { return KoID("tfm_halation", i18n("Halation")); }
    KisFilterConfigurationSP defaultConfiguration(KisResourcesInterfaceSP) const override;
    KisConfigWidget *createConfigurationWidget(QWidget *, const KisPaintDeviceSP, bool) const override;
    QRect neededRect(const QRect &, const KisFilterConfigurationSP, int) const override;
    QRect changedRect(const QRect &, const KisFilterConfigurationSP, int) const override;
    void processImpl(KisPaintDeviceSP, const QRect &, const KisFilterConfigurationSP, KoUpdater *) const override;
};
