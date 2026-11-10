#include "tfm_plugin.h"
#include "tfm_background_removal.h"
#include "tfm_bloom.h"
#include "tfm_clipboard_color_match.h"
#include "tfm_color_range_mask.h"
#include "tfm_color_temperature.h"
#include "tfm_film_grain.h"
#include "tfm_guided_color_match_filter.h"
#include "tfm_kuwahara.h"
#include "tfm_halation.h"
#include "tfm_flare.h"
#include "tfm_lens_distortion.h"
#include "tfm_processing.h"
#include "tfm_vibrance.h"
#include "tfm_vignette.h"
#include "tfm_gegl_focus_blur.h"
#include "tfm_gegl_motion_blur.h"

#include <filter/kis_filter_registry.h>
#include <kpluginfactory.h>

K_PLUGIN_FACTORY_WITH_JSON(TfmPluginFactory, "kritatfm.json", registerPlugin<TfmPlugin>();)

namespace {

template<typename Filter>
void addEnabled(KisFilterRegistry *manager, const QString &id)
{
    if (!tfm::filterEnabled(id)) return;
    manager->add(new Filter());
}

} // namespace

TfmPlugin::TfmPlugin(QObject *parent, const QVariantList &)
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
    addEnabled<KisFilterColorRangeMask>(manager, QStringLiteral("tfm_color_range_mask"));
    addEnabled<KisFilterClipboardColorMatch>(manager, QStringLiteral("tfm_clipboard_color_match"));
    addEnabled<KisFilterGuidedColorMatch>(manager, QStringLiteral("tfm_guided_color_match"));
    addEnabled<KisFilterBackgroundRemoval>(manager, QStringLiteral("tfm_background_removal"));
    if (tfm::filterEnabled(QStringLiteral("tfm_motion_blur_circular"))) {
        manager->add(new TfmGeglMotionBlur(TfmGeglMotionBlur::Variant::Circular));
    }
    if (tfm::filterEnabled(QStringLiteral("tfm_motion_blur_zoom"))) {
        manager->add(new TfmGeglMotionBlur(TfmGeglMotionBlur::Variant::Zoom));
    }
    addEnabled<TfmGeglFocusBlur>(manager, QStringLiteral("tfm_focus_blur"));
}

#include "tfm_plugin.moc"
