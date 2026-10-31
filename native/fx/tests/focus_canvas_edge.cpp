#include "focus_native.h"
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <string>

using namespace focus_native;
namespace {
int failures=0;
void check(bool ok,const std::string &what){if(!ok){std::cerr<<"FAIL: "<<what<<'\n';++failures;}}
bool near(float a,float b,float e=2e-4f){return std::abs(a-b)<=e;}
Image make(Rect b, Rect canvas){Image s(b);
#ifndef FOCUS_BASELINE
 s.canvasBounds=canvas;
#endif
 for(auto &p:s.pixels)p={.4f,.4f,.4f,1};return s;}
void testGaussianEdge(){
 Rect c{-20,30,137,101};Image s=make(c,c);Params p;p.blurRadius=25;p.x=.5;p.y=.5;p.radius=0;p.focus=0;
 auto o=render(s,c,{-40,0,250,240},p);
 for(int x=c.x;x<c.x+c.w;++x)check(near(o.get(x,c.y)[3],1),"Gaussian top edge alpha remains one");
 for(int y=c.y;y<c.y+c.h;++y)check(near(o.get(c.x,y)[3],1),"Gaussian left edge alpha remains one");
 // A transparent pixel is canvas support, but neighboring opaque color still diffuses into it.
 s.at(c.x+68,c.y+50)={0,0,0,0};o=render(s,c,{-40,0,250,240},p);
 check(o.get(c.x+67,c.y+50)[3]>0.1f,"transparent hole receives Gaussian diffusion");
}
void testLensEdge(){Rect c{-12,8,31,27};auto s=make({-28,-8,63,59},c);Params p;p.lens=true;p.blurRadius=12;p.radius=0;p.focus=0;
 auto o=render(s,c,{-50,-40,100,100},p);for(int x=c.x;x<c.x+c.w;++x)check(near(o.get(x,c.y)[3],1),"Lens canvas edge excludes outside sources");}
void testOutsideCannotContribute(){Rect c{0,0,9,7};Image s({-7,-7,23,21});s.canvasBounds=c;for(auto &q:s.pixels)q={0,0,0,0};for(int y=0;y<c.h;++y)for(int x=0;x<c.w;++x)s.at(x,y)={.4f,.4f,.4f,1};Params p;p.blurRadius=5;p.lens=true;p.radius=0;p.focus=0;auto o=render(s,c,{-10,-10,30,30},p);check(near(o.get(0,0)[3],1),"Lens ignores opaque source pixels outside canvas");
 Params g=p;g.lens=false;auto go=render(s,c,{-10,-10,30,30},g);check(near(go.get(0,0)[3],1),"Gaussian ignores canvas exterior padding");
 Image legacy=s;legacy.canvasBounds={};Rect target{-2,-2,13,11};auto lensLegacy=render(legacy,target,{-10,-10,30,30},p);auto lensClipped=render(s,target,{-10,-10,30,30},p);for(int y=-2;y<9;++y)for(int x=-2;x<11;++x)if(!c.contains(x,y))check(lensLegacy.get(x,y)==lensClipped.get(x,y),"Lens outside-canvas output retains legacy behavior");}
void testPatchOrder(){Rect c{-9,-4,25,19};auto s=make(c,c);s.at(1,2)={1,0,0,1};Params p;p.blurRadius=2;p.radius=0;p.focus=0;Rect frame{-30,-20,100,80};auto whole=render(s,c,frame,p);Image tiled(c);tiled.canvasBounds=c;
 renderInto(s,tiled,{-9,-4,12,19},frame,p);renderInto(s,tiled,{3,-4,13,19},frame,p);
 for(size_t i=0;i<whole.pixels.size();++i)for(int k=0;k<4;++k)check(near(whole.pixels[i][k],tiled.pixels[i][k]),"patch tiling matches full render");
 Image reverse(c);reverse.canvasBounds=c;renderInto(s,reverse,{3,-4,13,19},frame,p);renderInto(s,reverse,{-9,-4,12,19},frame,p);check(reverse.pixels==tiled.pixels,"reversed patch order is identical");}
void testCanvasIndependentOfFrame(){Rect c{0,0,13,9};auto s=make(c,c);for(int y=0;y<c.h;++y)for(int x=0;x<c.w;++x)s.at(x,y)[3]=float((x+y)%7+1)/7;Params p;p.blurRadius=2;p.x=.1;p.y=.1;p.radius=.8;p.focus=.25;auto a=render(s,c,{-10,-10,30,30},p);auto b=render(s,c,c,p);bool different=false;for(size_t i=0;i<a.pixels.size();++i)different|=!near(a.pixels[i][3],b.pixels[i][3],1e-3f);check(different,"canvas domain does not replace saved focus frame");}
void testIdentityAndLegacy(){Rect c{-4,3,9,7};auto s=make(c,c);s.at(-4,3)={.8f,.2f,.1f,.25f};Params p;p.blurRadius=0;auto o=render(s,c,c,p);check(o.pixels==s.pixels,"radius zero is exact identity");
 Image legacy(c);for(auto &q:legacy.pixels)q={.2f,.5f,.8f,1};p.blurRadius=2;p.radius=0;p.focus=0;auto a=render(legacy,c,c,p);check(a.get(-4,3)[3]<1,"empty canvasBounds retains legacy edge semantics");}
void testRadiusSweep(){Rect c{0,0,17,13};auto s=make(c,c);for(double r:{.5,2.,25.,200.}){Params p;p.blurRadius=r;p.radius=0;p.focus=0;auto o=render(s,c,{100,100,200,150},p);for(auto q:o.pixels)check(near(q[3],1,1e-3f),"Gaussian radius sweep opaque alpha");}
 Params p;p.blurRadius=2;p.highQuality=true;p.radius=0;p.focus=0;auto q=render(s,c,{100,100,200,150},p);for(auto px:q.pixels)check(near(px[3],1),"HQ opaque alpha");}
}
int main(){testGaussianEdge();testLensEdge();testOutsideCannotContribute();testPatchOrder();testCanvasIndependentOfFrame();testIdentityAndLegacy();testRadiusSweep();if(failures)std::cerr<<failures<<" assertion(s) failed\n";else std::cout<<"focus canvas edge regression passed\n";return failures?1:0;}
