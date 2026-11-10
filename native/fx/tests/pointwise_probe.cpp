#include "pointwise_math.h"
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <vector>

using namespace tfm::pointwise;
static void require(bool ok,const char *message) { if(!ok) throw std::runtime_error(message); }
int main(int argc,char **argv) try {
    if(argc==1) {
        require(skinWeight(0.07,0.5)==1.0,"target skin hue not protected");
        require(skinWeight(0.12,0.5)>0.999999,"inner boundary not protected");
        require(skinWeight(0.20,0.5)>0 && skinWeight(0.20,0.5)<1,"falloff missing");
        require(skinWeight(0.25,0.5)<1e-12 && skinWeight(0.6,0.5)==0,"distant hue protected");
        require(skinWeight(0.07,0.03)==0 && skinWeight(0.07,0.10)<1,"low saturation mask wrong");
        require(std::abs(skinWeight(0.99,0.5)-skinWeight(0.15,0.5))<1e-12,"hue seam discontinuity");
        for(float x : {-8.0f,-1.0f,-0.01f,0.0f,0.003f,0.2f,1.0f,4.0f,128.0f})
            require(std::abs(decode(encode(x))-x)<=1e-6f+std::abs(x)*2e-6f,"extended transfer roundtrip");
        const auto gain=temperatureGains(6500,100);
        require(std::abs(gain.g-1.2)<1e-12,"tint is not normalized");
        std::cout<<"production pointwise math PASS"<<std::endl; return 0;
    }
    require(argc==9,"input output operation p0 p1 p2 p3 p4 required");
    std::ifstream input(argv[1],std::ios::binary);
    std::vector<unsigned char> data{std::istreambuf_iterator<char>(input),std::istreambuf_iterator<char>()};
    require(!data.empty() && data.size()%4==0,"invalid pixel buffer");
    const int op=std::stoi(argv[3]);
    const double p0=std::stod(argv[4]),p1=std::stod(argv[5]),p2=std::stod(argv[6]),p3=std::stod(argv[7]),p4=std::stod(argv[8]);
    for(std::size_t i=0;i<data.size();i+=4) {
        const Rgb c{data[i+2]/255.0,data[i+1]/255.0,data[i]/255.0};
        const auto out=op==4 ? vibrance(c,{p0/100.0,p1/100.0,p2,p3,p4},true)
                            : temperature(c,temperatureGains(p0,p1),p2,p3>0.5,true);
        data[i]=static_cast<unsigned char>(std::lround(out.b*255));
        data[i+1]=static_cast<unsigned char>(std::lround(out.g*255));
        data[i+2]=static_cast<unsigned char>(std::lround(out.r*255));
    }
    std::ofstream output(argv[2],std::ios::binary); output.write(reinterpret_cast<char*>(data.data()),data.size());
    require(bool(output),"cannot save output"); return 0;
} catch(const std::exception &e) { std::cerr<<e.what()<<std::endl; return 1; }
