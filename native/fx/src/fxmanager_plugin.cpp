#include "fxmanager_plugin.h"
#include "fxmanager_bloom.h"
#include "fxmanager_film_grain.h"
#include "fxmanager_lens_distortion.h"
#include "fxmanager_vignette.h"
#include "fxmanager_color_range_mask.h"
#include "fxmanager_clipboard_color_match.h"

#include "fxmanager_guided_color_match_filter.h"
#include "fxmanager_background_removal.h"
#include <kpluginfactory.h>
#include <filter/kis_filter_registry.h>

K_PLUGIN_FACTORY_WITH_JSON(FxManagerFactory, "kritatfm.json", registerPlugin<FxManagerPlugin>();)

FxManagerPlugin::FxManagerPlugin(QObject *p, const QVariantList &)
    : QObject(p)
{
    KisFilterRegistry::instance()->add(new KisFilterBloom);
    KisFilterRegistry::instance()->add(new KisFilterFilmGrain);
    KisFilterRegistry::instance()->add(new KisFilterLensDistortion);
    KisFilterRegistry::instance()->add(new KisFilterVignette);
    KisFilterRegistry::instance()->add(new KisFilterColorRangeMask);
    KisFilterRegistry::instance()->add(new KisFilterClipboardColorMatch);

    KisFilterRegistry::instance()->add(new KisFilterGuidedColorMatch);
    KisFilterRegistry::instance()->add(new KisFilterBackgroundRemoval);

}

#include "fxmanager_plugin.moc"
