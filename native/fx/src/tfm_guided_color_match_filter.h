#pragma once

#include <filter/kis_filter.h>

class KisFilterGuidedColorMatch final : public KisFilter
{
public:
    KisFilterGuidedColorMatch();
    static KoID id() { return KoID("tfm_guided_color_match", i18n("Guided Color Match")); }
    KisFilterConfigurationSP defaultConfiguration(KisResourcesInterfaceSP resourcesInterface) const override;
    KisConfigWidget *createConfigurationWidget(QWidget *parent,
                                               const KisPaintDeviceSP device,
                                               bool useSelection) const override;
    void processImpl(KisPaintDeviceSP device, const QRect &applyRect,
                     const KisFilterConfigurationSP config,
                     KoUpdater *progressUpdater) const override;
};
