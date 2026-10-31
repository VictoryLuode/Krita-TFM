#pragma once
#include <array>
#include <vector>
#include <cstddef>

namespace focus_native {
struct Rect { int x=0,y=0,w=0,h=0; bool contains(int X,int Y) const { return X>=x&&Y>=y&&X<x+w&&Y<y+h; } };
using Pixel=std::array<float,4>;
struct Image {
    Rect bounds;
    std::vector<Pixel> pixels;
    Pixel outside{0,0,0,0}; // Converted paint-device default, not assumed transparent.
    explicit Image(Rect b={}, Pixel fill={0,0,0,0});
    Pixel get(int x,int y) const;
    Pixel &at(int x,int y);
};
enum class Shape { Circle,Square,Diamond,Horizontal,Vertical };
struct Params {
    bool lens=false;
    double blurRadius=25,highlightFactor=0,highlightThresholdLow=0,highlightThresholdHigh=1;
    Shape shape=Shape::Circle;
    double x=.5,y=.5,radius=.75,focus=.25,midpoint=.5,aspectRatio=0,rotation=0;
    bool highQuality=false;
};
Params sanitize(Params p);
float maskAt(int x,int y,Rect reference,const Params &p);
int halo(const Params &p);
Rect neededRect(Rect target,const Params &p);
Rect changedRect(Rect edited,const Params &p);
// Immutable linear unassociated F32 sRGB source. Output owns target pixels.
// Canonical global cores make patch order and extents irrelevant to arithmetic.
// Input must contain neededRect(target), or deliberately define missing pixels via outside.
Image render(const Image &source,Rect target,Rect reference,const Params &params);
// Caller snapshots input once for the entire host transaction, not once per patch.
void renderInto(const Image &immutableSource,Image &destination,Rect target,Rect reference,const Params &params);
}
