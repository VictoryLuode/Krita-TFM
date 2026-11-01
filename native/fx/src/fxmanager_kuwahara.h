#pragma once

#include <filter/kis_filter.h>

class KisFilterKuwahara final : public KisFilter
{
public:
    KisFilterKuwahara();
    static KoID id() { return KoID("tfm_kuwahara", i18n("Kuwahara")); }
    KisFilterConfigurationSP defaultConfiguration(KisResourcesInterfaceSP) const override;
    KisConfigWidget *createConfigurationWidget(QWidget *, const KisPaintDeviceSP, bool) const override;
    QRect neededRect(const QRect &, const KisFilterConfigurationSP, int) const override;
    QRect changedRect(const QRect &, const KisFilterConfigurationSP, int) const override;
    void processImpl(KisPaintDeviceSP, const QRect &, const KisFilterConfigurationSP, KoUpdater *) const override;
};
