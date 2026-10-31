#include "fxm_gegl_motion_blur.h"

#include "fxmanager_processing.h"
#include "fxm_blur_point_preview.h"

#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QSignalBlocker>
#include <QSlider>
#include <QVBoxLayout>
#include <QHash>
#include <list>
#include <atomic>

#include <KisGlobalResourcesInterface.h>
#include <KoUpdater.h>
#include <filter/kis_filter_category_ids.h>
#include <filter/kis_filter_configuration.h>
#include <kis_default_bounds_base.h>
#include <kis_paint_device.h>
#include <kis_painter.h>
#include <klocalizedstring.h>

#include <algorithm>
#include <cmath>

namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr int kMaxSaneDimension = 65536;

bool isSaneFrame(const QRect &r)
{
    return !r.isEmpty() && r.width() > 0 && r.height() > 0
        && r.width() <= kMaxSaneDimension && r.height() <= kMaxSaneDimension
        && std::abs(r.x()) <= kMaxSaneDimension && std::abs(r.y()) <= kMaxSaneDimension;
}

QRect extractDeviceFrame(const KisPaintDeviceSP &dev)
{
    if (!dev) return QRect();
    if (dev->defaultBounds()) {
        const QRect bounds = dev->defaultBounds()->bounds();
        if (isSaneFrame(bounds)) {
            return bounds;
        }
    }
    const QRect exact = dev->exactBounds();
    if (isSaneFrame(exact)) {
        return exact;
    }
    return QRect();
}

double wrapAngleRad(double a)
{
    while (a <= -kPi) a += 2.0 * kPi;
    while (a > kPi) a -= 2.0 * kPi;
    return a;
}

QRect computeCircularSweptRect(const QRect &rect,
                               const QRect &refFrame,
                               double centerX,
                               double centerY,
                               double angleDeg)
{
    if (rect.isEmpty()) return rect;
    const double clampedAngle = std::clamp(angleDeg, 0.0, 360.0);
    if (clampedAngle <= 1e-4) {
        return rect.adjusted(-3,-3,3,3);
    }

    const double cx = double(refFrame.x()) + centerX * double(refFrame.width());
    const double cy = double(refFrame.y()) + centerY * double(refFrame.height());
    // gegl:motion-blur-circular clamps half-angle to pi/2 in prepare() and sweeps [-angle/2, +angle/2] in process().
    const double halfAngle = std::min(clampedAngle * kPi / 180.0, 2.0 * kPi) * 0.5;

    const double x0 = double(rect.left());
    const double y0 = double(rect.top());
    const double x1 = double(rect.right() + 1);
    const double y1 = double(rect.bottom() + 1);

    double minX = x0;
    double maxX = x1;
    double minY = y0;
    double maxY = y1;

    auto includePoint = [&](double px, double py) {
        minX = std::min(minX, px);
        maxX = std::max(maxX, px);
        minY = std::min(minY, py);
        maxY = std::max(maxY, py);
    };

    const double cosH = std::cos(halfAngle);
    const double sinH = std::sin(halfAngle);

    auto includeRotated = [&](double px, double py) {
        const double dx = px - cx;
        const double dy = py - cy;
        // Rotate by +halfAngle and -halfAngle
        includePoint(cx + dx * cosH - dy * sinH, cy + dx * sinH + dy * cosH);
        includePoint(cx + dx * cosH + dy * sinH, cy - dx * sinH + dy * cosH);
    };

    const double clampedCx = std::clamp(cx, x0, x1);
    const double clampedCy = std::clamp(cy, y0, y1);

    // 4 corners + 4 closest edge projections
    includeRotated(x0, y0);
    includeRotated(x1, y0);
    includeRotated(x1, y1);
    includeRotated(x0, y1);
    includeRotated(clampedCx, y0);
    includeRotated(clampedCx, y1);
    includeRotated(x0, clampedCy);
    includeRotated(x1, clampedCy);

    // Check cardinal axis crossings (0, pi/2, pi, -pi/2) for the 4 corners (which achieve max radius).
    const double corners[4][2] = {{x0, y0}, {x1, y0}, {x1, y1}, {x0, y1}};
    const double cardinals[4][3] = {
        {0.0, 1.0, 0.0},
        {0.5 * kPi, 0.0, 1.0},
        {kPi, -1.0, 0.0},
        {-0.5 * kPi, 0.0, -1.0}
    };
    for (const auto &corner : corners) {
        const double dx = corner[0] - cx;
        const double dy = corner[1] - cy;
        const double r = std::hypot(dx, dy);
        if (r <= 1e-6) continue;
        const double phi = std::atan2(dy, dx);
        for (const auto &card : cardinals) {
            if (std::abs(wrapAngleRad(card[0] - phi)) <= halfAngle) {
                includePoint(cx + r * card[1], cy + r * card[2]);
            }
        }
    }

    constexpr int kInterpMargin = 3;
    if (!std::isfinite(minX) || !std::isfinite(minY) || !std::isfinite(maxX) || !std::isfinite(maxY)
        || minX < -1000000000.0 || minY < -1000000000.0
        || maxX > 1000000000.0 || maxY > 1000000000.0) return QRect();
    const int left = int(std::floor(minX)) - kInterpMargin;
    const int top = int(std::floor(minY)) - kInterpMargin;
    const int right = int(std::ceil(maxX)) + kInterpMargin;
    const int bottom = int(std::ceil(maxY)) + kInterpMargin;
    const QRect swept(left, top, std::max(1, right - left), std::max(1, bottom - top));
    return swept.united(rect);
}

QRect computeZoomChangedRect(const QRect &rect,
                             const QRect &refFrame,
                             double centerX,
                             double centerY,
                             double factor)
{
    if (rect.isEmpty()) return rect;
    const double clampedFactor = std::clamp(factor, -10.0, 1.0);
    if (std::abs(clampedFactor) <= 1e-5) {
        return rect;
    }

    const double denom = 1.0 - clampedFactor * (199.0 / 200.0);
    if (denom <= 0.0) return rect;

    const double cx = double(refFrame.x()) + centerX * double(refFrame.width());
    const double cy = double(refFrame.y()) + centerY * double(refFrame.height());

    const double u0 = double(rect.left() - 2);
    const double v0 = double(rect.top() - 2);
    const double u1 = double(rect.right() + 3);
    const double v1 = double(rect.bottom() + 3);

    // Inverse of u = x + t * factor * (cx - x) at t = 1 is x = cx + (u - cx) / (1 - factor).
    const double x0Inv = cx + (u0 - cx) / denom;
    const double x1Inv = cx + (u1 - cx) / denom;
    const double y0Inv = cy + (v0 - cy) / denom;
    const double y1Inv = cy + (v1 - cy) / denom;

    const double minX = std::min({u0, u1, x0Inv, x1Inv});
    const double maxX = std::max({u0, u1, x0Inv, x1Inv});
    const double minY = std::min({v0, v1, y0Inv, y1Inv});
    const double maxY = std::max({v0, v1, y0Inv, y1Inv});

    if (!std::isfinite(minX) || !std::isfinite(minY) || !std::isfinite(maxX) || !std::isfinite(maxY)
        || minX < -1000000000.0 || minY < -1000000000.0 || maxX > 1000000000.0 || maxY > 1000000000.0) return rect;
    const int left = int(std::floor(minX)) - 2;
    const int top = int(std::floor(minY)) - 2;
    const int right = int(std::ceil(maxX)) + 2;
    const int bottom = int(std::ceil(maxY)) + 2;
    const QRect changed(left, top, std::max(1, right-left), std::max(1, bottom-top));
    return changed.united(rect);
}

QSlider *makeBoundSlider(QWidget *parent,
                         QDoubleSpinBox *spin,
                         double minVal,
                         double maxVal,
                         double step,
                         int decimals,
                         double initialVal,
                         QHBoxLayout **rowOut)
{
    spin->setRange(minVal, maxVal);
    spin->setSingleStep(step);
    spin->setDecimals(decimals);
    spin->setValue(initialVal);

    auto *slider = new QSlider(Qt::Horizontal, parent);
    const int steps = std::max(1, int(std::llround((maxVal - minVal) / step)));
    slider->setRange(0, steps);
    slider->setValue(int(std::llround((initialVal - minVal) / step)));

    QObject::connect(slider, &QSlider::valueChanged, spin, [spin, minVal, step](int v) {
        spin->setValue(minVal + double(v) * step);
    });
    QObject::connect(spin, QOverload<double>::of(&QDoubleSpinBox::valueChanged), slider, [slider, minVal, step](double v) {
        const QSignalBlocker blocker(slider);
        slider->setValue(int(std::llround((v - minVal) / step)));
    });

    auto *row = new QHBoxLayout();
    row->setContentsMargins(0, 0, 0, 0);
    row->addWidget(slider, 1);
    row->addWidget(spin);
    *rowOut = row;
    return slider;
}

} // namespace

FxmGeglMotionBlur::FxmGeglMotionBlur(Variant variant)
    : KisFilter(variant == Variant::Circular ? circularId() : zoomId(),
                FiltersCategoryBlurId,
                variant == Variant::Circular ? i18n("&Circular Motion Blur...")
                                             : i18n("&Zoom Motion Blur..."))
    , m_variant(variant)
{
    setSupportsPainting(false);
    setSupportsAdjustmentLayers(true);
    setSupportsThreading(false);
    setSupportsLevelOfDetail(false);
    setColorSpaceIndependence(FULLY_INDEPENDENT);
}

QRect FxmGeglMotionBlur::resolveReferenceFrame(const KisFilterConfigurationSP &config)
{
    if (config) {
        const QRect saved(
            config->getInt("frame_x", 0),
            config->getInt("frame_y", 0),
            config->getInt("frame_width", 0),
            config->getInt("frame_height", 0));
        if (isSaneFrame(saved)) {
            return saved;
        }
    }
    return DefaultReferenceFrame();
}

bool FxmGeglMotionBlur::configurationAllowedForMask(KisFilterConfigurationSP) const
{
    return true;
}

KisFilterConfigurationSP FxmGeglMotionBlur::defaultConfiguration(KisResourcesInterfaceSP resourcesInterface) const
{
    KisFilterConfigurationSP c = factoryConfiguration(resourcesInterface);
    c->setProperty("center_x", 0.5);
    c->setProperty("center_y", 0.5);
    if (m_variant == Variant::Circular) {
        c->setProperty("angle", 20.0);
    } else {
        c->setProperty("factor", 0.1);
    }
    const QRect defFrame = DefaultReferenceFrame();
    c->setProperty("frame_x", defFrame.x());
    c->setProperty("frame_y", defFrame.y());
    c->setProperty("frame_width", defFrame.width());
    c->setProperty("frame_height", defFrame.height());
    c->setProperty("frame_initialized", false);
    fxmanager::applyFilterDefaults(id(), c);
    return c;
}

QRect FxmGeglMotionBlur::neededRect(const QRect &rect, const KisFilterConfigurationSP config, int) const
{
    if (rect.isEmpty()) return rect;
    const QRect frame = resolveReferenceFrame(config);
    const double cx = config ? config->getDouble("center_x", 0.5) : 0.5;
    const double cy = config ? config->getDouble("center_y", 0.5) : 0.5;
    if (m_variant == Variant::Circular) {
        return computeCircularSweptRect(rect, frame, cx, cy,
            config ? config->getDouble("angle", 20.0) : 20.0);
    }
    const double factor = std::clamp(config ? config->getDouble("factor", 0.1) : 0.1, -10.0, 1.0);
    const double scale = 1.0 - factor * (199.0 / 200.0);
    const double gx = frame.x() + cx * frame.width();
    const double gy = frame.y() + cy * frame.height();
    const double ax = gx + (rect.left() - gx) * scale;
    const double bx = gx + (rect.right() - gx) * scale;
    const double ay = gy + (rect.top() - gy) * scale;
    const double by = gy + (rect.bottom() - gy) * scale;
    const double l = std::min({double(rect.left()), ax, bx});
    const double r = std::max({double(rect.right()), ax, bx});
    const double t = std::min({double(rect.top()), ay, by});
    const double b = std::max({double(rect.bottom()), ay, by});
    if (!std::isfinite(l) || !std::isfinite(r) || !std::isfinite(t) || !std::isfinite(b)
        || l < -1000000000.0 || t < -1000000000.0 || r > 1000000000.0 || b > 1000000000.0) return QRect();
    return QRect(QPoint(int(std::floor(l)) - 3, int(std::floor(t)) - 3),
                 QPoint(int(std::ceil(r)) + 3, int(std::ceil(b)) + 3));
}

QRect FxmGeglMotionBlur::changedRect(const QRect &rect, const KisFilterConfigurationSP config, int) const
{
    if (rect.isEmpty()) return rect;
    const QRect frame = resolveReferenceFrame(config);
    const double cx = config ? config->getDouble("center_x", 0.5) : 0.5;
    const double cy = config ? config->getDouble("center_y", 0.5) : 0.5;
    if (m_variant == Variant::Circular) {
        // Expand the source interpolation footprint before taking its inverse sweep.
        return computeCircularSweptRect(rect.adjusted(-2, -2, 2, 2), frame, cx, cy,
            config ? config->getDouble("angle", 20.0) : 20.0);
    }
    return computeZoomChangedRect(rect, frame, cx, cy,
        config ? config->getDouble("factor", 0.1) : 0.1);
}

KisConfigWidget *FxmGeglMotionBlur::createConfigurationWidget(QWidget *parent, const KisPaintDeviceSP dev, bool) const
{
    return new Widget(m_variant, extractDeviceFrame(dev), dev, parent);
}

void FxmGeglMotionBlur::processImpl(KisPaintDeviceSP device, const QRect &rect,
                                  const KisFilterConfigurationSP config, KoUpdater *progressUpdater) const
{
    if (!device || rect.isEmpty()) return;
    const QRect frame = resolveReferenceFrame(config);
    const double gx = frame.x() + (config ? config->getDouble("center_x", 0.5) : 0.5) * frame.width();
    const double gy = frame.y() + (config ? config->getDouble("center_y", 0.5) : 0.5) * frame.height();
    const QRect read = neededRect(rect, config, 0);
    const qint64 n = qint64(read.width()) * read.height();
    if (read.isEmpty() || n <= 0) return;
    const bool circular = m_variant == Variant::Circular;
    const double angle = circular ? std::clamp(config ? config->getDouble("angle", 20.0) : 20.0, 0.0, 360.0) : 20.0;
    const double factor = !circular ? std::clamp(config ? config->getDouble("factor", 0.1) : 0.1, -10.0, 1.0) : 0.1;
    KisPaintDeviceSP snapshot = new KisPaintDevice(device->colorSpace());
    snapshot->prepareClone(device);
    const auto defaultImage = fxmanager::readFloatImage(snapshot, QRect(0, 0, 1, 1));
    if (defaultImage.isNull()) return;
    KisPainter::copyAreaOptimizedOldData(read.topLeft(), device, snapshot, read);
    const QRect stored = snapshot->extent().intersected(read);
    fxmanager::FloatRgbaImage dense;
    if (!stored.isEmpty() && qint64(stored.width()) * stored.height() <= 4LL * 1024 * 1024) {
        dense = fxmanager::readFloatImage(snapshot, stored);
        if (dense.isNull()) return;
    }
    // Cached source tiles preserve global sampler coordinates and bound float memory.
    constexpr int side = 128;
    constexpr int maxCached = 256;
    using TileKey = QPair<int, int>;
    using TileList = std::list<TileKey>;
    struct CachedTile {
        fxmanager::FloatRgbaImage image;
        TileList::iterator age;
    };
    QHash<TileKey, CachedTile> cache;
    TileList ages;
    auto getPixel = [&](int x, int y) -> const float * {
        if (!stored.contains(x, y)) return defaultImage.pixels.constData();
        if (!dense.isNull()) return dense.pixels.constData() + ((y-stored.y())*stored.width()+x-stored.x())*4;
        const int tx = int(std::floor(double(x)/side))*side;
        const int ty = int(std::floor(double(y)/side))*side;
        const TileKey key(tx, ty);
        auto it = cache.find(key);
        if (it == cache.end()) {
            if (cache.size() >= maxCached) {
                cache.remove(ages.back());
                ages.pop_back();
            }
            auto image = fxmanager::readFloatImage(snapshot, QRect(tx, ty, side, side));
            if (image.isNull()) return nullptr;
            ages.push_front(key);
            it = cache.insert(key, CachedTile{std::move(image), ages.begin()});
        } else {
            ages.splice(ages.begin(), ages, it->age);
        }
        return it->image.pixels.constData() + ((y-ty)*side+x-tx)*4;
    };
    if(!std::isfinite(gx)||!std::isfinite(gy)||!std::isfinite(angle)||!std::isfinite(factor)) return;
    const int samples=(circular ? angle==0.0 : factor==0.0) ? 1 : 200;
    double cosine[200],sine[200];
    if(circular) for(int i=0;i<samples;++i){
        const double a=(samples==1?0.0:(-1.0+2.0*i/(samples-1)))*angle*kPi/360.0;
        cosine[i]=std::cos(a);sine[i]=std::sin(a);
    }
    constexpr int outputSide=256;
    for(int top=rect.top();top<=rect.bottom();top+=outputSide) for(int left=rect.left();left<=rect.right();left+=outputSide){
        const QRect tile(left,top,std::min(outputSide,rect.right()-left+1),std::min(outputSide,rect.bottom()-top+1));
        fxmanager::FloatRgbaImage out;out.width=tile.width();out.height=tile.height();out.linearHdr=true;out.pixels.resize(tile.width()*tile.height()*4);
        float *outputPixels=out.pixels.data();
        std::atomic<bool> failed{false};
        auto rows = [&](int y0,int y1) {
        for(int y=y0;y<y1;++y) for(int x=0;x<tile.width();++x){
            const double px=tile.x()+x,py=tile.y()+y;
            double rgba[4]={};
            double coverageWeight=0.0;
            const bool normalizeCanvasEdge=circular && frame.contains(int(px),int(py));
            for(int i=0;i<samples;++i){
                double sx=px,sy=py;
                if(circular && samples>1){double dx=px-gx,dy=py-gy;sx=gx+dx*cosine[i]-dy*sine[i];sy=gy+dx*sine[i]+dy*cosine[i];}
                else if(!circular){double scale=1.0-double(i)/samples*factor;sx=gx+(px-gx)*scale;sy=gy+(py-gy)*scale;}
                const int ix=int(std::floor(sx)),iy=int(std::floor(sy));
                const double tx=sx-ix,ty=sy-iy;
                // Most taps lie wholly inside the converted source. Resolve
                // the four neighbors once instead of entering the tile/cache
                // lookup and rectangle checks for every channel contribution.
                if(!dense.isNull() && stored.contains(ix,iy) && stored.contains(ix+1,iy+1)
                    && read.contains(ix,iy) && read.contains(ix+1,iy+1)
                    && (!normalizeCanvasEdge || (frame.contains(ix,iy) && frame.contains(ix+1,iy+1)))) {
                    const float *row=dense.pixels.constData()+((iy-stored.y())*stored.width()+ix-stored.x())*4;
                    const float *neighbors[4]={row,row+4,row+stored.width()*4,row+stored.width()*4+4};
                    for(int v=0;v<2;++v)for(int u=0;u<2;++u){
                        const float *pixel=neighbors[v*2+u];
                        const double weight=(u?tx:1.0-tx)*(v?ty:1.0-ty),alpha=pixel[3];
                        coverageWeight+=weight;
                        rgba[3]+=weight*alpha;
                        if(alpha!=0.0)for(int c=0;c<3;++c)rgba[c]+=weight*alpha*pixel[c];
                    }
                    continue;
                }
                for(int v=0;v<2;++v)for(int u=0;u<2;++u){
                    const int xx=ix+u,yy=iy+v;
                    if(!read.contains(xx,yy))continue;
                    // Outside the reference canvas is missing support, not a
                    // transparent sample. Transparency inside it remains real.
                    if(normalizeCanvasEdge && !frame.contains(xx,yy))continue;
                    const float *pixel=getPixel(xx,yy); if(!pixel){failed.store(true);return;}
                    const double weight=(u?tx:1.0-tx)*(v?ty:1.0-ty),alpha=pixel[3];
                    coverageWeight+=weight;
                    rgba[3]+=weight*alpha;
                    if(alpha!=0.0)for(int c=0;c<3;++c)rgba[c]+=weight*alpha*pixel[c];
                }
            }
            float *pixel=outputPixels+(y*tile.width()+x)*4;
            const double divisor=normalizeCanvasEdge ? coverageWeight : samples;
            if(normalizeCanvasEdge && divisor==0.0){
                // Very small canvases can fall between all angular samples.
                const float *original=getPixel(int(px),int(py)); if(!original){failed.store(true);return;}
                std::copy(original,original+4,pixel);
            }else{
                pixel[3]=divisor>0.0 ? float(rgba[3]/divisor) : 0.0f;
                for(int c=0;c<3;++c)pixel[c]=rgba[3]!=0.0?float(rgba[c]/rgba[3]):0.0f;
            }
        }
        };
        // Dense source is immutable; sparse LRU access remains serial.
        if(!dense.isNull()) fxmanager::parallelRows(tile.height(),rows);
        else rows(0,tile.height());
        if(failed.load())return;
        if(progressUpdater && progressUpdater->interrupted())return;
        fxmanager::writeFloatImage(device,out,tile);
    }
    if (progressUpdater) progressUpdater->setProgress(100);
}

FxmGeglMotionBlur::Widget::Widget(Variant variant, const QRect &deviceFrame, const KisPaintDeviceSP &device, QWidget *parent)
    : KisConfigWidget(parent)
    , m_variant(variant)
    , m_deviceFrame(deviceFrame)
    , m_frame(isSaneFrame(deviceFrame) ? deviceFrame : DefaultReferenceFrame())
    , m_frameInitialized(false)
{
    auto *root = new QVBoxLayout(this);
    m_pointPreview = new FxmBlurPointPreview(this);
    m_pointPreview->setSource(device, m_frame);
    m_pointPreview->setReferenceFrame(m_frame);
    root->addWidget(m_pointPreview);
    auto *form = new QFormLayout();

    m_centerXSpin = new QDoubleSpinBox(this);
    QHBoxLayout *cxRow = nullptr;
    m_centerXSlider = makeBoundSlider(this, m_centerXSpin, -1.0, 2.0, 0.005, 3, 0.5, &cxRow);
    form->addRow(i18n("Center X:"), cxRow);

    m_centerYSpin = new QDoubleSpinBox(this);
    QHBoxLayout *cyRow = nullptr;
    m_centerYSlider = makeBoundSlider(this, m_centerYSpin, -1.0, 2.0, 0.005, 3, 0.5, &cyRow);
    form->addRow(i18n("Center Y:"), cyRow);

    m_primarySpin = new QDoubleSpinBox(this);
    QHBoxLayout *primaryRow = nullptr;
    if (m_variant == Variant::Circular) {
        m_primarySlider = makeBoundSlider(this, m_primarySpin, 0.0, 360.0, 0.5, 2, 20.0, &primaryRow);
        form->addRow(i18n("Angle (deg):"), primaryRow);
    } else {
        m_primarySlider = makeBoundSlider(this, m_primarySpin, -10.0, 1.0, 0.005, 3, 0.1, &primaryRow);
        form->addRow(i18n("Blurring factor:"), primaryRow);
    }

    root->addLayout(form);

    m_statusLabel = new QLabel(i18n("Native CPU processing."), this);
    m_statusLabel->setWordWrap(true);
    root->addWidget(m_statusLabel);
    root->addStretch(1);

    auto notify = [this]() { emit sigConfigurationItemChanged(); };
    m_pointPreview->bind(m_centerXSpin,m_centerYSpin,notify);
    connect(m_centerXSpin, QOverload<double>::of(&QDoubleSpinBox::valueChanged), this, notify);
    connect(m_centerYSpin, QOverload<double>::of(&QDoubleSpinBox::valueChanged), this, notify);
    connect(m_primarySpin, QOverload<double>::of(&QDoubleSpinBox::valueChanged), this, notify);
}

void FxmGeglMotionBlur::Widget::setConfiguration(const KisPropertiesConfigurationSP config)
{
    if (!config) return;
    const QRect savedFrame(config->getInt("frame_x",0),config->getInt("frame_y",0),config->getInt("frame_width",0),config->getInt("frame_height",0));
    const bool initialized = config->getBool("frame_initialized", false) && isSaneFrame(savedFrame);
    m_frame = initialized ? savedFrame : (isSaneFrame(m_deviceFrame) ? m_deviceFrame : DefaultReferenceFrame());
    m_frameInitialized = initialized || isSaneFrame(m_deviceFrame);
    m_pointPreview->setReferenceFrame(m_frame);

    {
        const QSignalBlocker b1(m_centerXSpin), b2(m_centerYSpin), b3(m_primarySpin);
        const QSignalBlocker s1(m_centerXSlider), s2(m_centerYSlider), s3(m_primarySlider);

        const double cx = config->getDouble("center_x", 0.5);
        const double cy = config->getDouble("center_y", 0.5);
        m_pointPreview->setCenter(QPointF(cx,cy));
        m_centerXSpin->setValue(cx);
        m_centerXSlider->setValue(int(std::llround((cx - m_centerXSpin->minimum()) / m_centerXSpin->singleStep())));
        m_centerYSpin->setValue(cy);
        m_centerYSlider->setValue(int(std::llround((cy - m_centerYSpin->minimum()) / m_centerYSpin->singleStep())));

        if (m_variant == Variant::Circular) {
            const double angle = config->getDouble("angle", 20.0);
            m_primarySpin->setValue(angle);
            m_primarySlider->setValue(int(std::llround((angle - m_primarySpin->minimum()) / m_primarySpin->singleStep())));
        } else {
            const double factor = config->getDouble("factor", 0.1);
            m_primarySpin->setValue(factor);
            m_primarySlider->setValue(int(std::llround((factor - m_primarySpin->minimum()) / m_primarySpin->singleStep())));
        }
    }

}

KisPropertiesConfigurationSP FxmGeglMotionBlur::Widget::configuration() const
{
    KisFilterConfigurationSP c = new KisFilterConfiguration(
        m_variant == Variant::Circular ? circularId().id() : zoomId().id(),
        1,
        KisGlobalResourcesInterface::instance());
    c->setProperty("center_x", m_centerXSpin->value());
    c->setProperty("center_y", m_centerYSpin->value());
    if (m_variant == Variant::Circular) {
        c->setProperty("angle", m_primarySpin->value());
    } else {
        c->setProperty("factor", m_primarySpin->value());
    }
    const QRect activeFrame = isSaneFrame(m_frame) ? m_frame : DefaultReferenceFrame();
    c->setProperty("frame_x", activeFrame.x());
    c->setProperty("frame_y", activeFrame.y());
    c->setProperty("frame_width", activeFrame.width());
    c->setProperty("frame_height", activeFrame.height());
    c->setProperty("frame_initialized", m_frameInitialized);
    return c;
}
