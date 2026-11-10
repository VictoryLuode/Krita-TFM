#pragma once
#include <KoColorProfile.h>
#include <array>
#include <cmath>
#include <cstring>
#include "pointwise_math.h"

namespace fxmanager {
// ICC matrix/TRC profiles define a colour transform without a gamut-clipping
// LUT. Evaluate that transform directly for float storage. Outside the ICC
// domain use signed standard curves, or the endpoint tangent for sampled TRCs.
// LUT profiles retain Krita's colour engine; no guessed matrix is used for them.
class FloatProfileTransform {
    using Matrix = std::array<double, 9>;
    const KoColorProfile *m_profile = nullptr;
    Matrix m_to{}, m_from{};
    double m_gamma = 0;
    bool m_srgb = false;
    std::array<double, 3> m_slope{{1, 1, 1}};

    static Matrix matrix(const QVector<qreal> &v) {
        Matrix result{};
        for (int r=0;r<3;++r) for (int c=0;c<3;++c) result[r*3+c]=v[c*3+r];
        return result;
    }
    static bool inverse(const Matrix &m, Matrix &out) {
        const double d=m[0]*(m[4]*m[8]-m[5]*m[7])-m[1]*(m[3]*m[8]-m[5]*m[6])+m[2]*(m[3]*m[7]-m[4]*m[6]);
        if (!std::isfinite(d) || std::abs(d)<1e-12) return false;
        out={{(m[4]*m[8]-m[5]*m[7])/d,(m[2]*m[7]-m[1]*m[8])/d,(m[1]*m[5]-m[2]*m[4])/d,
              (m[5]*m[6]-m[3]*m[8])/d,(m[0]*m[8]-m[2]*m[6])/d,(m[2]*m[3]-m[0]*m[5])/d,
              (m[3]*m[7]-m[4]*m[6])/d,(m[1]*m[6]-m[0]*m[7])/d,(m[0]*m[4]-m[1]*m[3])/d}};
        return true;
    }
    static Matrix multiply(const Matrix &a,const Matrix &b) {
        Matrix out{};
        for(int r=0;r<3;++r) for(int c=0;c<3;++c) for(int k=0;k<3;++k) out[r*3+c]+=a[r*3+k]*b[k*3+c];
        return out;
    }
    static void apply(const Matrix &m,float *p) {
        const double a=p[0],b=p[1],c=p[2];
        for(int r=0;r<3;++r) p[r]=float(m[r*3]*a+m[r*3+1]*b+m[r*3+2]*c);
    }
    static bool hasLut(const KoColorProfile *profile) {
        const QByteArray raw=profile->rawData();
        if(raw.size()<132) return true;
        auto be=[](const char *p) { return (quint32(quint8(p[0]))<<24)|(quint32(quint8(p[1]))<<16)|(quint32(quint8(p[2]))<<8)|quint8(p[3]); };
        const quint32 count=be(raw.constData()+128);
        if(count>quint32((raw.size()-132)/12)) return true;
        for(quint32 i=0;i<count;++i) {
            const char *tag=raw.constData()+132+i*12;
            if(!std::memcmp(tag,"A2B",3) || !std::memcmp(tag,"B2A",3) || !std::memcmp(tag,"D2B",3) || !std::memcmp(tag,"B2D",3)) return true;
        }
        return false;
    }
    double forward(double x,int channel) const {
        if(m_srgb) return pointwise::decode(float(x));
        if(m_gamma>0) return std::copysign(std::pow(std::abs(x),m_gamma),x);
        const double a=std::abs(x);
        if(a>1) return std::copysign(1+(a-1)*m_slope[channel],x);
        QVector<qreal> v(3,a);m_profile->linearizeFloatValue(v);
        return std::copysign(v[channel],x);
    }
    double backward(double x,int channel) const {
        if(m_srgb) return pointwise::encode(float(x));
        if(m_gamma>0) return std::copysign(std::pow(std::abs(x),1/m_gamma),x);
        const double a=std::abs(x);
        if(a>1) return std::copysign(1+(a-1)/m_slope[channel],x);
        // Invert the actual forward curve, avoiding LCMS's 16-bit reverse table.
        double low=0,high=1;
        for(int n=0;n<25;++n) { const double mid=(low+high)*.5; if(forward(mid,channel)<a) low=mid; else high=mid; }
        return std::copysign((low+high)*.5,x);
    }
public:
    bool initialize(const KoColorProfile *source,const KoColorProfile *working) {
        if(!source || !working || !source->hasColorants() || !source->hasTRC() || hasLut(source)) return false;
        const auto a=source->getColorantsXYZ(), b=working->getColorantsXYZ();
        if(a.size()!=9 || b.size()!=9) return false;
        Matrix inv;
        if(!inverse(matrix(b),inv)) return false;
        m_to=multiply(inv,matrix(a));
        if(!inverse(m_to,m_from)) return false;
        m_profile=source;
        switch(source->getTransferCharacteristics()) {
        case TRC_LINEAR:m_gamma=1;break;
        case TRC_GAMMA_1_8:m_gamma=1.8;break;
        case TRC_GAMMA_2_4:m_gamma=2.4;break;
        case TRC_ITU_R_BT_470_6_SYSTEM_M:m_gamma=2.2;break;
        case TRC_ITU_R_BT_470_6_SYSTEM_B_G:m_gamma=2.8;break;
        case TRC_A98:m_gamma=563.0/256.0;break;
        case TRC_IEC_61966_2_1:m_srgb=true;break;
        default:break;
        }
        if(!m_gamma && !m_srgb) {
            QVector<qreal> low(3,0),high(3,1),nearHigh(3,.999);
            source->linearizeFloatValue(low);source->linearizeFloatValue(high);source->linearizeFloatValue(nearHigh);
            for(int c=0;c<3;++c) {
                m_slope[c]=(high[c]-nearHigh[c])/.001;
                if(std::abs(low[c])>1e-6 || std::abs(high[c]-1)>1e-5 || !std::isfinite(m_slope[c]) || m_slope[c]<=0) return false;
            }
        }
        return true;
    }
    void toWorking(float *p) const { for(int c=0;c<3;++c) p[c]=float(forward(p[c],c));apply(m_to,p); }
    void fromWorking(float *p) const { apply(m_from,p);for(int c=0;c<3;++c) p[c]=float(backward(p[c],c)); }
};
}
