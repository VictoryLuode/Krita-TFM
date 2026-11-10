// Executes production filters, conversion bridges and actual tiled paint devices.
#include "fxmanager_vibrance.h"
#include "fxmanager_color_temperature.h"
#include "fxmanager_processing.h"
#include "fxmanager_film_grain.h"
#include "fxmanager_vignette.h"
#include <kis_default_bounds_base.h>
#include <QApplication>
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QElapsedTimer>
#include <KoColorSpaceRegistry.h>
#include <KoResourcePaths.h>
#include <KisGlobalResourcesInterface.h>
#include <algorithm>
#include <cmath>
#include <iostream>
#include <set>
#include <stdexcept>

static void require(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
}
static const QRect area(-19, 13, 1024, 4);
class Bounds final : public KisDefaultBoundsBase {
public:
    QRect bounds() const override { return area; }
    bool wrapAroundMode() const override { return false; }
    WrapAroundAxis wrapAroundModeAxis() const override { return WRAPAROUND_BOTH; }
    int currentLevelOfDetail() const override { return 0; }
    int currentTime() const override { return 0; }
    bool externalFrameActive() const override { return false; }
    void *sourceCookie() const override { return nullptr; }
};
static QByteArray bytes(KisPaintDeviceSP d) {
    QByteArray result(area.width()*area.height()*d->pixelSize(), Qt::Uninitialized);
    d->readBytes(reinterpret_cast<quint8*>(result.data()),area);
    return result;
}
static KisPaintDeviceSP fixture(const KoColorSpace *cs, bool hdr) {
    KisPaintDeviceSP d = new KisPaintDevice(cs);
    d->setDefaultBounds(new Bounds);
    fxmanager::FloatRgbaImage image;
    image.width=area.width(); image.height=area.height(); image.pixels.resize(area.width()*area.height()*4);
    for(int y=0;y<area.height();++y) for(int x=0;x<area.width();++x) {
        auto *p=image.pixels.data()+4*(y*area.width()+x);
        const float v=float(x)/float(area.width()-1);
        p[0]=hdr && y==3 ? -0.2f+v*3.0f : 0.01f+v*0.6f;
        p[1]=0.02f+v*0.4f; p[2]=0.03f+v*0.2f;
        p[3]=y==0 ? 0.0f : y==1 ? v : 1.0f;
    }
    require(fxmanager::writeFloatImage(d,image,area),"fixture float conversion failed");
    return d;
}
int main(int argc,char **argv) try {
    QApplication app(argc,argv);
    require(argc>=3,"output path and mode required");
    const bool baseline=QString::fromLocal8Bit(argv[2])=="baseline";
    const QDir out(QString::fromLocal8Bit(argv[1]));
    const QString runtime=QString::fromLocal8Bit(qgetenv("FXMANAGER_KRITA_RUNTIME"));
    app.addLibraryPath(runtime+"/lib");
    KoResourcePaths::addAssetDir("icc_profiles",runtime+"/share/color/icc/krita");
    auto *registry=KoColorSpaceRegistry::instance();
    QJsonArray results;
    for(int profileIndex=0;profileIndex<3;++profileIndex)
    for(const QString depth : {"U8", "U16", "F16", "F32"}) {
        const auto *profile=profileIndex==0 ? registry->p709G10Profile() : profileIndex==1 ? registry->p709SRGBProfile() : registry->p2020G10Profile();
        const auto *cs=registry->colorSpace("RGBA",depth,profile);
        require(cs!=nullptr && cs->colorDepthId().id()==depth,"required RGBA depth/profile unavailable");
        for(int kind=0;kind<4;++kind) {
            KisFilterVibrance vibrance;
            KisFilterColorTemperature temperature;
            KisFilterFilmGrain grain;
            KisFilterVignette vignette;
            KisFilter *filters[]={&vibrance,&temperature,&grain,&vignette};
            KisFilter *filter=filters[kind];
            auto config=filter->defaultConfiguration(KisGlobalResourcesInterface::instance());
            const bool hdr=depth.startsWith('F');
            auto d=fixture(cs,hdr);
            const auto original=bytes(d);
            config->setProperty("preset",QStringLiteral("custom"));
            config->setProperty("amount",0.0);
            config->setProperty("factor",0.0);
            config->setProperty("blend",0.0);
            filter->processImpl(d,area,config,nullptr);
            const bool zero=original==bytes(d);
            if(!baseline) require(zero,"blend zero changed source bytes");
            config->setProperty("blend",1.0);
            config->setProperty("vibrance",0.0);
            filter->processImpl(d,area,config,nullptr);
            if(!baseline) require(original==bytes(d),"neutral parameters changed source bytes");
            config->setProperty("vibrance",30.0);
            config->setProperty("temperature",5700.0);
            config->setProperty("tint",0.0);
            config->setProperty("amount",0.01);
            config->setProperty("factor",0.2);
            QJsonArray timings;
            for(int i=0;i<7;++i) {
                d=fixture(cs,hdr);
                QElapsedTimer timer; timer.start();
                filter->processImpl(d,area,config,nullptr);
                timings.append(timer.nsecsElapsed()/1e6);
            }
            const auto expected=bytes(d);
            auto tiled=fixture(cs,hdr);
            for(int x=area.left();x<=area.right();x+=73)
                filter->processImpl(tiled,QRect(x,area.top(),73,area.height()).intersected(area),config,nullptr);
            require(bytes(tiled)==expected,"pointwise full/tiled results differ");
            const auto input=fxmanager::readFloatImage(fixture(cs,hdr),area);
            const auto output=fxmanager::readFloatImage(d,area);
            std::set<float> values;
            float maxAlpha=0, lo=1e9f, hi=-1e9f;
            for(int i=0;i<output.pixels.size();i+=4) {
                maxAlpha=std::max(maxAlpha,std::abs(input.pixels[i+3]-output.pixels[i+3]));
                lo=std::min(lo,output.pixels[i]); hi=std::max(hi,output.pixels[i]);
                if(i/4>=area.width()*2 && i/4<area.width()*3) values.insert(output.pixels[i]);
            }
            float inputLo=1e9f,inputHi=-1e9f;
            for(int i=0;i<input.pixels.size();i+=4) { inputLo=std::min(inputLo,input.pixels[i]); inputHi=std::max(inputHi,input.pixels[i]); }
            if(hdr && !(lo<0 && hi>1)) std::cerr<<"HDR diagnostic profile="<<profileIndex<<" kind="<<kind<<" input="<<inputLo<<","<<inputHi<<" output="<<lo<<","<<hi<<std::endl;
            if(!baseline) {
                require(maxAlpha<=1e-6f,"pointwise processing changed alpha");
                if(depth!="U8") require(values.size()>512,"high-depth gradient was quantized");
                if(hdr) require(lo<0 && hi>1,"HDR or negative values were clipped");
                require(d->colorSpace()==cs,"source color space/profile changed");
            }
            const QString names[]={"vibrance-","temperature-","grain-","vignette-"};
            const QString name=names[kind]+depth+QString("-profile%1").arg(profileIndex);
            QFile file(out.filePath(name+".raw")); require(file.open(QIODevice::WriteOnly),"cannot write output");
            file.write(expected);
            fxmanager::readImage(d,area).save(out.filePath(name+".png"));
            results.append(QJsonObject{{"filter",name},{"blend_zero_unchanged",zero},
                {"gradient_levels",int(values.size())},{"alpha_max_error",maxAlpha},
                {"minimum_red",lo},{"maximum_red",hi},{"milliseconds",timings}});
            std::cout<<name.toStdString()<<" levels="<<values.size()<<" alpha_error="<<maxAlpha<<" PASS"<<std::endl;
        }
    }
    QFile report(out.filePath("pixels-and-timing.json"));
    require(report.open(QIODevice::WriteOnly),"cannot save report"); report.write(QJsonDocument(results).toJson());
    return 0;
} catch(const std::exception &e) { std::cerr<<"FAIL: "<<e.what()<<std::endl; return 1; }
