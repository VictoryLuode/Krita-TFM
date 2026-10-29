// Exercise the production filter on Krita's real tiled paint device.
#include "fxmanager_bloom.h"
#include "fxmanager_processing.h"
#include <QApplication>
#include <KoColorSpaceRegistry.h>
#include <KoResourcePaths.h>
#include <KisGlobalResourcesInterface.h>
#include <filter/kis_filter_configuration.h>
#include <kis_paint_device.h>
#include <kis_transaction.h>
#include <algorithm>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <vector>

static void require(bool value, const char *message) {
    if (!value) throw std::runtime_error(message);
}
static const QRect area(-19, 13, 173, 131);
static KisPaintDeviceSP fixture() {
    KisPaintDeviceSP d = new KisPaintDevice(KoColorSpaceRegistry::instance()->rgb8());
    d->setX(-7); d->setY(9);
    QImage image(area.size(), QImage::Format_ARGB32);
    for (int y=0; y<image.height(); ++y)
        for (int x=0; x<image.width(); ++x) {
            const int v = 65 + (x*17+y*29+(x*y)%53)%150;
            image.setPixel(x,y,qRgba(v, std::min(245,v+17), std::max(0,v-23),
                                    (x+y)%11 == 0 ? 0 : 80+(x*3+y*7)%176));
        }
    fxmanager::writeImage(d,image,area);
    return d;
}
static QByteArray bytes(KisPaintDeviceSP d) {
    QByteArray result(area.width()*area.height()*d->pixelSize(), Qt::Uninitialized);
    d->readBytes(reinterpret_cast<quint8*>(result.data()),area);
    return result;
}
static std::vector<QRect> chunks() {
    std::vector<QRect> result;
    for (int y=area.top(); y<=area.bottom(); y+=37)
        for (int x=area.left(); x<=area.right(); x+=43)
            result.push_back(QRect(x,y,43,37).intersected(area));
    return result;
}
static void apply(KisPaintDeviceSP d, bool diffusion, int order, bool transaction) {
    KisFilterBloom filter;
    auto config=filter.defaultConfiguration(KisGlobalResourcesInterface::instance());
    config->setProperty("diffusion",diffusion ? 1.0 : 0.0);
    config->setProperty("radius",9.0);
    config->setProperty("threshold",0.27);
    config->setProperty("strength",0.55);
    config->setProperty("softness",0.35);
    auto regions=order ? chunks() : std::vector<QRect>{area};
    if (order<0) std::reverse(regions.begin(),regions.end());
    std::unique_ptr<KisTransaction> tx;
    if (transaction) tx.reset(new KisTransaction(d));
    for (const auto &r:regions) filter.processImpl(d,r,config,nullptr);
    if(tx) tx->end();
}
int main(int argc,char **argv) try {
    QApplication app(argc,argv);
    const QString runtime=QString::fromLocal8Bit(qgetenv("FXMANAGER_KRITA_RUNTIME"));
    app.addLibraryPath(runtime+"/lib");
    KoResourcePaths::addAssetDir("icc_profiles",runtime+"/share/color/icc/krita");
    bool allChunksMatch=true;
    for (bool diffusion:{false,true}) {
        auto whole=fixture(); const auto original=bytes(whole);
        apply(whole,diffusion,0,true); const auto expected=bytes(whole);
        require(expected!=original,"fixture must exercise bloom writes");
        for (int order:{1,-1}) {
            auto tiled=fixture(); apply(tiled,diffusion,order,true);
            const auto actual=bytes(tiled); int differences=0;
            for(int i=0;i<actual.size();++i) differences+=actual[i]!=expected[i];
            std::cout<<(diffusion?"diffusion":"legacy")<<" order="<<order
                     <<" different_bytes="<<differences<<std::endl;
            allChunksMatch &= actual==expected;
        }
        // With no active transaction old-data reads must use current pixels,
        // including a second application after a completed transaction.
        auto plain=fixture(); apply(plain,diffusion,0,false);
        require(bytes(plain)==expected,"no-transaction read differs from current data");
        apply(plain,diffusion,0,false); apply(whole,diffusion,0,true);
        require(bytes(plain)==bytes(whole),"second pass used stale transaction data");
        std::cout<<(diffusion?"diffusion":"legacy")<<" no-transaction and repeated-pass PASS"<<std::endl;
    }
    require(allChunksMatch,"transaction chunks differ from whole image");
    std::cout<<"production Bloom real-device regression PASS"<<std::endl;
    return 0;
} catch(const std::exception &e) {
    std::cerr<<"FAIL: "<<e.what()<<std::endl; return 1;
}
