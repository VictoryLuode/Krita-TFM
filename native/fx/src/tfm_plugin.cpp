#include "tfm_plugin.h"
#include "tfm_background_removal.h"
#include "tfm_bloom.h"
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

#include <QAction>
#include <QApplication>
#include <QFileInfo>
#include <QFileSystemWatcher>
#include <QTimer>
#include <QWidget>

K_PLUGIN_FACTORY_WITH_JSON(TfmPluginFactory, "kritatfm.json", registerPlugin<TfmPlugin>();)

namespace {

// KisFilterManager inserts actions named krita_filter_<id> on filterAdded, but
// has no filterRemoved path. Delete stale actions so disable clears the menu and
// re-enable does not leave a hidden duplicate beside a new insertFilter entry.
void purgeFilterMenuAction(const QString &id)
{
    const QString actionId = QStringLiteral("krita_filter_%1").arg(id);
    const QList<QAction *> actions = qApp->findChildren<QAction *>(actionId);
    for (QAction *action : actions) {
        if (!action || action->objectName() != actionId) continue;
        for (QWidget *widget : action->associatedWidgets()) {
            if (widget) widget->removeAction(action);
        }
        action->deleteLater();
    }
}

template<typename Filter>
void syncOne(KisFilterRegistry *manager, const QString &id)
{
    const bool want = tfm::filterEnabled(id);
    const bool have = manager->contains(id);
    if (want && !have) {
        purgeFilterMenuAction(id);
        manager->add(new Filter());
    } else if (!want && have) {
        manager->remove(id);
        purgeFilterMenuAction(id);
    }
}

void syncMotion(KisFilterRegistry *manager, const QString &id, TfmGeglMotionBlur::Variant variant)
{
    const bool want = tfm::filterEnabled(id);
    const bool have = manager->contains(id);
    if (want && !have) {
        purgeFilterMenuAction(id);
        manager->add(new TfmGeglMotionBlur(variant));
    } else if (!want && have) {
        manager->remove(id);
        purgeFilterMenuAction(id);
    }
}

} // namespace

TfmPlugin::TfmPlugin(QObject *parent, const QVariantList &)
    : QObject(parent)
{
    syncFilters();
    watchSettings();
}

void TfmPlugin::syncFilters()
{
    KisFilterRegistry *manager = KisFilterRegistry::instance();
    syncOne<KisFilterBloom>(manager, QStringLiteral("tfm_bloom"));
    syncOne<KisFilterFilmGrain>(manager, QStringLiteral("tfm_filmgrain"));
    syncOne<KisFilterLensDistortion>(manager, QStringLiteral("tfm_lens_distortion"));
    syncOne<KisFilterVignette>(manager, QStringLiteral("tfm_vignette"));
    syncOne<KisFilterColorTemperature>(manager, QStringLiteral("tfm_color_temperature"));
    syncOne<KisFilterVibrance>(manager, QStringLiteral("tfm_vibrance"));
    syncOne<KisFilterKuwahara>(manager, QStringLiteral("tfm_kuwahara"));
    syncOne<KisFilterHalation>(manager, QStringLiteral("tfm_halation"));
    syncOne<KisFilterLensFlare>(manager, QStringLiteral("tfm_lens_flare"));
    syncOne<KisFilterAnamorphicFlare>(manager, QStringLiteral("tfm_anamorphic_flare"));
    syncOne<KisFilterColorRangeMask>(manager, QStringLiteral("tfm_color_range_mask"));
    syncOne<KisFilterGuidedColorMatch>(manager, QStringLiteral("tfm_guided_color_match"));
    syncOne<KisFilterBackgroundRemoval>(manager, QStringLiteral("tfm_background_removal"));
    syncMotion(manager, QStringLiteral("tfm_motion_blur_circular"), TfmGeglMotionBlur::Variant::Circular);
    syncMotion(manager, QStringLiteral("tfm_motion_blur_zoom"), TfmGeglMotionBlur::Variant::Zoom);
    syncOne<TfmGeglFocusBlur>(manager, QStringLiteral("tfm_focus_blur"));
}

void TfmPlugin::watchSettings()
{
    const QString path = tfm::settingsPath();
    if (path.isEmpty()) return;
    const QString directory = QFileInfo(path).absolutePath();
    if (directory.isEmpty()) return;
    m_watcher = new QFileSystemWatcher(this);
    m_debounce = new QTimer(this);
    m_debounce->setSingleShot(true);
    m_debounce->setInterval(250);
    connect(m_debounce, &QTimer::timeout, this, &TfmPlugin::syncFilters);
    const auto schedule = [this](const QString &) {
        if (m_debounce) m_debounce->start();
    };
    connect(m_watcher, &QFileSystemWatcher::directoryChanged, this, schedule);
    connect(m_watcher, &QFileSystemWatcher::fileChanged, this, schedule);
    m_watcher->addPath(directory);
    if (QFileInfo::exists(path)) m_watcher->addPath(path);
}

#include "tfm_plugin.moc"
