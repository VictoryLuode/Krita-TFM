#include "tfm_lens_distortion.h"
#include "tfm_lens_distortion_widget.h"
#include "tfm_processing.h"
#include "tfm_lens_gpu.h"

#include <algorithm>
#include <cmath>
#include <array>
#include <QImage>
#include <filter/kis_filter_category_ids.h>
#include <filter/kis_filter_configuration.h>
#include <kis_paint_device.h>
#include <kis_painter.h>
#include <KisGlobalResourcesInterface.h>
#include <KoUpdater.h>
#include <klocalizedstring.h>

namespace {

constexpr double kMinimumDistortion = -0.999;
constexpr double kHorizontalDispersionScale = 5.0;
constexpr double kRadialDispersionScale = 4.0;
constexpr double kDistortionScale = 4.0;

QRgb sampleBilinear(const QImage &image, double x, double y)
{
    const int width = image.width();
    const int height = image.height();
    if (width <= 0 || height <= 0) {
        return qRgba(0, 0, 0, 0);
    }
    const double maxX = double(width - 1);
    const double maxY = double(height - 1);
    if (x < -0.5 || y < -0.5 || x > maxX + 0.5 || y > maxY + 0.5) {
        return qRgba(0, 0, 0, 0);
    }
    const double sx = std::clamp(x, 0.0, maxX);
    const double sy = std::clamp(y, 0.0, maxY);
    const int x0 = int(std::floor(sx));
    const int y0 = int(std::floor(sy));
    const int x1 = std::min(x0 + 1, image.width() - 1);
    const int y1 = std::min(y0 + 1, image.height() - 1);
    const double fx = sx - x0;
    const double fy = sy - y0;
    const QRgb *row0 = reinterpret_cast<const QRgb *>(image.constScanLine(y0));
    const QRgb *row1 = reinterpret_cast<const QRgb *>(image.constScanLine(y1));
    const QRgb a = row0[x0];
    const QRgb b = row0[x1];
    const QRgb c = row1[x0];
    const QRgb d = row1[x1];
    auto mix = [&](int channel) {
        auto component = [channel](QRgb pixel) {
            switch (channel) {
            case 0: return qRed(pixel);
            case 1: return qGreen(pixel);
            case 2: return qBlue(pixel);
            default: return qAlpha(pixel);
            }
        };
        const double top = (1.0 - fx) * component(a) + fx * component(b);
        const double bottom = (1.0 - fx) * component(c) + fx * component(d);
        return int(std::lround((1.0 - fy) * top + fy * bottom));
    };
    return qRgba(mix(0), mix(1), mix(2), mix(3));
}
template <typename Read, typename Write>
void renderLens(const QRect &frame,const QRect &outputRect,bool horizontal,double distortion,
                double dispersion,bool fit,bool jitter,KoUpdater *updater,Read read,Write write)
{
    const double width = frame.width();
    const double height = frame.height();
    const double centerX = width * 0.5;
    const double centerY = height * 0.5;

    // Blender: green keeps the requested distortion, red/blue get +-dispersion/4,
    // and all three are multiplied by DISTORTION_SCALE.
    const double radialDispersion = dispersion / kRadialDispersionScale;
    const double redInput = std::clamp(distortion + radialDispersion, kMinimumDistortion, 1.0);
    const double blueInput = std::clamp(distortion - radialDispersion, kMinimumDistortion, 1.0);
    const double chromatic[3] = {
        redInput * kDistortionScale,
        distortion * kDistortionScale,
        blueInput * kDistortionScale
    };
    // compute_scale()
    const double maximumDistortion = std::max({redInput, distortion, blueInput});
    const double scale = (fit && maximumDistortion > 0.0)
        ? 1.0 / (1.0 + 2.0 * maximumDistortion)
        : 1.0 / (1.0 + maximumDistortion);
    const double horizontalDispersion = dispersion * kHorizontalDispersionScale / std::max(1.0, width);

    // Krita may already render this Filter Layer in tiles; keep the row loop
    // local to the requested rect and write only that rect back. Rows are
    // independent (source is read-only, each worker owns whole output rows),
    // so the band pass can run in parallel without touching host tiling.
    tfm::parallelRows(outputRect.height(), [&](int y0, int y1) {
    for (int y = y0; y < y1; ++y) {
        if(updater && updater->interrupted()) return;
        const double imageY = outputRect.y() - frame.y() + y + 0.5;
        for (int x = 0; x < outputRect.width(); ++x) {
            const double imageX = outputRect.x() - frame.x() + x + 0.5;

            if (horizontal) {
                // execute_horizontal_distortion_cpu(): normalized sample offsets.
                const double normalizedX = imageX / width;
                const double normalizedY = imageY / height;
                const auto red = read((normalizedX + horizontalDispersion) * width - 0.5, imageY - 0.5);
                const auto green = read(imageX - 0.5, imageY - 0.5);
                const auto blue = read((normalizedX - horizontalDispersion) * width - 0.5, imageY - 0.5);
                const double alpha = (red[3]+green[3]+blue[3])/3.0;
                Q_UNUSED(normalizedY);
                write(x,y,{red[0],green[1],blue[2],alpha});
                continue;
            }

            // radial_lens_distortion(): centred normalized UV, per-axis centre.
            const double uvx = scale * (imageX - centerX) / centerX;
            const double uvy = scale * (imageY - centerY) / centerY;
            const double distanceSquared = uvx * uvx + uvy * uvy;

            if (chromatic[0] * distanceSquared > 1.0
                || chromatic[1] * distanceSquared > 1.0
                || chromatic[2] * distanceSquared > 1.0) {
                write(x,y,{0,0,0,0});
                continue;
            }

            auto distortionScale = [distanceSquared](double value) {
                return 1.0 / (1.0 + std::sqrt(std::max(0.0, 1.0 - value * distanceSquared)));
            };

            const double redScale = distortionScale(chromatic[0]);
            const double greenScale = distortionScale(chromatic[1]);
            const double blueScale = distortionScale(chromatic[2]);
            const double redX = (uvx * redScale + 0.5) * width;
            const double redY = (uvy * redScale + 0.5) * height;
            const double greenX = (uvx * greenScale + 0.5) * width;
            const double greenY = (uvy * greenScale + 0.5) * height;
            const double blueX = (uvx * blueScale + 0.5) * width;
            const double blueY = (uvy * blueScale + 0.5) * height;

            auto stepsFor = [jitter](double amount, int seed) {
                if (jitter) {
                    return amount < 4.0 ? 2 : int(std::sqrt(amount + 1.0));
                }
                Q_UNUSED(seed);
                return int(amount + 1.0);
            };
            const int stepsRed = std::max(1, stepsFor(std::hypot(redX - greenX, redY - greenY), 0));
            const int stepsBlue = std::max(1, stepsFor(std::hypot(greenX - blueX, greenY - blueY), 1));
            const int stepsGreen = stepsRed + stepsBlue;

            double accumulated[4] = {0.0, 0.0, 0.0, 0.0};
            auto integrate = [&](int start, int end, int steps) {
                const double amount = chromatic[end] - chromatic[start];
                for (int i = 0; i < steps; ++i) {
                    const double increment = (i + (jitter
                        ? (tfm::deterministicNoise(int(imageX-0.5), int(imageY-0.5), start * steps + i, 71) + 1.0) * 0.5
                        : 0.5)) / steps;
                    const double value = chromatic[start] + increment * amount;
                    const double channelScale = 1.0 / (1.0 + std::sqrt(std::max(0.0, 1.0 - value * distanceSquared)));
                    const double sampleX = (uvx * channelScale + 0.5) * width - 0.5;
                    const double sampleY = (uvy * channelScale + 0.5) * height - 0.5;
                    const auto pixel = read(sampleX, sampleY);
                    const double startValue = pixel[start];
                    const double endValue = pixel[end];
                    accumulated[start] += (1.0 - increment) * startValue;
                    accumulated[end] += increment * endValue;
                    accumulated[3] += pixel[3];
                }
            };
            integrate(0, 1, stepsRed);
            integrate(1, 2, stepsBlue);

            accumulated[0] *= 2.0 / stepsRed;
            accumulated[1] *= 2.0 / stepsGreen;
            accumulated[2] *= 2.0 / stepsBlue;
            accumulated[3] /= stepsGreen;
            write(x,y,{accumulated[0],accumulated[1],accumulated[2],accumulated[3]});
        }
    }
    });
}

}

KisFilterLensDistortion::KisFilterLensDistortion()
    : KisFilter(id(), FiltersCategoryArtisticId, i18n("&Lens Distortion..."))
{
    setSupportsAdjustmentLayers(true);
    setColorSpaceIndependence(FULLY_INDEPENDENT);
    // A radial mapper samples arbitrary pixels from the whole image. Processing
    // isolated Krita patches would create one lens per patch (a tiled result).
    setSupportsThreading(false);
}
KisFilterConfigurationSP KisFilterLensDistortion::defaultConfiguration(KisResourcesInterfaceSP r) const
{
    auto configuration = factoryConfiguration(r);

    tfm::applyBuiltinDefaults(id().id(), configuration);
    tfm::applyFilterDefaults(id().id(), configuration); return configuration;
}
KisConfigWidget *KisFilterLensDistortion::createConfigurationWidget(QWidget *parent,
                                                                     const KisPaintDeviceSP,
                                                                     bool) const
{
    return new LensDistortionConfigurationWidget(id().id(), parent);
}

bool KisFilterLensDistortion::needsTransparentPixels(const KisFilterConfigurationSP, const KoColorSpace *) const
{
    return true;
}

QRect KisFilterLensDistortion::neededRect(const QRect &rect,
                                          const KisFilterConfigurationSP,
                                          int) const
{
    // Lens Distortion samples outside the output patch. Request a bounded
    // halo around it so patch edges do not become transparent seams, while
    // avoiding the unbounded rectangle that can explode group projections.
    const int marginX = std::max(1, rect.width());
    const int marginY = std::max(1, rect.height());
    return rect.adjusted(-marginX, -marginY, marginX, marginY);
}

void KisFilterLensDistortion::processImpl(KisPaintDeviceSP device,
                                          const QRect &rect,
                                          const KisFilterConfigurationSP configuration,
                                          KoUpdater *updater) const
{
    if (rect.isEmpty() || !device || (updater && updater->interrupted())) return;

    const QString mode = configuration ? configuration->getString("mode", "radial") : QStringLiteral("radial");
    const double distortion = std::clamp(
        configuration ? configuration->getDouble("distortion", 0.0) : 0.0,
        kMinimumDistortion,
        1.0);
    const double dispersion = std::clamp(
        configuration ? configuration->getDouble("dispersion", 0.0) : 0.0,
        0.0,
        1.0);
    const bool horizontal = mode == QStringLiteral("horizontal");
    const bool fit = configuration && configuration->getBool("fit", false);
    const bool jitter = configuration && configuration->getBool("jitter", false);
    if ((!horizontal && std::abs(distortion) < 1e-9 && dispersion < 1e-9)
        || (horizontal && dispersion < 1e-9)) return;

    QRect frame = device->defaultBounds()->bounds();
    if (frame.isEmpty()) frame = device->extent();
    if (frame.isEmpty()) frame = rect;
    const QRect outputRect = rect.intersected(frame);
    if (outputRect.isEmpty()) return;

    // Filter layers call processImpl once per region and write each result back
    // into the device, so a later region would sample the pixels an earlier
    // region already distorted and bend the frame more than once. Read the
    // transaction baseline instead of the live device.
    KisPaintDeviceSP pristine = new KisPaintDevice(device->colorSpace());
    pristine->prepareClone(device);
    KisPainter::copyAreaOptimizedOldData(frame.topLeft(), device, pristine, frame);
    if(tfm::requiresFloatProcessing(device)) {
        const auto source=tfm::readEncodedImage(pristine,frame);
        if(source.isNull()) return;
        tfm::EncodedRgbaImage output{outputRect.width(),outputRect.height(),QVector<float>(outputRect.width()*outputRect.height()*4)};
        const float *src=source.pixels.constData();
        float *dst=output.pixels.data();
        renderLens(frame,outputRect,horizontal,distortion,dispersion,fit,jitter,updater,
            [&](double x,double y) {
                std::array<double,4> value{};
                if(x<-.5 || y<-.5 || x>source.width-.5 || y>source.height-.5) return value;
                const double sx=std::clamp(x,0.0,double(source.width-1)),sy=std::clamp(y,0.0,double(source.height-1));
                const int x0=int(sx),y0=int(sy),x1=std::min(x0+1,source.width-1),y1=std::min(y0+1,source.height-1);
                const double fx=sx-x0,fy=sy-y0;
                for(int c=0;c<4;++c) {
                    const double top=(1-fx)*src[4*(y0*source.width+x0)+c]+fx*src[4*(y0*source.width+x1)+c];
                    const double bottom=(1-fx)*src[4*(y1*source.width+x0)+c]+fx*src[4*(y1*source.width+x1)+c];
                    value[c]=(1-fy)*top+fy*bottom;
                }
                return value;
            },[&](int x,int y,std::array<double,4> value) {
                for(int c=0;c<4;++c) dst[4*(y*output.width+x)+c]=float(value[c]);
            });
        if(updater && updater->interrupted()) return;
        const bool written=tfm::writeEncodedImage(device,output,outputRect);
        tfm::reportBackend(id().id(),QStringLiteral("cpu"),written
            ? QStringLiteral("High-depth CPU: float GPU implementation unavailable")
            : QStringLiteral("Float output conversion failed; pixels unchanged"));
        if(written && updater) updater->setProgress(100);
        return;
    }
    const QImage source = tfm::readImage(pristine, frame);
    if (source.isNull()) return;
    if (tfm::gpuRequested(id().id())) {
        QImage gpuOutput;
        QString reason;
        QString gpuDevice;
        if (tfm_lens_gpu::render(source, frame, outputRect, horizontal, distortion,
                                 dispersion, fit, jitter, gpuOutput, reason, gpuDevice, [updater] { return updater && updater->interrupted(); })) {
            if(updater && updater->interrupted()) return;
            tfm::writeImage(device, gpuOutput, outputRect);
            tfm::reportBackend(id().id(), QStringLiteral("gpu"), QString(), gpuDevice);
            if (updater) updater->setProgress(100);
            return;
        }
        if(updater && updater->interrupted()) return;
        tfm::reportBackend(id().id(), QStringLiteral("cpu"), reason);
    } else {
        tfm::reportBackend(id().id(), QStringLiteral("cpu"), QStringLiteral("CPU selected"));
    }
    QImage output(outputRect.size(), QImage::Format_ARGB32);

    uchar *outputBits=output.bits();
    const int stride=output.bytesPerLine();
    renderLens(frame,outputRect,horizontal,distortion,dispersion,fit,jitter,updater,
        [&](double x,double y) {
            const auto p=sampleBilinear(source,x,y);
            return std::array<double,4>{double(qRed(p)),double(qGreen(p)),double(qBlue(p)),double(qAlpha(p))};
        },[&](int x,int y,std::array<double,4> value) {
            auto channel=[&](int c) { return std::clamp(int(std::lround(value[c])),0,255); };
            reinterpret_cast<QRgb*>(outputBits+y*stride)[x]=qRgba(channel(0),channel(1),channel(2),channel(3));
        });
    if(updater && updater->interrupted()) return;

    tfm::writeImage(device, output, outputRect);
    if (updater) updater->setProgress(100);
}
