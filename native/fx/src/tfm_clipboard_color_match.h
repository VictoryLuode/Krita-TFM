#pragma once

#include <filter/kis_filter.h>

class KisFilterClipboardColorMatch final : public KisFilter
{
public:
    KisFilterClipboardColorMatch();

    static KoID id() { return KoID("tfm_clipboard_color_match", i18n("Statistical Color Match")); }

    KisFilterConfigurationSP defaultConfiguration(KisResourcesInterfaceSP resourcesInterface) const override;
    KisConfigWidget *createConfigurationWidget(QWidget *parent,
                                               const KisPaintDeviceSP device,
                                               bool useSelection) const override;
    void processImpl(KisPaintDeviceSP device,
                     const QRect &applyRect,
                     const KisFilterConfigurationSP config,
                     KoUpdater *progressUpdater) const override;
};
