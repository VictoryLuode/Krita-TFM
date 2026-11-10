#include "fxmanager_processing.h"
#include <QCoreApplication>
#include <iostream>
int main(int argc,char **argv) {
    QCoreApplication app(argc,argv);
    qputenv("TFM_THREADS","1");
    qputenv("TFM_BACKEND","auto");
    if(fxmanager::gpuRequested("tfm_vibrance",4096LL*4096)
       || !fxmanager::gpuRequested("tfm_vibrance",5120LL*5120)) return 1;
    for(const QString id : {"tfm_color_temperature","tfm_filmgrain","tfm_vignette","tfm_color_range_mask"})
        if(fxmanager::gpuRequested(id,5120LL*5120)) return 2;
    qputenv("TFM_BACKEND","gpu");
    if(!fxmanager::gpuRequested("tfm_vibrance",1) || !fxmanager::gpuRequested("tfm_filmgrain",1)) return 3;
    qputenv("TFM_BACKEND","cpu");
    if(fxmanager::gpuRequested("tfm_vibrance",5120LL*5120)) return 4;
    std::cout<<"Measured Auto policy and explicit backend override PASS\n";
}
