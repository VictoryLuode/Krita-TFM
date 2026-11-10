#include "fxm_gegl_focus_blur.h"
#include "fxm_gegl_motion_blur.h"
#include "fxmanager_processing.h"
#include "fxmanager_vulkan.h"
#include <QApplication>
#include <QLibrary>
#include <QFile>
#include <QFileInfo>
#include <QDir>
#include <QJsonDocument>
#include <QJsonObject>
#include <KoColorSpaceRegistry.h>
#include <KoResourcePaths.h>
#include <KisGlobalResourcesInterface.h>
#include <kis_default_bounds_base.h>
#include <kis_transaction.h>
#include <KoProgressUpdater.h>
#include <KoUpdater.h>
#include <KoFakeProgressProxy.h>
#include <cmath>
#include <iostream>
#include <stdexcept>

static void check(bool ok,const char *text) { if(!ok) throw std::runtime_error(text); }
static const QRect area(-7,9,53,37);
class Bounds final : public KisDefaultBoundsBase {
public:
    explicit Bounds(QRect rect):m_rect(rect) {}
    QRect bounds() const override { return m_rect; }
    bool wrapAroundMode() const override { return false; }
    WrapAroundAxis wrapAroundModeAxis() const override { return WRAPAROUND_BOTH; }
    int currentLevelOfDetail() const override { return 0; }
    int currentTime() const override { return 0; }
    bool externalFrameActive() const override { return false; }
    void *sourceCookie() const override { return nullptr; }
private:
    QRect m_rect;
};
static KisPaintDeviceSP fixture(const KoColorSpace *cs,const QRect &area=::area) {
    KisPaintDeviceSP d=new KisPaintDevice(cs);d->setDefaultBounds(new Bounds(area));
    fxmanager::FloatRgbaImage image;image.width=area.width();image.height=area.height();image.pixels.resize(area.width()*area.height()*4);
    for(int y=0;y<area.height();++y) for(int x=0;x<area.width();++x) {
        float *p=image.pixels.data()+4*(y*area.width()+x);
        p[0]=float(x)/52*3-.5f;p[1]=.1f+float(y)/80;p[2]=.05f+float(x)/200;
        p[3]=(x+y)%11==0 ? 0 : float(y)/36;
    }
    check(fxmanager::writeFloatImage(d,image,area),"fixture conversion failed");return d;
}
static QByteArray bytes(KisPaintDeviceSP d,const QRect &area=::area) {
    QByteArray raw(area.width()*area.height()*d->pixelSize(),Qt::Uninitialized);
    d->readBytes(reinterpret_cast<quint8*>(raw.data()),area);return raw;
}
int main(int argc,char **argv) try {
    QApplication app(argc,argv);
    const QString runtime=QString::fromLocal8Bit(qgetenv("FXMANAGER_KRITA_RUNTIME"));
    app.addLibraryPath(runtime+"/lib");
    KoResourcePaths::addAssetDir("icc_profiles",runtime+"/share/color/icc/krita");
    auto *registry=KoColorSpaceRegistry::instance();
    QLibrary candidate(QString::fromLocal8Bit(qgetenv("TFM_TEST_NATIVE_DLL")));
    candidate.setLoadHints(QLibrary::PreventUnloadHint);
    check(candidate.load(),"candidate DLL unavailable for isolated actual GPU test");
    FxManagerVulkan connection;
    FxmGeglFocusBlur focus;FxmGeglMotionBlur circular(FxmGeglMotionBlur::Variant::Circular),zoom(FxmGeglMotionBlur::Variant::Zoom);
    KisFilter *filters[]={&focus,&focus,&circular,&zoom};
    for(const QString depth:{"U8","U16","F16","F32"}) for(int kind=0;kind<4;++kind) {
        qputenv("TFM_BACKEND","cpu");qputenv("TFM_VULKAN_DISABLE","1");
        const auto *cs=registry->colorSpace("RGBA",depth,registry->p709G10Profile());
        check(cs && cs->colorDepthId().id()==depth,"depth unavailable");
        auto *filter=filters[kind]; auto config=filter->defaultConfiguration(KisGlobalResourcesInterface::instance());
        config->setProperty("frame_initialized",true);config->setProperty("frame_x",area.x());config->setProperty("frame_y",area.y());
        config->setProperty("frame_width",area.width());config->setProperty("frame_height",area.height());
        config->setProperty("blur_type",kind==1 ? "lens" : "gaussian");config->setProperty("blur_radius",2.0);
        config->setProperty("radius",0.0);config->setProperty("focus",0.0);config->setProperty("angle",12.0);config->setProperty("factor",.1);
        auto whole=fixture(cs);const auto original=bytes(whole);
        { KisTransaction tx(whole);filter->processImpl(whole,area,config,nullptr);tx.end(); }
        check(bytes(whole)!=original,"blur did not execute");
        const auto expected=fxmanager::readFloatImage(whole,area);
        auto tiled=fixture(cs);
        { KisTransaction tx(tiled);
            for(int y=area.top();y<=area.bottom();y+=19) for(int x=area.left();x<=area.right();x+=27)
                filter->processImpl(tiled,QRect(x,y,27,19).intersected(area),config,nullptr);
            tx.end();
        }
        const auto actual=fxmanager::readFloatImage(tiled,area);
        double error=0;for(int i=0;i<actual.pixels.size();++i) error=std::max(error,std::abs(double(actual.pixels[i])-expected.pixels[i]));
        std::cout<<depth.toStdString()<<" kind="<<kind<<" tile_error="<<error<<std::endl;
        check(error<1e-5,"blur whole/tile mismatch");
        if(depth.startsWith('F')) {
            bool negative=false,hdr=false;
            for(int i=0;i<expected.pixels.size();i+=4) { negative|=expected.pixels[i]<0;hdr|=expected.pixels[i]>1; }
            check(negative && hdr,"blur clipped extended range");
        }
        if(kind>=2 && depth=="F32") {
            qputenv("TFM_BACKEND","gpu");qputenv("TFM_VULKAN_DISABLE","0");
            auto gpu=fixture(cs);filter->processImpl(gpu,area,config,nullptr);
            QFile status(QDir(QFileInfo(fxmanager::settingsPath()).absolutePath()).filePath("backend-status.json"));
            check(status.open(QIODevice::ReadOnly),"missing backend evidence");
            const auto report=QJsonDocument::fromJson(status.readAll()).object();
            check(report["actual"].toString()=="gpu","GPU test silently fell back");
            const auto pixels=fxmanager::readFloatImage(gpu,area);double maxError=0;
            for(int i=0;i<pixels.pixels.size();++i) {
                const double delta=std::abs(double(pixels.pixels[i])-expected.pixels[i]);maxError=std::max(maxError,delta);
                check(delta<=2e-5+std::abs(expected.pixels[i])*2e-5,"float motion CPU/GPU mismatch");
            }
            std::cout<<"actual GPU "<<report["device"].toString().toStdString()<<" max_error="<<maxError<<std::endl;
            qputenv("TFM_BACKEND","cpu");qputenv("TFM_VULKAN_DISABLE","1");
        }
        if(depth=="F32") {
            const QRect large(-7,9,513,37);
            config->setProperty("frame_width",large.width());
            auto cancelled=fixture(cs,large); const auto initial=bytes(cancelled,large);
            KoFakeProgressProxy proxy;KoProgressUpdater progress(&proxy);
            progress.start();const auto sub=progress.startSubtask();bool reachedStaging=false;
            QObject::connect(sub.data(),&KoUpdater::sigProgress,&app,[&](int value) {
                if(value>0 && value<100) { reachedStaging=true; progress.cancel(); }
            });
            filter->processImpl(cancelled,large,config,sub.data());
            check(reachedStaging,"cancellation test did not reach staging");
            check(bytes(cancelled,large)==initial,"blur cancellation published a prefix");
        }
        config->setProperty("blur_radius",0.0);config->setProperty("angle",0.0);config->setProperty("factor",0.0);
        auto zero=fixture(cs);const auto before=bytes(zero);filter->processImpl(zero,area,config,nullptr);
        check(before==bytes(zero),"zero blur changed pixels");
    }
    connection.shutdown();
    std::cout<<"Focus/motion real-device and float GPU PASS"<<std::endl;return 0;
} catch(const std::exception &e) { std::cerr<<"FAIL: "<<e.what()<<std::endl;return 1; }
