#include "fxmanager_processing.h"
#include "fxmanager_bloom.h"
#include "fxmanager_film_grain.h"
#include "fxmanager_lens_distortion.h"
#include "fxmanager_vignette.h"
#include "fxmanager_color_range_mask.h"
#include "fxmanager_clipboard_color_match.h"
#include "fxmanager_guided_color_match_filter.h"
#include "fxmanager_background_removal.h"
#include <QApplication>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>
#include <QDomDocument>
#include <KisGlobalResourcesInterface.h>
#include <KoResourcePaths.h>
#include <filter/kis_filter_configuration.h>
#include <cmath>
#include <iostream>
#include <stdexcept>

static void require(bool ok, const QString &message) {
    if (!ok) throw std::runtime_error(message.toStdString());
}
static QJsonObject settings(const QString &filter, QJsonObject values) {
    return QJsonObject{{"filter_defaults", QJsonObject{{filter, values}}}};
}
static bool near(double a, double b) { return std::abs(a-b) < 1e-8; }

int main(int argc, char **argv) try {
    QApplication app(argc, argv);
    const QString runtime = QString::fromLocal8Bit(qgetenv("FXMANAGER_KRITA_RUNTIME"));
    const QString local = QString::fromLocal8Bit(qgetenv("KLOCALAPPDATA"));
    app.addLibraryPath(runtime + "/lib");
    KoResourcePaths::addAssetDir("icc_profiles", runtime + "/share/color/icc/krita");
    QDir().mkpath(local + "/resource/pykrita/fxmanager/data");
    QFile rc(local + "/kritarc");
    require(rc.open(QIODevice::WriteOnly|QIODevice::Truncate), "open isolated kritarc");
    rc.write("ResourceDirectory=" + (local + "/resource").toUtf8() + "\n"); rc.close();
    const QString path = local + "/resource/pykrita/fxmanager/data/settings.json";
    QFile::remove(path);

    KisFilterBloom bloom; KisFilterFilmGrain grain; KisFilterLensDistortion lens;
    KisFilterVignette vignette; KisFilterColorRangeMask mask;
    KisFilterClipboardColorMatch statistical; KisFilterGuidedColorMatch guided;
    KisFilterBackgroundRemoval background;
    auto defaults = [&](const KisFilter &f) { return f.defaultConfiguration(KisGlobalResourcesInterface::instance()); };
    auto write = [&](const QJsonObject &object) {
        QFile file(path); require(file.open(QIODevice::WriteOnly|QIODevice::Truncate), "write isolated settings");
        file.write(QJsonDocument(object).toJson(QJsonDocument::Compact)); file.close();
    };
    auto c = defaults(bloom);
    require(near(c->getDouble("threshold"), .7), "Bloom initial default mismatch");
    write(settings("fxmanager_bloom", {{"threshold", .31}, {"radius", 23}, {"strength", 1.25}, {"diffusion", 0.0}, {"softness", .42}}));
    c = defaults(bloom);
    require(near(c->getDouble("threshold"), .31) && near(c->getDouble("radius"),23) && near(c->getDouble("strength"),1.25) && near(c->getDouble("diffusion"),0) && near(c->getDouble("softness"),.42), "Bloom defaults not read from resource settings");
    write(settings("fxmanager_bloom", {{"threshold", .82}}));
    c = defaults(bloom);
    require(near(c->getDouble("threshold"),.82) && near(c->getDouble("softness"),0), "Bloom did not refresh settings file between calls");
    write(settings("fxmanager_bloom", {{"threshold", "0.2"}, {"radius", 999}, {"strength", true}, {"diffusion", -1}, {"softness", 1.5}}));
    c = defaults(bloom);
    require(near(c->getDouble("threshold"),.7) && near(c->getDouble("radius"),12) && near(c->getDouble("strength"),.65) && near(c->getDouble("diffusion"),1) && near(c->getDouble("softness"),0), "invalid Bloom values were not rejected");
    std::cout << "Bloom type/range validation, defaults and hot refresh PASS\n";

    write(settings("fxmanager_filmgrain", {{"preset", "custom"}, {"amount", .44}, {"size", 3.5}, {"seed", 91}, {"monochrome", false}}));
    c = defaults(grain);
    require(c->getString("preset") == "custom" && near(c->getDouble("amount"),.44) && near(c->getDouble("size"),3.5) && c->getInt("seed")==91 && !c->getBool("monochrome"), "Film Grain defaults failed");
    write(settings("fxmanager_lens_distortion", {{"mode", "horizontal"}, {"distortion", .21}, {"dispersion", .33}, {"jitter", true}, {"fit", true}}));
    c = defaults(lens);
    require(c->getString("mode")=="horizontal" && near(c->getDouble("distortion"),.21) && near(c->getDouble("dispersion"),.33) && c->getBool("jitter") && c->getBool("fit"), "Lens defaults failed");
    write(settings("fxmanager_vignette", {{"factor",.2},{"feather",.3},{"corner_roundness",.4},{"scale_x",1.2},{"scale_y",1.3},{"offset_x",-.2},{"offset_y",.1},{"angle",45}}));
    c = defaults(vignette);
    require(near(c->getDouble("factor"),.2) && near(c->getDouble("feather"),.3) && near(c->getDouble("corner_roundness"),.4) && near(c->getDouble("scale_x"),1.2) && near(c->getDouble("scale_y"),1.3) && near(c->getDouble("offset_x"),-.2) && near(c->getDouble("offset_y"),.1) && near(c->getDouble("angle"),45), "Vignette defaults failed");
    write(settings("fxmanager_color_range_mask", {{"channel","hue"},{"range_min",.2},{"range_max",.8},{"softness",.3},{"invert",true}}));
    c = defaults(mask);
    require(c->getString("channel")=="hue" && near(c->getDouble("range_min"),.2) && near(c->getDouble("range_max"),.8) && near(c->getDouble("softness"),.3) && c->getBool("invert"), "Color Range Mask defaults failed");
    write(settings("fxmanager_clipboard_color_match", {{"reference_source","file"},{"match_strength",.2},{"luminance",1.3},{"color_intensity",.7},{"fade",.8},{"tone_distribution",.4},{"tonal_color",.3},{"color_correlation",.6},{"gain_limit",3.0},{"shift_limit",20},{"variance_floor",4},{"gamut_protection",true}}));
    c = defaults(statistical);
    require(c->getString("reference_source")=="file" && near(c->getDouble("match_strength"),.2) && near(c->getDouble("luminance"),1.3) && near(c->getDouble("color_intensity"),.7) && near(c->getDouble("fade"),.8) && near(c->getDouble("tone_distribution"),.4) && near(c->getDouble("tonal_color"),.3) && near(c->getDouble("color_correlation"),.6) && near(c->getDouble("gain_limit"),3) && near(c->getDouble("shift_limit"),20) && near(c->getDouble("variance_floor"),4) && c->getBool("gamut_protection"), "Statistical Color Match defaults failed");
    write(settings("fxmanager_guided_color_match", {{"match_strength",.2},{"luminance",.3},{"chroma",1.4},{"shadow_color",.4},{"highlight_warmth",1.6},{"neutral_protection",.5},{"smoothness",.6}}));
    c = defaults(guided);
    require(near(c->getDouble("match_strength"),.2) && near(c->getDouble("luminance"),.3) && near(c->getDouble("chroma"),1.4) && near(c->getDouble("shadow_color"),.4) && near(c->getDouble("highlight_warmth"),1.6) && near(c->getDouble("neutral_protection"),.5) && near(c->getDouble("smoothness"),.6), "Guided Color Match defaults failed");
    write(settings("fxmanager_background_removal", {{"model","BiRefNet-dynamic-F16.gguf"},{"backend","gpu"},{"foreground_mode","fast_mask"}}));
    c = defaults(background);
    require(c->getString("model")=="BiRefNet-dynamic-F16.gguf" && c->getString("backend")=="gpu" && c->getString("foreground_mode")=="fast_mask", "Background Removal defaults failed");
    std::cout << "All eight production filters accept configured values PASS\n";

    // Existing independent filter configuration must remain untouched.
    c = defaults(bloom); c->setProperty("threshold", .123); c->setProperty("custom_existing", "preserve");
    write(settings("fxmanager_bloom", {{"threshold",.91},{"softness",.9}}));
    require(near(c->getDouble("threshold"),.123) && c->getString("custom_existing")=="preserve", "existing config was mutated");
    const QString xml = c->toXML(); KisFilterConfiguration restored("fxmanager_bloom", 1, KisGlobalResourcesInterface::instance()); restored.fromXML(xml);
    require(near(restored.getDouble("threshold"),.123) && restored.getString("custom_existing")=="preserve", "XML roundtrip changed existing config");
    require(near(restored.getDouble("softness"),0), "XML roundtrip unexpected settings overlay");
    write(settings("fxmanager_color_range_mask", {{"preserve_rgb",false}}));
    c = defaults(mask);
    require(c->getBool("preserve_rgb"), "unsupported preserve_rgb setting unexpectedly overlaid");
    std::cout << "Independent config non-overwrite and XML roundtrip PASS\n";
    return 0;
} catch (const std::exception &e) { std::cerr << "FAIL: " << e.what() << std::endl; return 1; }
