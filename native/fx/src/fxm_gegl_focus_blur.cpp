#include "fxm_gegl_focus_blur.h"

#include "focus_native.h"
#include "fxmanager_processing.h"
#include "fxm_blur_point_preview.h"

#include <QCheckBox>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QSignalBlocker>
#include <QSlider>
#include <QVBoxLayout>

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
#include <stdexcept>
#include <mutex>
#include <exception>
#include <vector>

namespace {

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

QString sanitizeBlurType(const QString &s)
{
    return (s == QLatin1String("lens")) ? QStringLiteral("lens") : QStringLiteral("gaussian");
}

QString sanitizeShape(const QString &s)
{
    static const QStringList kAllowed = {
        QStringLiteral("circle"),
        QStringLiteral("square"),
        QStringLiteral("diamond"),
        QStringLiteral("horizontal"),
        QStringLiteral("vertical")
    };
    return kAllowed.contains(s) ? s : QStringLiteral("circle");
}

QSlider *makeSliderRow(QWidget *parent,
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

void syncSliderAndSpin(QDoubleSpinBox *spin, QSlider *slider, double value)
{
    const QSignalBlocker b1(spin);
    const QSignalBlocker b2(slider);
    spin->setValue(value);
    slider->setValue(int(std::llround((spin->value() - spin->minimum()) / spin->singleStep())));
}

} // namespace

FxmGeglFocusBlur::FxmGeglFocusBlur()
    : KisFilter(id(), FiltersCategoryBlurId, i18n("&Focus Blur..."))
{
    setSupportsPainting(false);
    setSupportsAdjustmentLayers(true);
    setSupportsThreading(false);
    setSupportsLevelOfDetail(false);
    setColorSpaceIndependence(FULLY_INDEPENDENT);
}

QRect FxmGeglFocusBlur::resolveReferenceFrame(const KisFilterConfigurationSP &config)
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

bool FxmGeglFocusBlur::configurationAllowedForMask(KisFilterConfigurationSP) const
{
    return true;
}

KisFilterConfigurationSP FxmGeglFocusBlur::defaultConfiguration(KisResourcesInterfaceSP resourcesInterface) const
{
    KisFilterConfigurationSP c = factoryConfiguration(resourcesInterface);

    const QRect defFrame = DefaultReferenceFrame();
    c->setProperty("frame_x", defFrame.x());
    c->setProperty("frame_y", defFrame.y());
    c->setProperty("frame_width", defFrame.width());
    c->setProperty("frame_height", defFrame.height());
    c->setProperty("frame_initialized", false);
    fxmanager::applyBuiltinDefaults(id().id(), c);
    fxmanager::applyFilterDefaults(id().id(), c);
    return c;
}

namespace {
focus_native::Rect nr(QRect r) { return {r.x(),r.y(),r.width(),r.height()}; }
QRect qr(focus_native::Rect r) { return {r.x,r.y,r.w,r.h}; }
focus_native::Params nativeParams(KisFilterConfigurationSP c) {
    focus_native::Params p;
    if (!c) return p;
    p.lens=c->getString("blur_type")=="lens";
    p.highlightFactor=c->getDouble("highlight_factor",0);
    p.highlightThresholdLow=c->getDouble("highlight_threshold_low",0);
    p.highlightThresholdHigh=c->getDouble("highlight_threshold_high",1);
    p.blurRadius=c->getDouble("blur_radius",25);
    p.x=c->getDouble("x",.5);p.y=c->getDouble("y",.5);
    p.radius=c->getDouble("radius",.75);p.focus=c->getDouble("focus",.25);
    p.midpoint=c->getDouble("midpoint",.5);p.aspectRatio=c->getDouble("aspect_ratio",0);
    p.rotation=c->getDouble("rotation",0);p.highQuality=c->getBool("high_quality",false);
    auto shape=c->getString("shape","circle");
    if(shape=="square")p.shape=focus_native::Shape::Square;
    if(shape=="diamond")p.shape=focus_native::Shape::Diamond;
    if(shape=="horizontal")p.shape=focus_native::Shape::Horizontal;
    if(shape=="vertical")p.shape=focus_native::Shape::Vertical;
    return focus_native::sanitize(p);
}
}
QRect FxmGeglFocusBlur::neededRect(const QRect &rect, const KisFilterConfigurationSP config, int) const
{
    if (rect.isEmpty()) return rect;
    const auto p = nativeParams(config);
    return p.blurRadius == 0 ? rect : qr(focus_native::neededRect(nr(rect), p));
}

QRect FxmGeglFocusBlur::changedRect(const QRect &rect, const KisFilterConfigurationSP config, int lod) const
{
    Q_UNUSED(lod);
    if (rect.isEmpty()) return rect;
    return qr(focus_native::changedRect(nr(rect), nativeParams(config)));
}

KisConfigWidget *FxmGeglFocusBlur::createConfigurationWidget(QWidget *parent, const KisPaintDeviceSP dev, bool) const
{
    return new Widget(extractDeviceFrame(dev), dev, parent);
}

void FxmGeglFocusBlur::processImpl(KisPaintDeviceSP device,
                                   const QRect &rect,
                                   const KisFilterConfigurationSP config,
                                   KoUpdater *progressUpdater) const
{
    if (!device || rect.isEmpty()) return;
    {
        try {
        auto params=nativeParams(config);
        // Radius zero is a native byte identity, including hidden RGB and profile.
        if(params.blurRadius==0)return;
        // Global canonical lattice: never align a core to the request origin.
        const int n=params.lens?64:256, H=focus_native::halo(params);
        const int x0=int(std::floor(double(rect.x())/n))*n;
        const int y0=int(std::floor(double(rect.y())/n))*n;
        // Freeze the complete callback dependency before the first output write.
        // Old data preserves an existing transaction's source; without a
        // transaction this captures the invocation's current source instead.
        // The paint-device copy remains sparse and retains the default pixel.
        if (progressUpdater && progressUpdater->interrupted()) return;
        const QRect sourceRect=neededRect(rect,config,0);
        KisPaintDeviceSP sourceSnapshot=new KisPaintDevice(device->colorSpace());
        sourceSnapshot->prepareClone(device);
        KisPainter::copyAreaOptimizedOldData(sourceRect.topLeft(),device,sourceSnapshot,sourceRect);
        // Stage native-format output, including reverse ICC conversion, for the
        // entire invocation. A later core failure must not publish earlier cores.
        KisPaintDeviceSP staged=new KisPaintDevice(device->colorSpace());
        staged->prepareClone(device);
        const qint64 totalCores=(qint64(rect.right())-x0+n)/n *
                                ((qint64(rect.bottom())-y0+n)/n);
        qint64 completedCores=0;
        struct CoreResult { QRect write; focus_native::Image image; };
        const int columns=int((qint64(rect.right())-x0+n)/n);
        const focus_native::Rect frame=nr(resolveReferenceFrame(config));
        const int firstY=y0;
        // Do not call Krita device APIs from workers. Read the frozen source
        // and build per-core immutable inputs on this thread, then render them
        // in small batches to bound memory and preserve cancellation staging.
        const int batchSize=4;
        for(qint64 base=0;base<totalCores;base+=batchSize) {
            if(progressUpdater && progressUpdater->interrupted())return;
            const int count=int(std::min<qint64>(batchSize,totalCores-base));
            std::vector<CoreResult> results(static_cast<size_t>(count));
            std::vector<focus_native::Image> inputs;
            inputs.reserve(count);
            for(int i=0;i<count;++i) {
                const qint64 index=base+i;
                const int cx=x0+int(index%columns)*n, cy=firstY+int(index/columns)*n;
                const QRect core(cx,cy,n,n),read=core.adjusted(-H,-H,H,H);
                auto input=fxmanager::readFloatImage(sourceSnapshot,read);
                if(input.isNull())throw std::runtime_error("ICC source conversion failed");
                inputs.emplace_back(nr(read));
                if(device->defaultBounds())inputs.back().canvasBounds=nr(device->defaultBounds()->bounds());
                for(size_t p=0;p<inputs.back().pixels.size();++p)
                    std::copy_n(input.pixels.constData()+4*p,4,inputs.back().pixels[p].data());
                results[size_t(i)].write=core.intersected(rect);
            }
            std::exception_ptr failure;
            std::mutex failureMutex;
            fxmanager::parallelRows(count,[&](int begin,int end) {
                for(int i=begin;i<end;++i) {
                    try {
                        const qint64 index=base+i;
                        const int cx=x0+int(index%columns)*n,cy=firstY+int(index/columns)*n;
                        results[size_t(i)].image=focus_native::render(inputs[size_t(i)],nr(QRect(cx,cy,n,n)),frame,params);
                    } catch (...) {
                        std::lock_guard<std::mutex> guard(failureMutex);
                        if(!failure)failure=std::current_exception();
                    }
                }
            });
            if(failure)std::rethrow_exception(failure);
            for(int i=0;i<count;++i) {
                const QRect write=results[size_t(i)].write;
                const auto &result=results[size_t(i)].image;
                fxmanager::FloatRgbaImage output;
                output.width=write.width();output.height=write.height();output.linearHdr=true;
                output.pixels.resize(write.width()*write.height()*4);
                for(int y=0;y<write.height();++y)for(int x=0;x<write.width();++x)
                    std::copy_n(result.get(write.x()+x,write.y()+y).data(),4,
                                output.pixels.data()+4*(y*write.width()+x));
                if(!fxmanager::writeFloatImage(staged,output,write))
                    throw std::runtime_error("ICC output conversion failed");
                results[size_t(i)].image=focus_native::Image();
                ++completedCores;
                if(progressUpdater)progressUpdater->setProgress(int(99*completedCores/totalCores));
            }
        }
        if (progressUpdater && progressUpdater->interrupted()) return;
        // This host copy is not an atomic swap and has no failure status or
        // strong exception guarantee. All core work completes before it starts.
        KisPainter::copyAreaOptimized(rect.topLeft(),staged,device,rect);
        if(progressUpdater)progressUpdater->setProgress(100);
        } catch (const std::exception &e) {
            warnKrita << "Focus Blur failed:" << e.what();
        } catch (...) {
            warnKrita << "Focus Blur failed with an unknown exception.";
        }
        return;
    }

}

FxmGeglFocusBlur::Widget::Widget(const QRect &deviceFrame, const KisPaintDeviceSP &device, QWidget *parent)
    : KisConfigWidget(parent)
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

    m_blurTypeCombo = new QComboBox(this);
    m_blurTypeCombo->addItem(i18n("Gaussian Blur"), QStringLiteral("gaussian"));
    m_blurTypeCombo->addItem(i18n("Lens Blur"), QStringLiteral("lens"));
    form->addRow(i18n("Blur type:"), m_blurTypeCombo);

    m_blurRadiusSpin = new QDoubleSpinBox(this);
    QHBoxLayout *brRow = nullptr;
    m_blurRadiusSlider = makeSliderRow(this, m_blurRadiusSpin, 0.0, 200.0, 0.5, 2, 25.0, &brRow);
    form->addRow(i18n("Out-of-focus blur radius:"), brRow);

    m_shapeCombo = new QComboBox(this);
    m_shapeCombo->addItem(i18n("Circle"), QStringLiteral("circle"));
    m_shapeCombo->addItem(i18n("Square"), QStringLiteral("square"));
    m_shapeCombo->addItem(i18n("Diamond"), QStringLiteral("diamond"));
    m_shapeCombo->addItem(i18n("Horizontal"), QStringLiteral("horizontal"));
    m_shapeCombo->addItem(i18n("Vertical"), QStringLiteral("vertical"));
    form->addRow(i18n("Shape:"), m_shapeCombo);

    m_xSpin = new QDoubleSpinBox(this);
    QHBoxLayout *xRow = nullptr;
    m_xSlider = makeSliderRow(this, m_xSpin, -1.0, 2.0, 0.005, 3, 0.5, &xRow);
    form->addRow(i18n("Center X:"), xRow);

    m_ySpin = new QDoubleSpinBox(this);
    QHBoxLayout *yRow = nullptr;
    m_ySlider = makeSliderRow(this, m_ySpin, -1.0, 2.0, 0.005, 3, 0.5, &yRow);
    form->addRow(i18n("Center Y:"), yRow);

    m_radiusSpin = new QDoubleSpinBox(this);
    QHBoxLayout *rRow = nullptr;
    m_radiusSlider = makeSliderRow(this, m_radiusSpin, 0.0, 3.0, 0.01, 3, 0.75, &rRow);
    form->addRow(i18n("Outer radius:"), rRow);

    m_focusSpin = new QDoubleSpinBox(this);
    QHBoxLayout *fRow = nullptr;
    m_focusSlider = makeSliderRow(this, m_focusSpin, 0.0, 1.0, 0.01, 2, 0.25, &fRow);
    form->addRow(i18n("Sharpness (focus):"), fRow);

    m_midpointSpin = new QDoubleSpinBox(this);
    QHBoxLayout *mRow = nullptr;
    m_midpointSlider = makeSliderRow(this, m_midpointSpin, 0.0, 1.0, 0.01, 2, 0.5, &mRow);
    form->addRow(i18n("Transition midpoint:"), mRow);

    m_aspectSpin = new QDoubleSpinBox(this);
    QHBoxLayout *aRow = nullptr;
    m_aspectSlider = makeSliderRow(this, m_aspectSpin, -1.0, 1.0, 0.01, 2, 0.0, &aRow);
    form->addRow(i18n("Aspect ratio:"), aRow);

    m_rotationSpin = new QDoubleSpinBox(this);
    QHBoxLayout *rotRow = nullptr;
    m_rotationSlider = makeSliderRow(this, m_rotationSpin, -180.0, 180.0, 0.5, 1, 0.0, &rotRow);
    form->addRow(i18n("Rotation (deg):"), rotRow);

    m_highQualityCheck = new QCheckBox(i18n("High quality (Gaussian mode)"), this);
    form->addRow(QString(), m_highQualityCheck);

    root->addLayout(form);

    m_lensGroup = new QWidget(this);
    auto *lensForm = new QFormLayout(m_lensGroup);
    lensForm->setContentsMargins(0, 0, 0, 0);

    m_highlightFactorSpin = new QDoubleSpinBox(m_lensGroup);
    QHBoxLayout *hfRow = nullptr;
    m_highlightFactorSlider = makeSliderRow(m_lensGroup, m_highlightFactorSpin, 0.0, 1.0, 0.01, 2, 0.0, &hfRow);
    lensForm->addRow(i18n("Highlight factor:"), hfRow);

    m_highlightLowSpin = new QDoubleSpinBox(m_lensGroup);
    QHBoxLayout *hlRow = nullptr;
    m_highlightLowSlider = makeSliderRow(m_lensGroup, m_highlightLowSpin, 0.0, 1.0, 0.01, 2, 0.0, &hlRow);
    lensForm->addRow(i18n("Highlight threshold (low):"), hlRow);

    m_highlightHighSpin = new QDoubleSpinBox(m_lensGroup);
    QHBoxLayout *hhRow = nullptr;
    m_highlightHighSlider = makeSliderRow(m_lensGroup, m_highlightHighSpin, 0.0, 1.0, 0.01, 2, 1.0, &hhRow);
    lensForm->addRow(i18n("Highlight threshold (high):"), hhRow);

    root->addWidget(m_lensGroup);

    root->addStretch(1);

    updateModeVisibility();

    auto notify = [this]() { emit sigConfigurationItemChanged(); };
    m_pointPreview->bind(m_xSpin,m_ySpin,notify);
    connect(m_blurTypeCombo, QOverload<int>::of(&QComboBox::currentIndexChanged), this, [this]() {
        updateModeVisibility();
        emit sigConfigurationItemChanged();
    });
    connect(m_shapeCombo, QOverload<int>::of(&QComboBox::currentIndexChanged), this, notify);
    for (QDoubleSpinBox *spin : {m_blurRadiusSpin, m_highlightFactorSpin, m_highlightLowSpin,
                                 m_highlightHighSpin, m_xSpin, m_ySpin, m_radiusSpin,
                                 m_focusSpin, m_midpointSpin, m_aspectSpin, m_rotationSpin}) {
        connect(spin, QOverload<double>::of(&QDoubleSpinBox::valueChanged), this, notify);
    }
    connect(m_highQualityCheck, &QCheckBox::toggled, this, notify);
}

void FxmGeglFocusBlur::Widget::updateModeVisibility()
{
    const bool isLens = (m_blurTypeCombo->currentData().toString() == QLatin1String("lens"));
    if (m_lensGroup) m_lensGroup->setVisible(isLens);
    if (m_highQualityCheck) m_highQualityCheck->setVisible(!isLens);
}

void FxmGeglFocusBlur::Widget::setConfiguration(const KisPropertiesConfigurationSP config)
{
    if (!config) return;
    const QRect savedFrame(config->getInt("frame_x",0),config->getInt("frame_y",0),config->getInt("frame_width",0),config->getInt("frame_height",0));
    const bool savedInitialized = config->getBool("frame_initialized", false) && isSaneFrame(savedFrame);
    m_frame = savedInitialized ? savedFrame
        : (isSaneFrame(m_deviceFrame) ? m_deviceFrame : FxmGeglFocusBlur::DefaultReferenceFrame());
    m_frameInitialized = savedInitialized || isSaneFrame(m_deviceFrame);
    m_pointPreview->setReferenceFrame(m_frame);
    m_pointPreview->setCenter(QPointF(config->getDouble("x",0.5),config->getDouble("y",0.5)));

    {
        const QSignalBlocker bType(m_blurTypeCombo), bShape(m_shapeCombo), bHq(m_highQualityCheck);

        const QString blurType = sanitizeBlurType(config->getString("blur_type", QStringLiteral("gaussian")));
        const int typeIdx = m_blurTypeCombo->findData(blurType);
        if (typeIdx >= 0) m_blurTypeCombo->setCurrentIndex(typeIdx);

        const QString shape = sanitizeShape(config->getString("shape", QStringLiteral("circle")));
        const int shapeIdx = m_shapeCombo->findData(shape);
        if (shapeIdx >= 0) m_shapeCombo->setCurrentIndex(shapeIdx);

        syncSliderAndSpin(m_blurRadiusSpin, m_blurRadiusSlider, config->getDouble("blur_radius", 25.0));
        syncSliderAndSpin(m_highlightFactorSpin, m_highlightFactorSlider, config->getDouble("highlight_factor", 0.0));
        syncSliderAndSpin(m_highlightLowSpin, m_highlightLowSlider, config->getDouble("highlight_threshold_low", 0.0));
        syncSliderAndSpin(m_highlightHighSpin, m_highlightHighSlider, config->getDouble("highlight_threshold_high", 1.0));
        syncSliderAndSpin(m_xSpin, m_xSlider, config->getDouble("x", 0.5));
        syncSliderAndSpin(m_ySpin, m_ySlider, config->getDouble("y", 0.5));
        syncSliderAndSpin(m_radiusSpin, m_radiusSlider, config->getDouble("radius", 0.75));
        syncSliderAndSpin(m_focusSpin, m_focusSlider, config->getDouble("focus", 0.25));
        syncSliderAndSpin(m_midpointSpin, m_midpointSlider, config->getDouble("midpoint", 0.5));
        syncSliderAndSpin(m_aspectSpin, m_aspectSlider, config->getDouble("aspect_ratio", 0.0));
        syncSliderAndSpin(m_rotationSpin, m_rotationSlider, config->getDouble("rotation", 0.0));
        m_highQualityCheck->setChecked(config->getBool("high_quality", false));
    }

    updateModeVisibility();
}

KisPropertiesConfigurationSP FxmGeglFocusBlur::Widget::configuration() const
{
    KisFilterConfigurationSP c = new KisFilterConfiguration(
        id().id(), 1, KisGlobalResourcesInterface::instance());
    c->setProperty("blur_type", m_blurTypeCombo->currentData().toString());
    c->setProperty("blur_radius", m_blurRadiusSpin->value());
    c->setProperty("highlight_factor", m_highlightFactorSpin->value());
    c->setProperty("highlight_threshold_low", m_highlightLowSpin->value());
    c->setProperty("highlight_threshold_high", m_highlightHighSpin->value());
    c->setProperty("shape", m_shapeCombo->currentData().toString());
    c->setProperty("x", m_xSpin->value());
    c->setProperty("y", m_ySpin->value());
    c->setProperty("radius", m_radiusSpin->value());
    c->setProperty("focus", m_focusSpin->value());
    c->setProperty("midpoint", m_midpointSpin->value());
    c->setProperty("aspect_ratio", m_aspectSpin->value());
    c->setProperty("rotation", m_rotationSpin->value());
    c->setProperty("high_quality", m_highQualityCheck->isChecked());
    const QRect activeFrame = isSaneFrame(m_frame) ? m_frame : DefaultReferenceFrame();
    c->setProperty("frame_x", activeFrame.x());
    c->setProperty("frame_y", activeFrame.y());
    c->setProperty("frame_width", activeFrame.width());
    c->setProperty("frame_height", activeFrame.height());
    c->setProperty("frame_initialized", m_frameInitialized);
    return c;
}
