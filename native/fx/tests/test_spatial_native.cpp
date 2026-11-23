#include "tfm_bloom.h"
#include "tfm_halation.h"
#include "tfm_kuwahara.h"
#include "tfm_flare.h"
#include "tfm_lens_distortion.h"
#include "tfm_color_range_mask.h"
#include "tfm_processing.h"
#include "tfm_guided_color_match.h"
#include "background_composite.h"
#include <QApplication>
#include <QDir>
#include <QLibrary>
#include <QJsonDocument>
#include <QJsonObject>
#include <QFile>
#include <QFileInfo>
#include <KoColorSpaceRegistry.h>
#include <KoResourcePaths.h>
#include <KisGlobalResourcesInterface.h>
#include <kis_default_bounds_base.h>
#include <kis_transaction.h>
#include <KoProgressUpdater.h>
#include <KoUpdater.h>
#include <KoFakeProgressProxy.h>
#include <thread>
#include <chrono>
#include <atomic>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <set>

static void check(bool ok,const char *message) { if(!ok) throw std::runtime_error(message); }
static const QRect area(-9,11,257,31);
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
    KisPaintDeviceSP d=new KisPaintDevice(cs); d->setDefaultBounds(new Bounds(area));
    tfm::FloatRgbaImage input;
    input.width=area.width(); input.height=area.height(); input.pixels.resize(area.width()*area.height()*4);
    for(int y=0;y<area.height();++y) for(int x=0;x<area.width();++x) {
        float *p=input.pixels.data()+4*(y*area.width()+x);
        p[0]=float(x)/256*2.5f-.25f; p[1]=.1f+float(x+y)/600; p[2]=.07f+float(x)/1400;
        p[3]=y==0 ? 0 : y<10 ? float(x)/256 : 1;
    }
    check(tfm::writeFloatImage(d,input,area),"fixture conversion failed"); return d;
}
static QByteArray bytes(KisPaintDeviceSP d,const QRect &area=::area) {
    QByteArray raw(area.width()*area.height()*d->pixelSize(),Qt::Uninitialized);
    d->readBytes(reinterpret_cast<quint8*>(raw.data()),area); return raw;
}
#ifndef TFM_RECORD_BASELINE
static void checkGpuStatus(const QString &filterId)
{
    QFile status(QFileInfo(tfm::settingsPath()).dir().filePath("backend-status.json"));
    check(status.open(QIODevice::ReadOnly), "GPU status missing");
    const auto record = QJsonDocument::fromJson(status.readAll()).object();
    check(record["actual"].toString() == "gpu" && record["filter"].toString() == filterId,
          "spatial regression did not execute on GPU");
}

static void checkHalationEdge(KisFilterHalation &filter, const KoColorSpace *space)
{
    const QRect box(0, 0, 64, 64);
    tfm::EncodedRgbaImage edge;
    edge.width = box.width();
    edge.height = box.height();
    edge.pixels.resize(edge.width * edge.height * 4);
    for (int y = 0; y < edge.height; ++y) {
        for (int x = 0; x < edge.width; ++x) {
            float *pixel = edge.pixels.data() + 4 * (y * edge.width + x);
            std::fill_n(pixel, 3, x >= edge.width / 2 ? 1.f : 0.f);
            pixel[3] = 1.f;
        }
    }
    auto config = filter.defaultConfiguration(KisGlobalResourcesInterface::instance());
    config->setProperty("threshold", .75);
    config->setProperty("quality", 32);
    config->setProperty("glow_mode", "channels");
    for (int radius : {3, 24}) {
        config->setProperty("radius", radius);
        QVector<float> reference;
        for (bool gpu : {false, true}) {
            qputenv("TFM_BACKEND", gpu ? "gpu" : "cpu");
            qputenv("TFM_VULKAN_DISABLE", gpu ? "0" : "1");
            KisPaintDeviceSP device = new KisPaintDevice(space);
            device->setDefaultBounds(new Bounds(box));
            check(tfm::writeEncodedImage(device, edge, box), "halation edge fixture failed");
            KisTransaction tx(device);
            filter.processImpl(device, box, config, nullptr);
            tx.end();
            const auto result = tfm::readEncodedImage(device, box).pixels;
            if (gpu) {
                checkGpuStatus(filter.id().id());
                for (int i = 0; i < result.size(); ++i)
                    check(std::abs(reference[i] - result[i]) < .0001, "halation edge CPU/GPU mismatch");
            } else {
                reference = result;
                check(result != edge.pixels, "halation edge was not processed");
            }
        }
    }
    qputenv("TFM_BACKEND", "cpu");
    qputenv("TFM_VULKAN_DISABLE", "1");
}
#endif

int main(int argc,char **argv) try {
    QApplication app(argc,argv);
    const QString runtime=[](){ QByteArray v=qgetenv("TFM_KRITA_RUNTIME"); if(v.isEmpty()) v=qgetenv("FXMANAGER_KRITA_RUNTIME"); return QString::fromLocal8Bit(v); }();
    app.addLibraryPath(runtime+"/lib");
    KoResourcePaths::addAssetDir("icc_profiles",runtime+"/share/color/icc/krita");
#ifndef TFM_RECORD_BASELINE
    QLibrary candidate(QString::fromLocal8Bit(qgetenv("TFM_TEST_NATIVE_DLL")));
    candidate.setLoadHints(QLibrary::PreventUnloadHint);
    check(candidate.load(), "isolated GPU plugin not loaded");
#endif
    auto *registry=KoColorSpaceRegistry::instance();
    KisFilterBloom bloom; KisFilterHalation halation; KisFilterKuwahara kuwahara;
    KisFilterLensFlare flare; KisFilterAnamorphicFlare streak; KisFilterLensDistortion lens; KisFilterColorRangeMask mask;
    KisFilter *filters[]={&bloom,&bloom,&halation,&kuwahara,&flare,&streak,&lens,&lens,&mask};
    const bool baseline=argc>2 && QString::fromLocal8Bit(argv[2])=="baseline";
    for(const QString depth:{"U8","U16","F16","F32"}) for(int index=0;index<9;++index) {
        if(baseline && depth!="U8") continue;
        const auto *cs=registry->colorSpace("RGBA",depth,registry->p709G10Profile());
        check(cs && cs->colorDepthId().id()==depth,"required depth unavailable");
        auto *filter=filters[index];
        auto config=filter->defaultConfiguration(KisGlobalResourcesInterface::instance());
        config->setProperty("radius",2.0); config->setProperty("size",2.0); config->setProperty("iterations",3.0);
        config->setProperty("diffusion",index==0 ? 0.0 : 1.0); config->setProperty("threshold",0.2);
        config->setProperty("intensity",.2); config->setProperty("strength",.2);
        config->setProperty("distortion",.1); config->setProperty("dispersion",.04);
        config->setProperty("mode",index==7 ? "horizontal" : "radial"); config->setProperty("jitter",false);
        config->setProperty("range_min",.1); config->setProperty("range_max",.8);
        auto whole=fixture(cs); const auto input=tfm::readFloatImage(whole,area);
        { KisTransaction transaction(whole); filter->processImpl(whole,area,config,nullptr); transaction.end(); }
        if(argc>1) {
            QFile file(QDir(QString::fromLocal8Bit(argv[1])).filePath(QString("%1-%2.raw").arg(depth).arg(index)));
            check(file.open(QIODevice::WriteOnly),"cannot save pixels"); file.write(bytes(whole));
        }
        if(baseline) continue;
        const auto expected=tfm::readFloatImage(whole,area);
#ifndef TFM_RECORD_BASELINE
        if (depth == "F32" && (index == 2 || index == 3 || index == 6)) {
            qputenv("TFM_BACKEND", "gpu");
            qputenv("TFM_VULKAN_DISABLE", "0");
            auto accelerated = fixture(cs);
            { KisTransaction tx(accelerated); filter->processImpl(accelerated, area, config, nullptr); tx.end(); }
            checkGpuStatus(filter->id());
            qputenv("TFM_BACKEND", "auto");
            check(tfm::gpuRequested("tfm_vibrance", 64 * 64), "warm Auto preview bypassed the GPU");
            const auto result = tfm::readFloatImage(accelerated, area);
            for (int i = 0; i < expected.pixels.size(); ++i)
                check(std::abs(expected.pixels[i] - result.pixels[i]) < .0001, "F32 spatial CPU/GPU mismatch");
            qputenv("TFM_BACKEND", "cpu");
            qputenv("TFM_VULKAN_DISABLE", "1");
        }
#endif
        for(bool reverse:{false,true}) {
            auto tiled=fixture(cs);
            KisTransaction transaction(tiled);
            QVector<QRect> chunks;
            for(int y=area.top();y<=area.bottom();y+=11) for(int x=area.left();x<=area.right();x+=67)
                chunks.append(QRect(x,y,67,11).intersected(area));
            if(reverse) std::reverse(chunks.begin(),chunks.end());
            for(const auto &rect:chunks) filter->processImpl(tiled,rect,config,nullptr);
            transaction.end();
            const auto actual=tfm::readFloatImage(tiled,area);
            double error=0;
            for(int i=0;i<actual.pixels.size();++i) error=std::max(error,std::abs(double(actual.pixels[i])-expected.pixels[i]));
            std::cout<<depth.toStdString()<<" filter="<<index<<" reverse="<<reverse<<" tile_error="<<error<<std::endl;
            const double tolerance=depth=="F16" ? .002 : depth=="U16" ? .0001 : .00002;
            check(error<=tolerance,"whole/tile mismatch");
        }
        if(index<6) {
            float alphaError=0;
            for(int i=3;i<expected.pixels.size();i+=4) alphaError=std::max(alphaError,std::abs(expected.pixels[i]-input.pixels[i]));
            check(alphaError==0,"spatial colour filter changed alpha");
        }
        if(depth.startsWith('F') && index!=6 && index!=7) {
            bool negative=false,hdr=false;
            for(int i=0;i<expected.pixels.size();i+=4) { negative|=expected.pixels[i]<0; hdr|=expected.pixels[i]>1; }
            check(negative && hdr,"spatial filter clipped extended range");
        }
        if(index!=3 && index!=8) {
            auto zero=fixture(cs); const auto original=bytes(zero);
            config->setProperty("blend",0.0);config->setProperty("strength",0.0);
            config->setProperty("distortion",0.0);config->setProperty("dispersion",0.0);
            filter->processImpl(zero,area,config,nullptr);
            check(original==bytes(zero),"no-effect parameters changed bytes");
        }
        {
            auto cancelled=fixture(cs); const auto original=bytes(cancelled);
            KoFakeProgressProxy proxy;
            KoProgressUpdater progress(&proxy);
            progress.start(); const auto sub=progress.startSubtask(); progress.cancel();
            app.processEvents();
            check(sub && sub->interrupted(),"test cancellation was not delivered");
            filter->processImpl(cancelled,area,config,sub.data());
            check(original==bytes(cancelled),"cancelled operation published pixels");
        }
        if(index==3 && depth=="F32") {
            const QRect large(-9,11,1024,512);
            auto cancelled=fixture(cs,large); const auto original=bytes(cancelled,large);
            config->setProperty("size",12.0);config->setProperty("iterations",4.0);
            KoFakeProgressProxy proxy;
            KoProgressUpdater progress(&proxy);
            progress.start(); const auto sub=progress.startSubtask();
            std::atomic<bool> completed{false};
            std::thread calculation([&] { filter->processImpl(cancelled,large,config,sub.data()); completed=true; });
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
            progress.cancel();
            while(!completed) { app.processEvents(); std::this_thread::sleep_for(std::chrono::milliseconds(1)); }
            calculation.join();
            check(original==bytes(cancelled,large),"in-flight cancelled computation published pixels");
        }
    }
#ifndef TFM_RECORD_BASELINE
    checkHalationEdge(halation, registry->colorSpace("RGBA", "F32", registry->p709G10Profile()));
    tfm::guided::Lut lut; lut.valid=true;
    for(int r=0;r<lut.Size;++r) for(int g=0;g<lut.Size;++g) for(int b=0;b<lut.Size;++b) {
        lut.values[lut.index(r,g,b,0)]=float(r)/(lut.Size-1);
        lut.values[lut.index(r,g,b,1)]=float(g)/(lut.Size-1);
        lut.values[lut.index(r,g,b,2)]=float(b)/(lut.Size-1);
    }
    for(double v:{-.25,0.0,.300001,.300002,1.0,2.5}) {
        const auto result=lut.sampleFloat({v,v,v});
        check(std::abs(result[0]-v)<1e-7,"float LUT quantized identity/extended input");
    }
    float original[]={2.2f,-.3f,.432101f,.90001f}; const float estimated[]={1.0f,0.0f,110/255.0f,1.0f};
    const std::uint8_t proxy[]={255,0,110},alpha[]={128};
    tfm::background_removal::compositeRefined(original,estimated,proxy,alpha,1);
    check(original[0]==2.2f && original[1]==-.3f && original[2]==.432101f,"AI composition replaced source precision");
    check(std::abs(original[3]-.90001f*128/255)<1e-7,"AI composition changed alpha semantics");
#endif
    std::cout<<"Spatial, LUT and AI float composition PASS"<<std::endl;
    return 0;
} catch(const std::exception &e) { std::cerr<<"FAIL: "<<e.what()<<std::endl; return 1; }
