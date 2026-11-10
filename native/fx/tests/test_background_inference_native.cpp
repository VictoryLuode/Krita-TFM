#include "tfm_background_removal.h"
#include "tfm_processing.h"
#include <QApplication>
#include <QElapsedTimer>
#include <QDir>
#include <QFile>
#include <KoColorSpaceRegistry.h>
#include <KoResourcePaths.h>
#include <KisGlobalResourcesInterface.h>
#include <cmath>
#include <iostream>
#include <stdexcept>

static void check(bool ok,const char *text) { if(!ok) throw std::runtime_error(text); }
int main(int argc,char **argv) try {
    QApplication app(argc,argv);
    const QString runtime=[](){ QByteArray v=qgetenv("TFM_KRITA_RUNTIME"); if(v.isEmpty()) v=qgetenv("FXMANAGER_KRITA_RUNTIME"); return QString::fromLocal8Bit(v); }();
    app.addLibraryPath(runtime+"/lib");
    KoResourcePaths::addAssetDir("icc_profiles",runtime+"/share/color/icc/krita");
    const QRect area(0,0,64,64);
    auto *registry=KoColorSpaceRegistry::instance();
    const auto *cs=registry->colorSpace("RGBA","F32",registry->p709G10Profile());
    check(cs && cs->pixelSize()==16,"RGBA F32 unavailable");
    tfm::FloatRgbaImage original;original.width=64;original.height=64;original.pixels.resize(64*64*4);
    for(int y=0;y<64;++y) for(int x=0;x<64;++x) {
        auto *p=original.pixels.data()+4*(y*64+x);
        const bool object=(x-32)*(x-32)+(y-32)*(y-32)<20*20;
        p[0]=object ? 3.0f+float(x)/1000 : -2.0f+float(y)/1000;
        p[1]=object ? .6f : .15f;p[2]=object ? .1f : .4f;p[3]=.712345f+float(x)/10000;
    }
    KisFilterBackgroundRemoval filter;
    auto config=filter.defaultConfiguration(KisGlobalResourcesInterface::instance());
    config->setProperty("model",QStringLiteral("BiRefNet-lite-F16.gguf"));config->setProperty("backend",QStringLiteral("cpu"));
    config->setProperty("output_mode",QStringLiteral("cutout"));
    for(bool refine:{false,true}) {
        KisPaintDeviceSP device=new KisPaintDevice(cs);
        check(tfm::writeFloatImage(device,original,area),"fixture conversion failed");
        const auto input=tfm::readFloatImage(device,area);
        config->setProperty("foreground_mode",refine ? "refined_foreground" : "fast_mask");
        QElapsedTimer timer;timer.start();filter.processImpl(device,area,config,nullptr);
        const auto output=tfm::readFloatImage(device,area);
        bool changed=false,negative=false,hdr=false;
        for(int i=0;i<output.pixels.size();i+=4) {
            if(!refine) for(int c=0;c<3;++c) check(output.pixels[i+c]==input.pixels[i+c],"mask inference changed source colour bytes");
            const float alpha=output.pixels[i+3],before=input.pixels[i+3];
            changed|=alpha!=before;check(alpha>=0 && alpha<=before,"inference alpha outside source coverage");
            const double maskCode=double(alpha)/before*255;
            check(std::abs(maskCode-std::round(maskCode))<2e-5,"source alpha precision lost during mask composition");
            negative|=output.pixels[i]<0;hdr|=output.pixels[i]>1;
        }
        check(changed,"inference did not produce an applied mask");check(negative && hdr,"inference composition clipped HDR/negative source");
        std::cout<<(refine ? "refined" : "mask-only")<<" actual BiRefNet CPU ms="<<timer.elapsed()<<" PASS"<<std::endl;
        if(argc>1) {
            QFile file(QDir(QString::fromLocal8Bit(argv[1])).filePath(refine ? "refined.f32" : "mask-only.f32"));
            check(file.open(QIODevice::WriteOnly),"cannot save inference evidence");
            file.write(reinterpret_cast<const char*>(output.pixels.constData()),output.pixels.size()*sizeof(float));
        }
    }
    return 0;
} catch(const std::exception &e) { std::cerr<<"FAIL: "<<e.what()<<std::endl;return 1; }
