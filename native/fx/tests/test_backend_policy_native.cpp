#include "tfm_processing.h"
#include <QCoreApplication>
#include <iostream>
int main(int argc,char **argv) {
    QCoreApplication app(argc,argv);
    qputenv("TFM_THREADS","1");
    qputenv("TFM_BACKEND","auto");
    qunsetenv("TFM_AUTO_ASSUME_WARM");
    // Cold worker: Vibrance stays on CPU below the measured cold crossover.
    if(tfm::gpuRequested("tfm_vibrance",4096LL*4096)
       || !tfm::gpuRequested("tfm_vibrance",5120LL*5120)) return 1;
    for(const QString id : {"tfm_color_temperature","tfm_filmgrain","tfm_vignette","tfm_color_range_mask"})
        if(tfm::gpuRequested(id,5120LL*5120)) return 2;
    // Warm worker: Vibrance flips earlier; other calibrated filters stay on CPU.
    qputenv("TFM_AUTO_ASSUME_WARM","1");
    if(tfm::gpuRequested("tfm_vibrance",1024LL*1024)
       || !tfm::gpuRequested("tfm_vibrance",2048LL*2048)) return 5;
    for(const QString id : {"tfm_color_temperature","tfm_filmgrain","tfm_vignette","tfm_color_range_mask"})
        if(tfm::gpuRequested(id,5120LL*5120)) return 6;
    qunsetenv("TFM_AUTO_ASSUME_WARM");
    qputenv("TFM_BACKEND","gpu");
    if(!tfm::gpuRequested("tfm_vibrance",1) || !tfm::gpuRequested("tfm_filmgrain",1)) return 3;
    qputenv("TFM_BACKEND","cpu");
    if(tfm::gpuRequested("tfm_vibrance",5120LL*5120)) return 4;
    std::cout<<"Measured Auto policy and explicit backend override PASS\n";
}
