#include "../src/fxmanager_color_range_mask_algorithm.h"
#include <cassert>
#include <cmath>
#include <iostream>

using namespace colormask;
int main() {
    Settings s;
    const std::uint32_t p = 0x8064a0c8u;
    assert(maskArgb32(p, s) == p);
    s.channel = Settings::Channel::Hue;
    s.rangeMin = .95; s.rangeMax = .05; s.softness = .02;
    assert(alphaFactor(1, 0, 0, s) == 1);
    assert(alphaFactor(1, .06, 0, s) == 1);
    assert(alphaFactor(1, 0, .06, s) == 1);
    assert(alphaFactor(0, 1, 0, s) == 0);
    assert(alphaFactor(.5, .5, .5, s) == 0);
    assert(alphaFactor(0, 0, 0, s) == 0);
    assert(alphaFactor(1, 1, 1, s) == 0);
    s.invert = true;
    assert(alphaFactor(.5, .5, .5, s) == 1);
    assert(alphaFactor(1, 0, 0, s) == 0);
    s.invert = false; s.rangeMin = 1; s.rangeMax = 1;
    assert(alphaFactor(1, 0, 0, s) == 1);
    s.rangeMin = 0; s.rangeMax = 1;
    assert(alphaFactor(0, 1, 0, s) == 1);
    s.channel = Settings::Channel::Saturation;
    s.rangeMin = .75; s.rangeMax = 1;
    assert(alphaFactor(1, 0, 0, s) == 1);
    assert(alphaFactor(.5, .5, .5, s) == 0);
    assert(maskArgb32(0x80ff0000u, s) == 0x80ff0000u);
    assert(maskArgb32(0x00ff0000u, s) == 0x00ff0000u);
    assert(maskArgb32(0x80808080u, s) == 0x00808080u);
    s.channel = Settings::Channel::Red;
    s.rangeMin = .4; s.rangeMax = .6; s.softness = .2;
    double f = alphaFactor(.3, .7, .2, s);
    assert(std::abs(f - .5) < 1e-9);
    s.invert = true;
    assert(std::abs(alphaFactor(.3, .7, .2, s) + f - 1) < 1e-9);
    s.invert = false;
    auto result = maskArgb32(0x804cb233u, s);
    assert((result & 0xffffffu) == 0x4cb233u);
    assert((result >> 24) > 0 && (result >> 24) < 128);
    s.channel = Settings::Channel::Gray;
    assert(std::abs(selectedChannel(1, 0, 0, s.channel) - .2126) < 1e-9);
    s.channel = Settings::Channel::Green;
    assert(selectedChannel(.1, .2, .3, s.channel) == .2);
    s.channel = Settings::Channel::Blue;
    assert(selectedChannel(.1, .2, .3, s.channel) == .3);
    std::cout << "color range mask tests passed\n";
}
