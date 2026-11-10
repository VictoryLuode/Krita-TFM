#include "fxmanager_processing.h"
#include <QApplication>
#include <QDir>
#include <QFile>
#include <KoColorSpaceRegistry.h>
#include <KoColorProfile.h>
#include <KoResourcePaths.h>
#include <cmath>
#include <iostream>
#include <stdexcept>

static void check(bool ok,const char *text) { if(!ok) throw std::runtime_error(text); }
int main(int argc,char **argv) try {
    QApplication app(argc,argv);
    const QString runtime=QString::fromLocal8Bit(qgetenv("FXMANAGER_KRITA_RUNTIME"));
    app.addLibraryPath(runtime+"/lib");
    KoResourcePaths::addAssetDir("icc_profiles",runtime+"/share/color/icc/krita");
    auto *registry=KoColorSpaceRegistry::instance();
    const auto *working=registry->colorSpace("RGBA","F32",registry->p709G10Profile());
    const QRect rect(0,0,1024,1);
    QVector<QPair<QString,const KoColorProfile *>> profiles;
    for(const QString filename : {"ClayRGB-elle-V2-g22.icc", "ClayRGB-elle-V4-srgbtrc.icc"}) {
        QFile file(runtime+"/share/color/icc/krita/"+filename);
        check(file.open(QIODevice::ReadOnly),"profile fixture missing");
        const auto *profile=registry->createColorProfile("RGBA","F32",file.readAll());
        check(profile,"profile load failed");
        profiles.append({filename,profile});
    }
    const QVector<double> customPrimaries{.3127,.3290,.68,.32,.265,.69,.15,.06};
    profiles.append({"Custom gamma 1.8",registry->profileFor(customPrimaries,PRIMARIES_UNSPECIFIED,TRC_GAMMA_1_8)});
    profiles.append({"Custom Rec709 TRC",registry->profileFor(customPrimaries,PRIMARIES_UNSPECIFIED,TRC_ITU_R_BT_709_5)});
    for(const auto &entry : profiles) {
        const QString filename=entry.first;
        const auto *profile=entry.second;
        check(profile,"custom profile unavailable");
        for(const QString depth : {"F16","F32"}) {
            const auto *cs=registry->colorSpace("RGBA",depth,profile);
            check(cs,"profile/depth unavailable");
            KisPaintDeviceSP device=new KisPaintDevice(cs);
            QByteArray raw(rect.width()*cs->pixelSize(),Qt::Uninitialized);
            QVector<float> channels(4);
            for(int i=0;i<rect.width();++i) {
                const float x=float(i)/1023;
                channels={-0.25f+3*x,.15f+.3f*x,.3f+.2f*x,i%3==0 ? 0.0f : .712345f};
                cs->fromNormalisedChannelsValue(reinterpret_cast<quint8*>(raw.data())+i*cs->pixelSize(),channels);
            }
            device->writeBytes(reinterpret_cast<const quint8*>(raw.constData()),rect);
            const auto linear=fxmanager::readFloatImage(device,rect);
            check(!linear.isNull(),"custom float conversion failed");
            check(fxmanager::writeFloatImage(device,linear,rect),"custom reverse conversion failed");
            check(device->colorSpace()==cs && *cs->profile()==*profile,"profile changed");
            QByteArray result(raw.size(),Qt::Uninitialized);
            device->readBytes(reinterpret_cast<quint8*>(result.data()),rect);
            double error=0,alpha=0;
            QVector<float> before(4),after(4);
            for(int i=0;i<rect.width();++i) {
                cs->normalisedChannelsValue(reinterpret_cast<const quint8*>(raw.constData())+i*cs->pixelSize(),before);
                cs->normalisedChannelsValue(reinterpret_cast<const quint8*>(result.constData())+i*cs->pixelSize(),after);
                for(int c=0;c<3;++c) error=std::max(error,double(std::abs(before[c]-after[c])));
                alpha=std::max(alpha,double(std::abs(before[3]-after[3])));
            }
            std::cout<<filename.toStdString()<<" "<<depth.toStdString()<<" HDR roundtrip error="<<error<<" alpha="<<alpha<<std::endl;
            check(error<(depth=="F16" ? .004 : .0002) && alpha==0,"custom profile HDR/alpha roundtrip failed");
            // An independent colour-engine transform checks the matrix orientation
            // and whitepoint adaptation on an in-range, non-clipping colour.
            channels={.31f,.43f,.27f,1};
            cs->fromNormalisedChannelsValue(reinterpret_cast<quint8*>(raw.data()),channels);
            device->writeBytes(reinterpret_cast<const quint8*>(raw.constData()),0,0,1,1);
            float reference[4];
            check(cs->convertPixelsTo(reinterpret_cast<const quint8*>(raw.constData()),reinterpret_cast<quint8*>(reference),working,1,
                  KoColorConversionTransformation::internalRenderingIntent(),KoColorConversionTransformation::internalConversionFlags()),"ICC reference failed");
            const auto actual=fxmanager::readFloatImage(device,QRect(0,0,1,1));
            for(int c=0;c<3;++c) check(std::abs(reference[c]-actual.pixels[c])<.001,"matrix/TRC differs from ICC reference");
        }
    }
    for(const QString depth : {"U8","U16","F16","F32"}) {
        const auto *cs=registry->colorSpace("RGBA",depth,registry->p709SRGBProfile());
        KisPaintDeviceSP device=new KisPaintDevice(cs);
        const float values[4]={-4.5f,2.125f,.1234567f,.6f};
        if(depth=="F32") device->writeBytes(reinterpret_cast<const quint8*>(values),0,0,1,1);
        const auto data=fxmanager::readDataFloatRgba(device,QRect(0,0,1,1));
        if(depth=="F32") {
            check(data.pixels.size()==4,"raw F32 unavailable");
            for(int c=0;c<4;++c) check(data.pixels[c]==values[c],"raw AOV underwent colour transform");
        } else check(data.pixels.isEmpty(),"non-F32 data incorrectly accepted as raw AOV");
    }
    std::cout<<"Custom profiles and raw AOV boundaries PASS"<<std::endl;
    return 0;
} catch(const std::exception &e) { std::cerr<<"FAIL: "<<e.what()<<std::endl;return 1; }
