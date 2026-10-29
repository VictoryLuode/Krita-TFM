#include "../src/bloom_algorithm.h"
#include <cassert>
#include <cmath>
#include <cstdio>
using namespace fxmanager::bloom;
int main() {
    assert(highlight(.6,.7,0)==0);
    assert(highlight(.6,.7,.2)>0);
    assert(std::abs(highlight(.9,.7,.2)-.2)<1e-10);
    QImage src(90,65,QImage::Format_ARGB32); src.fill(qRgba(20,20,20,255));
    src.setPixel(43,30,qRgba(255,240,220,255));
    src.setPixel(25,25,qRgba(255,0,255,0));
    src.setPixel(45,30,qRgba(10,15,20,100));
    QImage all=diffuse(src,.7,3,2,.1);
    assert(qRed(all.pixel(44,30))>qRed(src.pixel(44,30)));
    for(int y=0;y<src.height();++y) for(int x=0;x<src.width();++x) assert(qAlpha(all.pixel(x,y))==qAlpha(src.pixel(x,y)));
    assert(all.pixel(25,25)==src.pixel(25,25));
    QImage transparent=src; transparent.setPixel(25,25,qRgba(0,0,0,0));
    QImage noHidden=diffuse(transparent,.7,3,2,.1);
    for(int y=0;y<src.height();++y) for(int x=0;x<src.width();++x)
        if(x!=25 || y!=25) assert(noHidden.pixel(x,y)==all.pixel(x,y));
    for(int left=0;left<90;left+=15) {
        QRect tile(left,0,std::min(15,90-left),65);
        QRect padded=tile.adjusted(-halo(3),-halo(3),halo(3),halo(3));
        QImage chunk(padded.size(),QImage::Format_ARGB32); chunk.fill(Qt::transparent);
        for(int y=0;y<padded.height();++y) for(int x=0;x<padded.width();++x) {
            int xx=x+padded.x(), yy=y+padded.y();
            if(src.rect().contains(xx,yy)) chunk.setPixel(x,y,src.pixel(xx,yy));
        }
        QImage result=diffuse(chunk,.7,3,2,.1);
        for(int y=0;y<tile.height();++y) for(int x=0;x<tile.width();++x)
            assert(result.pixel(x+halo(3),y+halo(3))==all.pixel(x+left,y));
    }
    puts("Bloom algorithm: threshold, alpha, hidden RGB, diffusion and tiled seams PASS");
}
