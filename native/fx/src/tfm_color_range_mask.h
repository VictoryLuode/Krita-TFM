#pragma once

#include <filter/kis_filter.h>
#include <filter/kis_filter_configuration.h>
#include <kis_config_widget.h>

/// Alpha-only colour range mask: pixels near the target colour stay opaque.
class KisFilterColorRangeMask final : public KisFilter
{
public:
    KisFilterColorRangeMask();

    static KoID id() { return KoID("tfm_color_range_mask", i18n("Color Range Mask")); }

    KisFilterConfigurationSP defaultConfiguration(KisResourcesInterfaceSP resourcesInterface) const override;
    KisConfigWidget *createConfigurationWidget(QWidget *parent,
                                               const KisPaintDeviceSP device,
                                               bool useSelection) const override;
    void processImpl(KisPaintDeviceSP device,
                     const QRect &applyRect,
                     const KisFilterConfigurationSP config,
                     KoUpdater *progressUpdater) const override;
};
