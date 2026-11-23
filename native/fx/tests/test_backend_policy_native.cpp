#include "tfm_processing.h"
#include <QCoreApplication>
#include <iostream>
int main(int argc,char **argv) {
    QCoreApplication app(argc,argv);
    qputenv("TFM_BACKEND","auto");
    if (tfm::gpuRequested("tfm_vibrance", 64 * 64)) return 1;
    if (!tfm::gpuRequested("tfm_vibrance", 1024 * 1024) || !tfm::gpuRequested("tfm_bloom", 1)) return 1;
    if (tfm::gpuRequested("tfm_filmgrain", 4096LL * 4096, true) ||
        !tfm::gpuRequested("tfm_filmgrain", 4096LL * 4096) ||
        !tfm::gpuRequested("tfm_filmgrain", 4096LL * 4096 + 1, true)) return 4;
    qputenv("TFM_BACKEND","gpu");
    if (!tfm::gpuRequested("tfm_filmgrain", 4096LL * 4096, true)) return 5;
    if(!tfm::gpuRequested("tfm_vibrance",1) || !tfm::gpuRequested("tfm_filmgrain",1)) return 2;
    qputenv("TFM_BACKEND","cpu");
    if(tfm::gpuRequested("tfm_vibrance",5120LL*5120) || tfm::gpuRequested("tfm_bloom",1)) return 3;
    std::cout<<"Auto prefers GPU with CPU override PASS\n";
}
