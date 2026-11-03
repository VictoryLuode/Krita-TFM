#include "fxmanager_plugin.h"
#include "fxmanager_background_removal.h"
#include "fxmanager_bloom.h"
#include "fxmanager_clipboard_color_match.h"
#include "fxmanager_color_range_mask.h"
#include "fxmanager_color_temperature.h"
#include "fxmanager_film_grain.h"
#include "fxmanager_guided_color_match_filter.h"
#include "fxmanager_kuwahara.h"
#include "fxmanager_halation.h"
#include "fxmanager_flare.h"
#include "fxmanager_light_effects.h"
#include "fxmanager_lens_distortion.h"
#include "fxmanager_processing.h"
#include "fxmanager_vibrance.h"
#include "fxmanager_vignette.h"
#include "fxm_gegl_focus_blur.h"
#include "fxm_gegl_motion_blur.h"

#include <filter/kis_filter_registry.h>
#include <kpluginfactory.h>

K_PLUGIN_FACTORY_WITH_JSON(FxManagerPluginFactory, "kritatfm.json", registerPlugin<FxManagerPlugin>();)

namespace {

template<typename Filter>
void addEnabled(KisFilterRegistry *manager, const QString &id)
{
    if (!fxmanager::filterEnabled(id)) return;
    manager->add(new Filter());
}

} // namespace

FxManagerPlugin::FxManagerPlugin(QObject *parent, const QVariantList &)
    : QObject(parent)
{
    KisFilterRegistry *manager = KisFilterRegistry::instance();
    addEnabled<KisFilterBloom>(manager, QStringLiteral("tfm_bloom"));
    addEnabled<KisFilterFilmGrain>(manager, QStringLiteral("tfm_filmgrain"));
    addEnabled<KisFilterLensDistortion>(manager, QStringLiteral("tfm_lens_distortion"));
    addEnabled<KisFilterVignette>(manager, QStringLiteral("tfm_vignette"));
    addEnabled<KisFilterColorTemperature>(manager, QStringLiteral("tfm_color_temperature"));
    addEnabled<KisFilterVibrance>(manager, QStringLiteral("tfm_vibrance"));
    addEnabled<KisFilterKuwahara>(manager, QStringLiteral("tfm_kuwahara"));
    addEnabled<KisFilterHalation>(manager, QStringLiteral("tfm_halation"));
    addEnabled<KisFilterLensFlare>(manager, QStringLiteral("tfm_lens_flare"));
    addEnabled<KisFilterAnamorphicFlare>(manager, QStringLiteral("tfm_anamorphic_flare"));
    addEnabled<KisFilterLightRays>(manager, QStringLiteral("tfm_light_rays"));
    addEnabled<KisFilterLightLeaks>(manager, QStringLiteral("tfm_light_leaks"));
    addEnabled<KisFilterLightPatch>(manager, QStringLiteral("tfm_light_patch"));
    addEnabled<KisFilterColorRangeMask>(manager, QStringLiteral("tfm_color_range_mask"));
    addEnabled<KisFilterClipboardColorMatch>(manager, QStringLiteral("tfm_clipboard_color_match"));
    addEnabled<KisFilterGuidedColorMatch>(manager, QStringLiteral("tfm_guided_color_match"));
    addEnabled<KisFilterBackgroundRemoval>(manager, QStringLiteral("tfm_background_removal"));
    if (fxmanager::filterEnabled(QStringLiteral("tfm_motion_blur_circular"))) {
        manager->add(new FxmGeglMotionBlur(FxmGeglMotionBlur::Variant::Circular));
    }
    if (fxmanager::filterEnabled(QStringLiteral("tfm_motion_blur_zoom"))) {
        manager->add(new FxmGeglMotionBlur(FxmGeglMotionBlur::Variant::Zoom));
    }
    addEnabled<FxmGeglFocusBlur>(manager, QStringLiteral("tfm_focus_blur"));
}

#include "fxmanager_plugin.moc"
