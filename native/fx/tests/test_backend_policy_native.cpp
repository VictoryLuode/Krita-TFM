#include "tfm_processing.h"
#include <QCoreApplication>
#include <iostream>
int main(int argc,char **argv) {
    QCoreApplication app(argc,argv);
    qputenv("TFM_BACKEND","auto");
    // Auto prefers GPU for every Vulkan-capable filter; size thresholds are gone.
    for(const QString id : {"tfm_vibrance","tfm_color_temperature","tfm_filmgrain","tfm_vignette",
                            "tfm_color_range_mask","tfm_bloom","tfm_lens_flare","tfm_kuwahara",
                            "tfm_halation","tfm_guided_color_match","tfm_lens_distortion",
                            "tfm_motion_blur_circular","tfm_motion_blur_zoom"}) {
        if(!tfm::gpuRequested(id,1) || !tfm::gpuRequested(id,64LL*64)) return 1;
    }
    qputenv("TFM_BACKEND","gpu");
    if(!tfm::gpuRequested("tfm_vibrance",1) || !tfm::gpuRequested("tfm_filmgrain",1)) return 2;
    qputenv("TFM_BACKEND","cpu");
    if(tfm::gpuRequested("tfm_vibrance",5120LL*5120) || tfm::gpuRequested("tfm_bloom",1)) return 3;
    std::cout<<"Auto prefers GPU with CPU override PASS\n";
}
