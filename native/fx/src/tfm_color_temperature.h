#pragma once

#include <filter/kis_filter.h>

class KisFilterColorTemperature final : public KisFilter
{
public:
    KisFilterColorTemperature();
    static KoID id() { return KoID("tfm_color_temperature", i18n("Color Temperature")); }
    KisFilterConfigurationSP defaultConfiguration(KisResourcesInterfaceSP) const override;
    KisConfigWidget *createConfigurationWidget(QWidget *, const KisPaintDeviceSP, bool) const override;
    void processImpl(KisPaintDeviceSP, const QRect &, const KisFilterConfigurationSP, KoUpdater *) const override;
};
