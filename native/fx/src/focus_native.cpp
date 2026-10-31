#include "focus_native.h"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace focus_native {
namespace {
constexpr double pi=3.14159265358979323846;
using Acc=std::array<double,4>;
int floorMultiple(int x,int n) { return int(std::floor(double(x)/n))*n; }
Rect expand(Rect r,int h) { return {r.x-h,r.y-h,r.w+2*h,r.h+2*h}; }
Rect canonical(Rect r,int n) {
    if(r.w<=0||r.h<=0) return r;
    int x=floorMultiple(r.x,n),y=floorMultiple(r.y,n);
    return {x,y,floorMultiple(r.x+r.w-1,n)+n-x,floorMultiple(r.y+r.h-1,n)+n-y};
}
Acc premultiply(Pixel p) {
    if(p[3]==0) return {};
    return {double(p[0])*p[3],double(p[1])*p[3],double(p[2])*p[3],p[3]};
}
Pixel unassociate(Acc v) {
    if(v[3]<=1e-14) return {0,0,0,0};
    return {float(v[0]/v[3]),float(v[1]/v[3]),float(v[2]/v[3]),float(v[3])};
}
Pixel gaussianUnassociate(Acc v) {
    double a=std::max(v[3],1.0/65536);
    return {float(v[0]/a),float(v[1]/a),float(v[2]/a),float(v[3])};
}
Acc gaussianPremultiply(Pixel p) {
    if(p[3]==0) return {}; // Exact-zero hidden RGB normalized; transparent padding stays zero.
    double a=std::max(double(p[3]),1.0/65536);
    return {double(p[0])*a,double(p[1])*a,double(p[2])*a,p[3]};
}
Image gaussianCore(const Image&s,Rect core,Rect frame,const Params&p) {
    Image out(core);
    int H=halo(p); Rect read=expand(core,H);
    const size_t count=size_t(read.w)*read.h;
    std::vector<Acc> original(count),a(count),b(count),blended(size_t(core.w)*core.h);
    for(int y=0;y<read.h;++y)for(int x=0;x<read.w;++x)original[size_t(y)*read.w+x]=gaussianPremultiply(s.get(read.x+x,read.y+y));
    int levels=p.highQuality?16:int(std::ceil(std::clamp(std::log2(std::max(p.blurRadius,1e-6))+3,2.0,16.0)));
    std::vector<double> position(blended.size());
    for(int y=0;y<core.h;++y)for(int x=0;x<core.w;++x) {
        double m=maskAt(core.x+x,core.y+y,frame,p);
        int j=std::min(levels-2,int(std::pow(m,1/1.5)*(levels-1)));
        double v1=std::pow(double(j)/(levels-1),1.5),v2=std::pow(double(j+1)/(levels-1),1.5);
        position[size_t(y)*core.w+x]=j+(m-v1)/(v2-v1);
    }
    for(int level=0;level<levels;++level) {
        bool used=false; for(double pos:position)if(std::abs(pos-level)<1){used=true;break;}
        if(!used)continue;
        a=original;
        if(level) {
            double sigma=p.blurRadius*std::pow(double(level)/(levels-1),1.5);
            // Finite normalized sampled Gaussian, same support as the FIR pyramid.
            float fsigma=float(sigma);
            int length=fsigma>1e-6f?int(std::ceil(fsigma*6.5)):1;
            length += (length+1)%2; int radius=length/2;
            if(radius>H)throw std::logic_error("FIR support exceeds halo");
            std::vector<double> kernel(length);double sum=0;
            for(int k=-radius;k<=radius;++k){double v=std::exp(-.5*double(k)*k/(fsigma*fsigma));kernel[k+radius]=v;sum+=v;}
            for(double &v:kernel)v/=sum;
            // Only horizontal columns needed by the vertical core are evaluated.
            // Four independent adjacent pixels; preserve each pixel's tap order.
            for(int y=H-radius;y<H+core.h+radius;++y)for(int x=H;x<H+core.w;x+=4){
                Acc accum[4]{};
                for(int k=-radius;k<=radius;++k) {
                    const Acc *src=&original[size_t(y)*read.w+x+k];
                    const double weight=kernel[k+radius];
                    for(int j=0;j<4;++j)for(int c=0;c<4;++c)accum[j][c]+=src[j][c]*weight;
                }
                for(int j=0;j<4;++j)b[size_t(y)*read.w+x+j]=accum[j];
            }
            for(int y=H;y<H+core.h;++y)for(int x=H;x<H+core.w;x+=4){
                Acc accum[4]{};
                for(int k=-radius;k<=radius;++k) {
                    const Acc *src=&b[size_t(y+k)*read.w+x];
                    const double weight=kernel[k+radius];
                    for(int j=0;j<4;++j)for(int c=0;c<4;++c)accum[j][c]+=src[j][c]*weight;
                }
                for(int j=0;j<4;++j)a[size_t(y)*read.w+x+j]=accum[j];
            }
        }
        for(int y=0;y<core.h;++y)for(int x=0;x<core.w;++x) {
            size_t i=size_t(y)*core.w+x; double weight=std::max(0.0,1-std::abs(position[i]-level));
            for(int c=0;c<4;++c)blended[i][c]+=weight*a[size_t(y+H)*read.w+x+H][c];
        }
    }
    for(size_t i=0;i<out.pixels.size();++i)out.pixels[i]=gaussianUnassociate(blended[i]);
    return out;
}
Image lensCore(const Image&s,Rect core,Rect frame,const Params&p) {
    Image out(core);int H=halo(p);Rect read=expand(core,H);
    struct Sample{Acc rgba;double weight,radius2;};
    std::vector<Sample> samples(size_t(read.w)*read.h);
    for(int y=0;y<read.h;++y)for(int x=0;x<read.w;++x) {
        Pixel q=s.get(read.x+x,read.y+y);
        double luminance=q[3]==0?0:.2126*q[0]+.7152*q[1]+.0722*q[2];
        double range=p.highlightThresholdHigh-p.highlightThresholdLow;
        double t=range==0?(luminance>p.highlightThresholdLow?1:0):std::clamp((luminance-p.highlightThresholdLow)/range,0.0,1.0);
        double r=maskAt(read.x+x,read.y+y,frame,p)*p.blurRadius+.5;
        double weight=std::exp2(10*p.highlightFactor*t)/(pi*r*r);
        auto &v=samples[size_t(y)*read.w+x];v.rgba=premultiply(q);v.weight=weight;v.radius2=r*r;
        for(double &c:v.rgba)c*=weight;
    }
    // Difference rows implement source-dependent disk scatter in O(radius), not O(radius^2).
    std::vector<std::array<double,5>> diff(core.w+1);
    std::vector<int> coverage(core.w+1);
    for(int y=0;y<core.h;++y) {
        std::fill(diff.begin(),diff.end(),std::array<double,5>{});
        std::fill(coverage.begin(),coverage.end(),0);
        for(int dy=-H;dy<=H;++dy)for(int sx=0;sx<read.w;++sx) {
            const auto &v=samples[size_t(y+H+dy)*read.w+sx];
            if(v.radius2<double(dy)*dy)continue;
            int reach=int(std::sqrt(v.radius2-double(dy)*dy));
            int left=std::max(0,sx-H-reach),right=std::min(core.w,sx-H+reach+1);
            if(left>=right)continue;
            for(int c=0;c<4;++c){diff[left][c]+=v.rgba[c];diff[right][c]-=v.rgba[c];}
            diff[left][4]+=v.weight;diff[right][4]-=v.weight;
            if(v.rgba[3]>0){++coverage[left];--coverage[right];}
        }
        std::array<double,5> sum{}; int covered=0;
        for(int x=0;x<core.w;++x) {
            for(int c=0;c<5;++c)sum[c]+=diff[x][c];
            covered+=coverage[x];
            // Exact integer support avoids ghost RGB from cancellation at zero coverage.
            if(covered==0){out.at(core.x+x,core.y+y)={0,0,0,0};continue;}
            Pixel v=unassociate({sum[0],sum[1],sum[2],sum[3]});
            v[3]=sum[4]>0?float(std::clamp(sum[3]/sum[4],0.0,1.0)):0;
            if(v[3]==0)v={0,0,0,0};out.at(core.x+x,core.y+y)=v;
        }
    }
    return out;
}
}
Image::Image(Rect b,Pixel fill):bounds(b){if(b.w<0||b.h<0||size_t(b.w)*b.h>64ULL*1024*1024)throw std::invalid_argument("image size");pixels.assign(size_t(b.w)*b.h,fill);}
Pixel Image::get(int x,int y)const{return bounds.contains(x,y)?pixels[size_t(y-bounds.y)*bounds.w+x-bounds.x]:outside;}
Pixel &Image::at(int x,int y){if(!bounds.contains(x,y))throw std::out_of_range("image coordinate");return pixels[size_t(y-bounds.y)*bounds.w+x-bounds.x];}
Params sanitize(Params p){
    auto clamp=[](double v,double lo,double hi,double fallback){return std::isfinite(v)?std::clamp(v,lo,hi):fallback;};
    p.blurRadius=clamp(p.blurRadius,0,200,25);p.highlightFactor=clamp(p.highlightFactor,0,1,0);
    p.highlightThresholdLow=clamp(p.highlightThresholdLow,0,1,0);p.highlightThresholdHigh=clamp(p.highlightThresholdHigh,0,1,1);
    p.x=clamp(p.x,-1,2,.5);p.y=clamp(p.y,-1,2,.5);p.radius=clamp(p.radius,0,3,.75);
    p.focus=clamp(p.focus,0,1,.25);p.midpoint=clamp(p.midpoint,0,1,.5);p.aspectRatio=clamp(p.aspectRatio,-1,1,0);p.rotation=clamp(p.rotation,-180,180,0);return p;
}
float maskAt(int x,int y,Rect f,const Params&p){
    if(f.w<=0||f.h<=0)throw std::invalid_argument("reference frame");
    const double cx=int(f.x+f.w*p.x),cy=int(f.y+f.h*p.y);
    double scale=p.aspectRatio<0?std::max(1+p.aspectRatio,1e-6):1/std::max(1-p.aspectRatio,1e-6);
    double length=f.w/2.0/std::max(1.0,scale),inner=p.radius*p.focus;
    double gamma=p.midpoint>=1?1000:std::min(1000.0,-.6931471805599453/std::log(std::max(p.midpoint,1e-6)));
    double angle=-p.rotation*pi/180,dx=x-cx,dy=y-cy;
    double u=std::abs((std::cos(angle)*dx-std::sin(angle)*dy)/scale),v=std::abs(std::sin(angle)*dx+std::cos(angle)*dy),d=std::hypot(u,v);
    switch(p.shape){case Shape::Square:d=std::max(u,v);break;case Shape::Diamond:d=u+v;break;case Shape::Horizontal:d=v;break;case Shape::Vertical:d=u;break;default:break;}
    return float(std::pow(std::clamp((d/length-inner)/std::max(p.radius-inner,.0001),0.0,1.0),gamma));
}
int halo(const Params&input){auto p=sanitize(input);if(p.lens)return int(std::floor(p.blurRadius+.5));float sigma=float(p.blurRadius);int length=sigma>1e-6f?int(std::ceil(sigma*6.5)):1;length+=(length+1)%2;return length/2;}
Rect neededRect(Rect r,const Params&p){return expand(canonical(r,p.lens?64:256),halo(p));}
Rect changedRect(Rect r,const Params&p){return expand(r,halo(p));}
Image render(const Image&s,Rect target,Rect frame,const Params&input){
    Params p=sanitize(input);Image out(target); if(target.w==0||target.h==0)return out;
    if(p.blurRadius==0||(p.lens&&p.blurRadius<.5)) {for(int y=target.y;y<target.y+target.h;++y)for(int x=target.x;x<target.x+target.w;++x)out.at(x,y)=s.get(x,y);return out;}
    int n=p.lens?64:256;Rect grid=canonical(target,n);
    for(int cy=grid.y;cy<grid.y+grid.h;cy+=n)for(int cx=grid.x;cx<grid.x+grid.w;cx+=n){
        Rect core{cx,cy,n,n};Image tile=p.lens?lensCore(s,core,frame,p):gaussianCore(s,core,frame,p);
        for(int y=std::max(cy,target.y);y<std::min(cy+n,target.y+target.h);++y)for(int x=std::max(cx,target.x);x<std::min(cx+n,target.x+target.w);++x)out.at(x,y)=tile.get(x,y);
    }
 return out;
}
void renderInto(const Image&s,Image&dst,Rect target,Rect frame,const Params&p){
    // One whole render safely supports aliasing. Multiple calls require an immutable transaction snapshot.
    Image result=render(s,target,frame,p);
    for(int y=target.y;y<target.y+target.h;++y)for(int x=target.x;x<target.x+target.w;++x)dst.at(x,y)=result.get(x,y);
}
}
