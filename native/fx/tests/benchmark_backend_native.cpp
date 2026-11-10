// End-to-end filter timings: real U8 paint device, conversions and IPC included.
#include "tfm_vibrance.h"
#include "tfm_color_temperature.h"
#include "tfm_film_grain.h"
#include "tfm_vignette.h"
#include "tfm_color_range_mask.h"
#include "tfm_processing.h"
#include "tfm_vulkan.h"
#include <QApplication>
#include <QLibrary>
#include <QElapsedTimer>
#include <QFile>
#include <QDir>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <KoColorSpaceRegistry.h>
#include <KoResourcePaths.h>
#include <KisGlobalResourcesInterface.h>
#include <kis_default_bounds_base.h>
#include <iostream>
#include <stdexcept>

class Bounds final : public KisDefaultBoundsBase {
    QRect m_rect;
public:
    Bounds(QRect rect):m_rect(rect) {}
    QRect bounds() const override { return m_rect; }
    bool wrapAroundMode() const override { return false; }
    WrapAroundAxis wrapAroundModeAxis() const override { return WRAPAROUND_BOTH; }
    int currentLevelOfDetail() const override { return 0; }
    int currentTime() const override { return 0; }
    bool externalFrameActive() const override { return false; }
    void *sourceCookie() const override { return nullptr; }
};

int main(int argc,char **argv) try {
    QApplication app(argc,argv);
    qputenv("TFM_THREADS","1"); qputenv("TFM_VULKAN_DISABLE","0");
    const QString runtime=[](){ QByteArray v=qgetenv("TFM_KRITA_RUNTIME"); if(v.isEmpty()) v=qgetenv("FXMANAGER_KRITA_RUNTIME"); return QString::fromLocal8Bit(v); }();
    app.addLibraryPath(runtime+"/lib");
    KoResourcePaths::addAssetDir("icc_profiles",runtime+"/share/color/icc/krita");
    QLibrary candidate(QString::fromLocal8Bit(qgetenv("TFM_TEST_NATIVE_DLL")));
    candidate.setLoadHints(QLibrary::PreventUnloadHint);
    if (!candidate.load()) throw std::runtime_error("candidate DLL unavailable");
    auto *registry=KoColorSpaceRegistry::instance();
    const auto *cs=registry->colorSpace("RGBA","U8",registry->p709SRGBProfile());
    TfmVulkan connection;
    KisFilterVibrance vibrance; KisFilterColorTemperature temperature;
    KisFilterFilmGrain grain; KisFilterVignette vignette; KisFilterColorRangeMask mask;
    QJsonArray records;
    const std::vector<int> sizes = qEnvironmentVariableIsSet("TFM_BENCH_LARGE") ? std::vector<int>{qEnvironmentVariableIntValue("TFM_BENCH_LARGE")==2 ? 5120 : 4096} : std::vector<int>{64,256,1024,2048};
    for (KisFilter *filter : std::initializer_list<KisFilter*>{&vibrance,&temperature,&grain,&vignette,&mask})
    for (int side : sizes) {
        const QString only=qEnvironmentVariable("TFM_BENCH_FILTER");
        if(!only.isEmpty() && filter->id()!=only) continue;
        const QRect area(0,0,side,side);
        KisPaintDeviceSP source=new KisPaintDevice(cs); source->setDefaultBounds(new Bounds(area));
        QByteArray input(side*side*4,Qt::Uninitialized);
        for(int i=0;i<input.size();i+=4) {
            input[i]=char((i*17)%256);input[i+1]=char((i/9)%256);input[i+2]=char((i/37)%256);input[i+3]=char(255);
        }
        source->writeBytes(reinterpret_cast<const quint8*>(input.constData()),area);
        auto config=filter->defaultConfiguration(KisGlobalResourcesInterface::instance());
        config->setProperty("vibrance",60.0); config->setProperty("temperature",5700.0);
        config->setProperty("preset",QStringLiteral("custom"));config->setProperty("amount",.4);
        config->setProperty("factor",.4);
        config->setProperty("range_min",.2);config->setProperty("range_max",.8);
        QJsonObject record{{"filter",filter->id()},{"side",side},{"cpu_threads",1}};
        QByteArray cpu;
        for (const QByteArray &backend : {QByteArray("cpu"),QByteArray("gpu")}) {
            qputenv("TFM_BACKEND",backend);
            QJsonArray cold,warm;
            for(int sample=0;sample<15;++sample) {
                if (sample<3) connection.shutdown();
                KisPaintDeviceSP device=new KisPaintDevice(*source);
                QElapsedTimer clock;clock.start();
                filter->processImpl(device,area,config,nullptr);
                (sample<3 ? cold : warm).append(clock.nsecsElapsed()/1e6);
                if (sample==0) {
                    QByteArray actual(input.size(),Qt::Uninitialized);
                    device->readBytes(reinterpret_cast<quint8*>(actual.data()),area);
                    if (backend=="cpu") cpu=actual;
                    else {
                        QFile status(QDir(tfm::resourceDirectory()).filePath("TFM/backend-status.json"));
                        if(!status.open(QIODevice::ReadOnly) || QJsonDocument::fromJson(status.readAll()).object().value("actual").toString()!="gpu")
                            throw std::runtime_error("GPU benchmark silently fell back");
                        int delta=0;
                        for(int i=0;i<actual.size();++i) delta=std::max(delta,std::abs(int(uchar(actual[i]))-int(uchar(cpu[i]))));
                        record.insert("max_cpu_gpu_u8_error",delta);
                        if(delta>2) throw std::runtime_error("benchmark changed image output");
                    }
                }
            }
            record.insert(QString::fromLatin1(backend)+"_cold_ms",cold);
            record.insert(QString::fromLatin1(backend)+"_warm_ms",warm);
        }
        records.append(record);
        std::cout<<filter->id().toStdString()<<" "<<side<<" PASS"<<std::endl;
    }
    connection.shutdown();
    QFile report(QDir(QString::fromLocal8Bit(argv[1])).filePath("backend-benchmark.json"));
    if(!report.open(QIODevice::WriteOnly)) throw std::runtime_error("cannot write benchmark");
    report.write(QJsonDocument(records).toJson());
    return 0;
} catch(const std::exception &error) {std::cerr<<error.what()<<std::endl;return 1;}

