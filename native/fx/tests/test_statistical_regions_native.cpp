// Exercise the production widget with real Krita devices and XML configuration.
#include "tfm_clipboard_color_match.h"
#include "tfm_clipboard_color_match_widget.h"
#include "tfm_statistical_profile.h"
#include <QApplication>
#include <QCheckBox>
#include <QDoubleSpinBox>
#include <QPushButton>
#include <QSlider>
#include <KoColorSpaceRegistry.h>
#include <KoResourcePaths.h>
#include <KisGlobalResourcesInterface.h>
#include <filter/kis_filter_configuration.h>
#include <kis_default_bounds_base.h>
#include <kis_paint_device.h>
#include <iostream>
#include <memory>
#include <stdexcept>

using namespace tfm::statistical;
void check(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
    std::cout << "PASS " << message << std::endl;
}
class Bounds final : public KisDefaultBoundsBase {
public:
    QRect bounds() const override { return QRect(37, -19, 80, 40); }
    bool wrapAroundMode() const override { return false; }
    WrapAroundAxis wrapAroundModeAxis() const override { return WRAPAROUND_BOTH; }
    int currentLevelOfDetail() const override { return 0; }
    int currentTime() const override { return 0; }
    bool externalFrameActive() const override { return false; }
    void *sourceCookie() const override { return nullptr; }
};
QByteArray profile(KisPropertiesConfigurationSP c, const char *key) { return c->getProperty(key).toByteArray(); }
void number(QWidget &w, const QString &key, double value) { w.findChild<QDoubleSpinBox *>(key)->setValue(value); }
void region(QWidget &w, const QString &prefix, double x, double y, double width, double height) {
    w.findChild<QCheckBox *>(prefix + "_region_enabled")->setChecked(true);
    number(w, prefix+"_region_x", x); number(w, prefix+"_region_y", y);
    number(w, prefix+"_region_w", width); number(w, prefix+"_region_h", height);
}
KisFilterConfigurationSP xml(KisPropertiesConfigurationSP props) {
    KisFilterConfigurationSP result = new KisFilterConfiguration("tfm_clipboard_color_match", 1, KisGlobalResourcesInterface::instance());
    check(result->fromXML(props->toXML()), "real Krita XML roundtrip succeeds");
    return result;
}
int main(int argc, char **argv) try {
    QApplication app(argc, argv);
    const QString runtime = [](){ QByteArray v=qgetenv("TFM_KRITA_RUNTIME"); if(v.isEmpty()) v=qgetenv("FXMANAGER_KRITA_RUNTIME"); return QString::fromLocal8Bit(v); }();
    app.addLibraryPath(runtime + "/lib");
    KoResourcePaths::addAssetDir("icc_profiles", runtime + "/share/color/icc/krita");
    const auto *lab = KoColorSpaceRegistry::instance()->lab16();
    check(lab != nullptr, "real Lab16 colour engine is available");
    KisPaintDeviceSP device = new KisPaintDevice(lab);
    device->setDefaultBounds(new Bounds);
    QByteArray raw(80*40*8, '\0');
    Accumulator whole, selected;
    for (int y=0; y<40; ++y) for (int x=0; x<80; ++x) {
        auto *p = reinterpret_cast<quint16 *>(raw.data()+8*(80*y+x));
        p[0]=quint16(10000+x*500+y*70); p[1]=quint16(30000+x*20); p[2]=quint16(34000-y*30); p[3]=65535;
        Pixel pixel{p[0]/65535.0, (p[1]-32896.0)/65535.0, (p[2]-32896.0)/65535.0, 1};
        whole.add(pixel);
        if (x>=20 && x<60 && y>=10 && y<30) selected.add(pixel);
    }
    device->writeBytes(reinterpret_cast<const quint8 *>(raw.constData()),37,-19,80,40);
    KisFilterClipboardColorMatch filter;
    ClipboardColorMatchConfigurationWidget widget(filter.id().id(), device);
    int notifications=0;
    QObject::connect(&widget, &KisConfigWidget::sigConfigurationItemChanged, [&]{ ++notifications; });
    widget.setConfiguration(filter.defaultConfiguration(KisGlobalResourcesInterface::instance()));
    const auto initial=widget.configuration();
    check(profile(initial,"source_distribution")==encodeProfile(whole.finish()), "initial target snapshot uses nonzero device bounds");
    region(widget,"target",25,25,50,50);
    check(profile(widget.configuration(),"source_distribution")==profile(initial,"source_distribution"), "region edits freeze existing target statistics");
    widget.findChild<QPushButton *>("reanalyze_target")->click();
    const auto cropped=widget.configuration();
    check(profile(cropped,"source_distribution")==encodeProfile(selected.finish()), "explicit reanalysis samples exact nonzero-origin rectangle");
    // A saved reference profile exercises restoration without requiring a
    // separately built RGB colour-engine plugin in this standalone process.
    const auto referenceRegion=encodeProfile(whole.finish());
    auto referenceConfig=xml(cropped);
    referenceConfig->setProperty("reference_valid",true);
    referenceConfig->setProperty("reference_distribution",referenceRegion);
    widget.setConfiguration(referenceConfig);
    region(widget,"reference",25,25,50,50);
    check(profile(widget.configuration(),"reference_distribution")==referenceRegion, "reference region edits preserve frozen statistics");
    const auto saved=widget.configuration();
    auto restored=xml(saved);
    // Mutate the live input after saving to expose accidental automatic analysis.
    std::fill(raw.begin(),raw.end(),char(0));
    device->writeBytes(reinterpret_cast<const quint8 *>(raw.constData()),37,-19,80,40);
    ClipboardColorMatchConfigurationWidget reopened(filter.id().id(),device);
    int reopenSignals=0;
    QObject::connect(&reopened,&KisConfigWidget::sigConfigurationItemChanged,[&]{++reopenSignals;});
    reopened.setConfiguration(restored);
    auto next=reopened.configuration();
    check(profile(next,"source_distribution")==profile(saved,"source_distribution") && profile(next,"reference_distribution")==referenceRegion, "XML restore preserves both frozen profiles despite live input changes");
    for(const QString &prefix : {QStringLiteral("reference"),QStringLiteral("target")}) {
        check(next->getBool(prefix+"_region_enabled") && next->getDouble(prefix+"_region_x")==25 && next->getDouble(prefix+"_region_y")==25 && next->getDouble(prefix+"_region_w")==50 && next->getDouble(prefix+"_region_h")==50,"region controls survive real XML restore");
    }
    check(reopenSignals==0,"restoring controls emits no modification signal");
    reopened.findChild<QPushButton *>("analyze_reference")->click();
    check(profile(reopened.configuration(),"reference_distribution")==referenceRegion,"missing session reference retains saved analysis on explicit analyze");
    // Restore a larger rectangle into the same widget: old width limits must not clamp it.
    auto larger=xml(saved);
    for(const QString &prefix : {QStringLiteral("reference"),QStringLiteral("target")}) {
        larger->setProperty(prefix+"_region_x",0.0); larger->setProperty(prefix+"_region_y",0.0);
        larger->setProperty(prefix+"_region_w",100.0); larger->setProperty(prefix+"_region_h",100.0);
    }
    auto *box=reopened.findChild<QDoubleSpinBox *>("tone_distribution");
    auto *slider=reopened.findChild<QSlider *>("tone_distribution_slider");
    int sliderSignals=0;
    QObject::connect(slider,&QSlider::valueChanged,[&]{++sliderSignals;});
    box->blockSignals(true); larger->setProperty("tone_distribution",0.67);
    reopened.setConfiguration(larger);
    check(box->signalsBlocked() && sliderSignals==0,"restore preserves existing blockers and blocks child slider signals");
    check(reopened.configuration()->getDouble("target_region_w")==100 && reopened.configuration()->getDouble("reference_region_h")==100,"repeated restore expands previous region limits");
    box->blockSignals(false);
    reopened.findChild<QPushButton *>("reanalyze_target")->click();
    check(!reopened.configuration()->getBool("source_stats_valid" ) || profile(reopened.configuration(),"source_distribution")==profile(saved,"source_distribution"),"failed transparent target analysis preserves previous snapshot");
    check(profile(reopened.configuration(),"source_distribution")==profile(saved,"source_distribution"),"invalid explicit target analysis leaves saved profile unchanged");
    std::cout << "ALL NATIVE REGION AND FROZEN CONFIGURATION CHECKS PASSED" << std::endl;
    return 0;
} catch(const std::exception &e) { std::cerr << "FAIL " << e.what() << std::endl; return 1; }
