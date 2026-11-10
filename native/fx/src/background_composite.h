#pragma once
#include <cstddef>
#include <cstdint>

namespace fxmanager::background_removal {
// The estimator sees a bounded U8 proxy. Apply its colour correction to the
// original float image; never replace HDR/detail with the quantized proxy.
inline void compositeRefined(float *original,const float *foreground,
                             const std::uint8_t *inferenceRgb,const std::uint8_t *mask,
                             std::size_t pixels)
{
    for(std::size_t i=0;i<pixels;++i) {
        for(int c=0;c<3;++c)
            original[i*4+c]+=foreground[i*4+c]-float(inferenceRgb[i*3+c])/255.0f;
        original[i*4+3]*=float(mask[i])/255.0f;
    }
}
}
