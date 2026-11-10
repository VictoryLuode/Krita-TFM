#include "tfm_clipboard_color_match.h"
#include "tfm_guided_color_match_filter.h"
#include "tfm_guided_color_match.h"
#include "tfm_statistical_profile.h"
#include "tfm_processing.h"
#include <QApplication>
#include <KoColorSpaceRegistry.h>
#include <KoResourcePaths.h>
#include <KisGlobalResourcesInterface.h>
#include <set>
#include <cmath>
#include <iostream>
#include <stdexcept>

static void check(bool ok,const char *message) { if(!ok) throw std::runtime_error(message); }
static const QRect area(-3,7,1024,3);
static KisPaintDeviceSP fixture(const KoColorSpace *cs) {
    KisPaintDeviceSP device=new KisPaintDevice(cs);
    tfm::FloatRgbaImage image;
    image.width=area.width();image.height=area.height();image.pixels.resize(area.width()*area.height()*4);
    for(int y=0;y<area.height();++y) for(int x=0;x<area.width();++x) {
        float *p=image.pixels.data()+4*(y*area.width()+x);
        const float v=float(x)/1023;
        p[0]=y==2 ? -.3f+v*3 : .01f+v*.6f;
        p[1]=.03f+v*.4f;p[2]=.02f+v*.3f;p[3]=y==0 ? v : 1;
    }
    check(tfm::writeFloatImage(device,image,area),"fixture failed");return device;
}
static QByteArray bytes(KisPaintDeviceSP d) {
    QByteArray raw(area.width()*area.height()*d->pixelSize(),Qt::Uninitialized);
    d->readBytes(reinterpret_cast<quint8*>(raw.data()),area);return raw;
}
int main(int argc,char **argv) try {
    QApplication app(argc,argv);
    const QString runtime=[](){ QByteArray v=qgetenv("TFM_KRITA_RUNTIME"); if(v.isEmpty()) v=qgetenv("FXMANAGER_KRITA_RUNTIME"); return QString::fromLocal8Bit(v); }();
    app.addLibraryPath(runtime+"/lib");
    KoResourcePaths::addAssetDir("icc_profiles",runtime+"/share/color/icc/krita");
    auto *registry=KoColorSpaceRegistry::instance();
    tfm::guided::Lut lut;lut.valid=true;
    for(int r=0;r<lut.Size;++r) for(int g=0;g<lut.Size;++g) for(int b=0;b<lut.Size;++b) {
        lut.values[lut.index(r,g,b,0)]=float(r)*.95f/(lut.Size-1);
        lut.values[lut.index(r,g,b,1)]=float(g)/(lut.Size-1);
        lut.values[lut.index(r,g,b,2)]=float(b)/(lut.Size-1);
    }
    tfm::statistical::Accumulator sourceStats,referenceStats;
    for(int i=0;i<1024;++i) {
        sourceStats.add({.1+.7*i/1023,.02+.03*i/1023,.04-.02*i/1023,1});
        referenceStats.add({.12+.7*i/1023,.03+.03*i/1023,.035-.02*i/1023,1});
    }
    const auto sourceProfile=tfm::statistical::encodeProfile(sourceStats.finish());
    const auto targetProfile=tfm::statistical::encodeProfile(referenceStats.finish());
    for(int profileIndex=0;profileIndex<3;++profileIndex)
    for(const QString depth:{"U8","U16","F16","F32"}) for(int kind=0;kind<3;++kind) {
        const auto *profile=profileIndex==0 ? registry->p709G10Profile() : profileIndex==1 ? registry->p709SRGBProfile() : registry->p2020G10Profile();
        const auto *cs=registry->colorSpace("RGBA",depth,profile);
        check(cs && cs->colorDepthId().id()==depth,"required depth unavailable");
        KisFilterClipboardColorMatch stats;KisFilterGuidedColorMatch guided;
        KisFilter *filter=kind==0 ? static_cast<KisFilter*>(&guided) : static_cast<KisFilter*>(&stats);
        auto config=filter->defaultConfiguration(KisGlobalResourcesInterface::instance());
        config->setProperty("guided_lut_valid",true);config->setProperty("guided_lut",tfm::guided::encodeLut(lut));
        config->setProperty("reference_valid",true);config->setProperty("source_stats_valid",true);
        config->setProperty("statistical_version",kind==1 ? 1 : 4);
        config->setProperty("source_distribution",sourceProfile);config->setProperty("reference_distribution",targetProfile);
        config->setProperty("match_strength",.3);config->setProperty("gamut_protection",false);
        for(const QString channel:{"l","a","b"}) {
            config->setProperty("source_mean_"+channel,30000.0);config->setProperty("reference_mean_"+channel,30200.0);
            config->setProperty("source_std_"+channel,10000.0);config->setProperty("reference_std_"+channel,10000.0);
        }
        auto device=fixture(cs);const auto input=tfm::readFloatImage(device,area);
        const auto original=bytes(device);
        filter->processImpl(device,area,config,nullptr);
        check(bytes(device)!=original,"test configuration did not exercise output");
        const auto output=tfm::readFloatImage(device,area);
        float alphaError=0,lo=1e9f,hi=-1e9f;
        std::set<float> levels;
        for(int i=0;i<output.pixels.size();i+=4) {
            alphaError=std::max(alphaError,std::abs(output.pixels[i+3]-input.pixels[i+3]));
            lo=std::min(lo,output.pixels[i]);hi=std::max(hi,output.pixels[i]);
            if(i/4>=area.width() && i/4<2*area.width()) levels.insert(output.pixels[i]);
        }
        std::cout<<"profile="<<profileIndex<<" "<<depth.toStdString()<<" kind="<<kind<<" levels="<<levels.size()
                 <<" alpha="<<alphaError<<" range="<<lo<<","<<hi<<std::endl;
        check(alphaError==0,"transfer changed alpha precision");
        if(depth!="U8") check(levels.size()>512,"transfer quantized high depth");
        if(depth.startsWith('F')) check(lo<0 && hi>1,"transfer clipped extended values");
        auto tiled=fixture(cs);
        for(int x=area.left();x<=area.right();x+=127)
            filter->processImpl(tiled,QRect(x,area.top(),127,area.height()).intersected(area),config,nullptr);
        check(bytes(tiled)==bytes(device),"transfer differs across tiles");
        if(kind==0) {
            tfm::guided::Lut identity=lut;
            for(int r=0;r<lut.Size;++r) for(int g=0;g<lut.Size;++g) for(int b=0;b<lut.Size;++b)
                identity.values[lut.index(r,g,b,0)]=float(r)/(lut.Size-1);
            config->setProperty("guided_lut",tfm::guided::encodeLut(identity));
            auto zero=fixture(cs);const auto before=bytes(zero);
            filter->processImpl(zero,area,config,nullptr);
            check(before==bytes(zero),"identity LUT changed pixels");
        }
        if(kind!=0) {
            config->setProperty("match_strength",0.0);
            auto zero=fixture(cs); const auto before=bytes(zero);
            filter->processImpl(zero,area,config,nullptr);
            check(before==bytes(zero),"zero strength changed bytes");
        }
    }
    std::cout<<"Production guided/statistical precision PASS"<<std::endl;return 0;
} catch(const std::exception &e) { std::cerr<<"FAIL: "<<e.what()<<std::endl;return 1; }
