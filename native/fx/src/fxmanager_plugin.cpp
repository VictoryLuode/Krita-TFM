#include "fxmanager_plugin.h"
#include "fxmanager_background_removal.h"
#include "fxmanager_bloom.h"
#include "fxmanager_clipboard_color_match.h"
#include "fxmanager_color_range_mask.h"
#include "fxmanager_film_grain.h"
#include "fxmanager_guided_color_match_filter.h"
#include "fxmanager_lens_distortion.h"
#include "fxmanager_vignette.h"
#include "fxm_gegl_focus_blur.h"
#include "fxm_gegl_motion_blur.h"

#include <filter/kis_filter_registry.h>
#include <kpluginfactory.h>

K_PLUGIN_FACTORY_WITH_JSON(FxManagerPluginFactory, "kritatfm.json", registerPlugin<FxManagerPlugin>();)

FxManagerPlugin::FxManagerPlugin(QObject *parent, const QVariantList &)
    : QObject(parent)
{
    KisFilterRegistry *manager = KisFilterRegistry::instance();
    manager->add(new KisFilterBloom());
    manager->add(new KisFilterFilmGrain());
    manager->add(new KisFilterLensDistortion());
    manager->add(new KisFilterVignette());
    manager->add(new KisFilterColorRangeMask());
    manager->add(new KisFilterClipboardColorMatch());
    manager->add(new KisFilterGuidedColorMatch());
    manager->add(new KisFilterBackgroundRemoval());
    manager->add(new FxmGeglMotionBlur(FxmGeglMotionBlur::Variant::Circular));
    manager->add(new FxmGeglMotionBlur(FxmGeglMotionBlur::Variant::Zoom));
    manager->add(new FxmGeglFocusBlur());
}

#include "fxmanager_plugin.moc"
