#pragma once
#include "bloom_algorithm.h"
#include "tfm_processing.h"
#include <KoUpdater.h>

namespace tfm::bloom {
inline EncodedRgbaImage renderFloat(const EncodedRgbaImage &source,double threshold,int radius,
                                   double strength,double softness,bool diffusion,KoUpdater *updater)
{
    auto output=source;
    float *dst=output.pixels.data();
    const float *src=source.pixels.constData();
    const int width=source.width,height=source.height;
    const double denom=std::max(.001,1.0-threshold);
    if(diffusion) {
        QVector<Light> light(width*height),temp(light.size());
        for(int y=0;y<height;++y) {
            if(updater && updater->interrupted()) return {};
            for(int x=0;x<width;++x) {
                const auto *p=src+4*(y*width+x);
                const double lum=.2126*p[0]+.7152*p[1]+.0722*p[2];
                const double gain=highlight(lum,std::clamp(threshold,0.0,1.0),softness)/denom*p[3];
                light[y*width+x]={p[0]*gain,p[1]*gain,p[2]*gain};
            }
        }
        for(int pass=0;pass<blurPasses;++pass) {
            if(updater && updater->interrupted()) return {};
            boxPass(light,temp,width,height,radius,true);
            if(updater && updater->interrupted()) return {};
            boxPass(temp,light,width,height,radius,false);
        }
        for(int i=0;i<width*height;++i) {
            if(!dst[i*4+3]) continue;
            const auto glow=light[i]*std::clamp(strength,0.0,2.0);
            dst[i*4]+=float(glow.r); dst[i*4+1]+=float(glow.g); dst[i*4+2]+=float(glow.b);
        }
    } else {
        const int step=std::max(1,radius/8);
        parallelRows(height,[&](int y0,int y1) {
            for(int y=y0;y<y1;++y) {
                if(updater && updater->interrupted()) return;
                for(int x=0;x<width;++x) {
                    auto *base=dst+4*(y*width+x);
                    const double lum=.2126*base[0]+.7152*base[1]+.0722*base[2];
                    if(lum<=threshold) continue;
                    double sum[3]={}; int count=0;
                    for(int oy=-radius;oy<=radius;oy+=step) for(int ox=-radius;ox<=radius;ox+=step) {
                        const auto *p=src+4*(std::clamp(y+oy,0,height-1)*width+std::clamp(x+ox,0,width-1));
                        if(.2126*p[0]+.7152*p[1]+.0722*p[2]>threshold) {
                            for(int c=0;c<3;++c) sum[c]+=p[c];
                            ++count;
                        }
                    }
                    if(count) {
                        const double gain=std::clamp((lum-threshold)/denom*strength,0.0,1.0);
                        for(int c=0;c<3;++c) base[c]+=float(sum[c]/count*gain);
                    }
                }
            }
        });
    }
    return output;
}
}
