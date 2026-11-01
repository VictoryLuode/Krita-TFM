/* Standalone color range mask kernel. Input pixels are BGRA8. */
#include <math.h>
#include <stdint.h>
#include <stddef.h>

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif

typedef struct {
    double r, g, b, x, y;
    int add;
} ColorSample;

static int smooth_weight(double distance, double tolerance, double softness) {
    if (softness <= 0.0) return distance <= tolerance ? 255 : 0;
    double t = fmax(0.0, fmin(1.0, (tolerance + softness - distance) / (2.0 * softness)));
    return (int)nearbyint(255.0 * t * t * (3.0 - 2.0 * t));
}

/* 0-5 hue, 6 skin, 7 highlights, 8 midtones, 9 shadows. */
EXPORT int tfm_perceptual_options(const uint8_t *pixels, const uint8_t *luminance,
                          int width, int height, int stride, int mode,
                          int threshold, int invert, int threshold_enabled,
                          double tolerance_override, double softness_override, uint8_t *output) {
    if (!pixels || !luminance || !output || width <= 0 || height <= 0 ||
        stride < 0 || (size_t)stride < (size_t)width * 4 || mode < 0 || mode > 9 ||
        threshold < 0 || threshold > 255 || !isfinite(tolerance_override) ||
        !isfinite(softness_override) || tolerance_override < -1.0 ||
        softness_override < -1.0 || (tolerance_override < 0 && tolerance_override != -1.0) ||
        (softness_override < 0 && softness_override != -1.0)) return -1;
    for (int y = 0; y < height; ++y) {
        const uint8_t *row = pixels + (size_t)y * stride;
        for (int x = 0; x < width; ++x) {
            const uint8_t *p = row + (size_t)x * 4;
            const size_t i = (size_t)y * width + x;
            double r = p[2] / 255.0, g = p[1] / 255.0, b = p[0] / 255.0;
            double high = fmax(r, fmax(g,b)), low = fmin(r, fmin(g,b));
            double delta = high - low, saturation = high > 0 ? delta / high : 0;
            double hue = -1;
            if (delta > 0) {
                if (high == r) hue = 60.0 * fmod((g-b)/delta, 6.0);
                else if (high == g) hue = 60.0 * ((b-r)/delta + 2.0);
                else hue = 60.0 * ((r-g)/delta + 4.0);
                if (hue < 0) hue += 360.0;
            }
            const double legacy_tolerance = threshold_enabled ? fmax(2.0, threshold * 0.65) : 6.0;
            const double tolerance = tolerance_override >= 0 ? tolerance_override : legacy_tolerance;
            const double softness = softness_override >= 0 ? softness_override :
                (threshold_enabled ? fmax(1.0, legacy_tolerance * 0.35) : 8.0);
            int weight = 0;
            if (mode < 6 && hue >= 0 && saturation > 0.04) {
                double distance = fabs(hue - mode * 60.0);
                distance = fmin(distance, 360.0 - distance);
                if (!threshold_enabled) distance += (1.0 - saturation) * 12.0;
                weight = smooth_weight(distance, tolerance, softness);
            } else if (mode == 6 && hue >= 0 && saturation >= 0.08) {
                double hue_distance = fabs(hue - 27.0);
                hue_distance = fmin(hue_distance, 360.0 - hue_distance);
                double hue_tolerance = tolerance_override >= 0 ? tolerance_override : 19.0 + threshold*0.12;
                double hue_softness = softness_override >= 0 ? softness_override : 8.0;
                double component_tolerance = tolerance_override >= 0 ? tolerance_override / 255.0 : 0.0;
                double component_softness = softness_override >= 0 ? softness_override / 255.0 : 0.0;
                int h = smooth_weight(hue_distance, hue_tolerance, hue_softness);
                int s = smooth_weight(fabs(saturation - 0.42),
                                      fmin(1.0, 0.36 + component_tolerance),
                                      softness_override >= 0 ? component_softness : 0.22);
                int v = smooth_weight(fabs(high - 0.72),
                                      fmin(1.0, 0.58 + component_tolerance),
                                      softness_override >= 0 ? component_softness : 0.34);
                weight = (int)nearbyint((double)h * s * v / (255.0 * 255.0));
            } else if (mode >= 7) {
                double lum = luminance[i], soft = softness_override >= 0 ? softness_override : fmax(3.0, threshold * 0.24);
                double distance = mode == 7 ? 255.0 - lum : mode == 8 ? fabs(lum - 128.0) : lum;
                weight = smooth_weight(distance, tolerance_override >= 0 ? tolerance_override : (mode == 8 ? 56.0 : 60.0), soft);
            }
            if (invert) weight = 255 - weight;
            output[i] = (uint8_t)nearbyint(weight * p[3] / 255.0);
        }
    }
    return 0;
}

EXPORT int tfm_perceptual(const uint8_t *pixels, const uint8_t *luminance,
                          int width, int height, int stride, int mode,
                          int threshold, int invert, int threshold_enabled, uint8_t *output) {
    return tfm_perceptual_options(pixels, luminance, width, height, stride, mode,
                                  threshold, invert, threshold_enabled, -1.0, -1.0, output);
}

EXPORT int tfm_channel_mask(const uint8_t *pixels, const uint8_t *luminance,
                            int width, int height, int stride, int channel,
                            int threshold, int invert, int threshold_enabled,
                            double tolerance, double softness, uint8_t *output) {
    if (!pixels || !output || width <= 0 || height <= 0 ||
        stride < 0 || (size_t)stride < (size_t)width * 4 || channel < 0 || channel > 3 ||
        threshold < 0 || threshold > 255 || !isfinite(tolerance) || !isfinite(softness) ||
        (tolerance < 0.0 && tolerance != -1.0) ||
        (softness < 0.0 && softness != -1.0) || (channel == 3 && !luminance)) return -1;
    const int has_options = threshold_enabled || tolerance >= 0.0 || softness >= 0.0;
    const int cutoff = threshold_enabled ? threshold : 128;
    const int adjusted_cutoff = tolerance >= 0.0 ?
        (cutoff > (int)tolerance ? cutoff - (int)tolerance : 0) : cutoff;
    const double edge = softness >= 0.0 ? softness : 0.0;
    for (int y = 0; y < height; ++y) {
        const uint8_t *row = pixels + (size_t)y * stride;
        for (int x = 0; x < width; ++x) {
            const size_t i = (size_t)y * width + x;
            const uint8_t *pixel = row + (size_t)x * 4;
            const int value = channel == 0 ? pixel[2] : channel == 1 ? pixel[1] :
                              channel == 2 ? pixel[0] : luminance[i];
            int weight;
            if (!has_options) {
                weight = invert ? 255 - value : value;
            } else if (edge > 0.0) {
                weight = smooth_weight((double)adjusted_cutoff - value,
                                       0.0, edge);
                if (invert) weight = 255 - weight;
            } else {
                weight = value >= adjusted_cutoff ? 255 : 0;
                if (invert) weight = 255 - weight;
            }
            output[i] = (uint8_t)nearbyint(weight * pixel[3] / 255.0);
        }
    }
    return 0;
}

/* Indexed outline: 0 transparent, 1..8 animated black/white dash phases.
 * The 50% boundary matches selection-outline semantics for soft masks. */
EXPORT int tfm_color_range_outline(const uint8_t *mask, int width, int height,
                                    uint8_t *output) {
    if (!mask || !output || width <= 0 || height <= 0) return -1;
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            size_t i = (size_t)y * width + x;
            int edge = mask[i] >= 128 &&
                (x == 0 || y == 0 || x == width - 1 || y == height - 1 ||
                 mask[i - 1] < 128 || mask[i + 1] < 128 ||
                 mask[i - width] < 128 || mask[i + width] < 128);
            output[i] = edge ? 1 + ((x + y) & 7) : 0;
        }
    }
    return 0;
}

EXPORT int tfm_color_range_combine(const uint8_t *mask, const uint8_t *old,
                                   int width, int height, int mode,
                                   uint8_t *output) {
    if (!mask || !old || !output || width <= 0 || height <= 0 ||
        mode < 0 || mode > 3) return -1;
    const size_t size = (size_t)width * height;
    for (size_t i = 0; i < size; ++i) {
        const unsigned a = old[i], b = mask[i];
        switch (mode) {
        case 0: output[i] = (uint8_t)b; break;
        case 1: output[i] = (uint8_t)(a > b ? a : b); break;
        case 2: output[i] = (uint8_t)((a * (255 - b) + 127) / 255); break;
        case 3: output[i] = (uint8_t)((a * b + 127) / 255); break;
        }
    }
    return 0;
}



EXPORT int tfm_color_range_options(const uint8_t *pixels, int width, int height, int stride, const ColorSample *samples, int count, double fuzziness, int localized, double radius, int invert, int threshold_enabled, double tolerance, double softness, uint8_t *output) {
    if (!pixels || !output || width <= 0 || height <= 0 || stride < 0 || (size_t)stride < (size_t)width*4 || count < 0 || (count && !samples) || !isfinite(fuzziness) || !isfinite(radius) || !isfinite(tolerance) || !isfinite(softness) || (tolerance < 0 && tolerance != -1.0) || (softness < 0 && softness != -1.0)) return -1;
    const double scale=threshold_enabled?fmax(1.0,fuzziness):100.0, falloff=fmax(radius*0.2,0.001);
    for(int y=0;y<height;++y){const uint8_t*row=pixels+(size_t)y*stride;double ny=(y+0.5)/height;for(int x=0;x<width;++x){const uint8_t*q=row+(size_t)x*4;double pos=0,neg=0,nx=(x+0.5)/width;for(int i=0;i<count;++i){const ColorSample*z=samples+i;double dr=q[2]-z->r,dg=q[1]-z->g,db=q[0]-z->b,d=sqrt((dr*dr+dg*dg+db*db)/3.0);double w=(tolerance<0&&softness<0)?fmax(0.0,fmin(1.0,1.0-d/scale)):smooth_weight(d,tolerance>=0?tolerance:scale/2.0,softness>=0?softness:scale/2.0)/255.0;if(localized&&radius<1.0){double zdist=hypot(nx-z->x,ny-z->y);w*=fmax(0.0,fmin(1.0,(radius-zdist)/falloff));}if(z->add)pos=fmax(pos,w);else neg=fmax(neg,w);}int v=(int)nearbyint(255.0*fmax(0.0,pos-neg));if(invert)v=255-v;output[(size_t)y*width+x]=(uint8_t)nearbyint(v*q[3]/255.0);}}return 0;
}

EXPORT int tfm_color_range(const uint8_t *pixels, int width, int height,
                           int stride, const ColorSample *samples, int count,
                           double fuzziness, int localized, double radius,
                           int invert, int threshold_enabled, uint8_t *output) {
    return tfm_color_range_options(pixels, width, height, stride, samples, count,
                                   fuzziness, localized, radius, invert, threshold_enabled,
                                   -1.0, -1.0, output);
}
