#pragma once

#include <filter/kis_filter.h>

class KisFilterBackgroundRemoval final : public KisFilter
{
public:
    KisFilterBackgroundRemoval();

    static KoID id() { return KoID("tfm_background_removal", i18n("Background Removal")); }

    KisFilterConfigurationSP defaultConfiguration(KisResourcesInterfaceSP) const override;
    KisConfigWidget *createConfigurationWidget(QWidget *, const KisPaintDeviceSP, bool) const override;
    void processImpl(KisPaintDeviceSP, const QRect &, const KisFilterConfigurationSP, KoUpdater *) const override;
    QRect neededRect(const QRect &rect, const KisFilterConfigurationSP, int) const override { return rect; }
    QRect changedRect(const QRect &rect, const KisFilterConfigurationSP, int) const override { return rect; }
};
