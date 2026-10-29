#include "fxmanager_clipboard_color_match.h"
#include "fxmanager_clipboard_color_match_widget.h"
#include "fxmanager_drag_spinbox.h"
#include "fxmanager_processing.h"
#include "fxmanager_statistical_profile.h"

#include <algorithm>
#include <cmath>
#include <memory>
#include <vector>

#include <QBuffer>
#include <QCheckBox>
#include <QClipboard>

#include <QGroupBox>
#include <QDoubleSpinBox>
#include <QFileDialog>
#include <QFormLayout>
#include <QFrame>
#include <QGuiApplication>
#include <QHBoxLayout>
#include <QLabel>
#include <QMimeData>

#include <QPushButton>
#include <QComboBox>
#include <QSignalBlocker>
#include <QSlider>
#include <QCryptographicHash>
#include <QVBoxLayout>

#include <KisGlobalResourcesInterface.h>
#include <KisMainWindow.h>
#include <KisPart.h>
#include <KisReferenceImage.h>
#include <KisView.h>
#include <KoColorSpaceRegistry.h>
#include <KoColorProfile.h>
#include <KoSelection.h>
#include <KoSelectedShapesProxy.h>
#include <kis_canvas2.h>
#include <KoUpdater.h>
#include <filter/kis_filter_category_ids.h>
#include <filter/kis_filter_configuration.h>
#include <kis_default_bounds_base.h>
#include <kis_iterator_ng.h>
#include <kis_paint_device.h>
#include <klocalizedstring.h>

namespace {

constexpr double kEpsilon = 1e-6;

double parameterDefault(const QString &key, int version)
{
    if (key == QLatin1String("fade")) return 0;
    if (key == QLatin1String("tone_distribution")) return version == 2 ? 0.65 : 0;
    if (key == QLatin1String("tonal_color")) return version == 2 ? 0.75 : 0;
    if (key == QLatin1String("color_correlation")) return version == 2 ? 1 : 0;
    if (key == QLatin1String("gain_limit")) return 2;
    if (key == QLatin1String("shift_limit")) return 51;
    if (key == QLatin1String("variance_floor")) return 2.55;
    return 1;
}

struct Stats {
    double meanL = 0.0;
    double meanA = 0.0;
    double meanB = 0.0;
    double stdL = 0.0;
    double stdA = 0.0;
    double stdB = 0.0;
    int count = 0;
};

bool statsForDevice(const KisPaintDeviceSP &device, const QRect &rect, Stats *out,
                    fxmanager::statistical::Profile *distribution = nullptr)
{
    if (!device || !out || rect.isEmpty()) return false;
    const KoColorSpace *lab = KoColorSpaceRegistry::instance()->lab16();
    if (!lab) return false;

    KisPaintDeviceSP labDevice = new KisPaintDevice(*device.data());
    labDevice->convertTo(lab,
                         KoColorConversionTransformation::internalRenderingIntent(),
                         KoColorConversionTransformation::internalConversionFlags());

    double sumL = 0.0;
    double sumA = 0.0;
    double sumB = 0.0;
    double sumL2 = 0.0;
    double sumA2 = 0.0;
    double sumB2 = 0.0;
    int count = 0;
    fxmanager::statistical::Accumulator enhanced;
    KisSequentialConstIterator it(labDevice, rect);
    while (it.nextPixel()) {
        const quint16 *data = reinterpret_cast<const quint16 *>(it.oldRawData());
        const double l = data[0];
        const double a = data[1];
        const double b = data[2];
        if (distribution) enhanced.add({l/65535.0, (a-32896.0)/65535.0,
                                        (b-32896.0)/65535.0, data[3]/65535.0});
        sumL += l;
        sumA += a;
        sumB += b;
        sumL2 += l * l;
        sumA2 += a * a;
        sumB2 += b * b;
        ++count;
    }
    if (count == 0) return false;

    const double inv = 1.0 / count;
    out->meanL = sumL * inv;
    out->meanA = sumA * inv;
    out->meanB = sumB * inv;
    out->stdL = std::sqrt(std::max(0.0, sumL2 * inv - out->meanL * out->meanL));
    out->stdA = std::sqrt(std::max(0.0, sumA2 * inv - out->meanA * out->meanA));
    out->stdB = std::sqrt(std::max(0.0, sumB2 * inv - out->meanB * out->meanB));
    out->count = count;
    if (distribution) *distribution = enhanced.finish();
    return true;
}

double matchChannel(double value, double sourceMean, double sourceStd,
                    double referenceMean, double referenceStd, double amount)
{
    if (sourceStd < kEpsilon || referenceStd < kEpsilon) return value;
    const double matched = (value - sourceMean) * (referenceStd / sourceStd) + referenceMean;
    return value + (matched - value) * amount;
}

double value(const KisFilterConfigurationSP &config, const char *key, double fallback)
{
    return config ? config->getDouble(key, fallback) : fallback;
}

} // namespace

KisFilterClipboardColorMatch::KisFilterClipboardColorMatch()
    : KisFilter(id(), FiltersCategoryColorId, i18n("&Statistical Color Match..."))
{
    setColorSpaceIndependence(FULLY_INDEPENDENT);
    setSupportsThreading(false);
    setSupportsAdjustmentLayers(true);
}

KisFilterConfigurationSP KisFilterClipboardColorMatch::defaultConfiguration(KisResourcesInterfaceSP resourcesInterface) const
{
    auto config = factoryConfiguration(resourcesInterface);
    config->setProperty("statistical_version", 4);
    for (const char *key : {"tone_distribution", "tonal_color", "color_correlation", "gain_limit", "shift_limit", "variance_floor"})
        config->setProperty(key, parameterDefault(QString::fromLatin1(key), 3));
    config->setProperty("gamut_protection", false);
    config->setProperty("reference_distribution", QByteArray());
    config->setProperty("source_distribution", QByteArray());
    config->setProperty("reference_valid", false);
    config->setProperty("reference_mean_l", 0.0);
    config->setProperty("reference_mean_a", 0.0);
    config->setProperty("reference_mean_b", 0.0);
    config->setProperty("reference_std_l", 0.0);
    config->setProperty("reference_std_a", 0.0);
    config->setProperty("reference_std_b", 0.0);
    config->setProperty("reference_width", 0);
    config->setProperty("reference_height", 0);
    config->setProperty("reference_hash", QString());
    config->setProperty("reference_preview", QByteArray());
    config->setProperty("match_strength", 1.0);
    config->setProperty("luminance", 1.0);
    config->setProperty("color_intensity", 1.0);
    config->setProperty("fade", 0.0);
    config->setProperty("preserve_alpha", true);
    config->setProperty("reference_source", QStringLiteral("clipboard"));
    config->setProperty("reference_path", QString());
    config->setProperty("source_stats_valid", false);
    config->setProperty("source_mean_l", 0.0);
    config->setProperty("source_mean_a", 0.0);
    config->setProperty("source_mean_b", 0.0);
    config->setProperty("source_std_l", 0.0);
    config->setProperty("source_std_a", 0.0);
    config->setProperty("source_std_b", 0.0);
    fxmanager::applyFilterDefaults(id().id(), config); return config;
}

KisConfigWidget *KisFilterClipboardColorMatch::createConfigurationWidget(QWidget *parent,
                                                                         const KisPaintDeviceSP device,
                                                                         bool) const
{
    return new ClipboardColorMatchConfigurationWidget(id().id(), device, parent);
}

void KisFilterClipboardColorMatch::processImpl(KisPaintDeviceSP device,
                                               const QRect &applyRect,
                                               const KisFilterConfigurationSP config,
                                               KoUpdater *progressUpdater) const
{
    if (!device || applyRect.isEmpty() || !config || !config->getBool("reference_valid", false)) return;

    const KoColorSpace *lab = KoColorSpaceRegistry::instance()->lab16();
    if (!lab) return;

    if (config->getInt("statistical_version", 1) >= 2) {
        namespace st = fxmanager::statistical;
        const auto sourceProfile = st::decodeProfile(config->getProperty("source_distribution").toByteArray());
        const auto referenceProfile = st::decodeProfile(config->getProperty("reference_distribution").toByteArray());
        const double strength = std::clamp(value(config, "match_strength", 1.0), 0.0, 1.0);
        const double fade = std::clamp(value(config, "fade", 0.0), 0.0, 1.0);
        const double luminance = std::clamp(value(config, "luminance", 1.0), 0.0, 2.0);
        const double colour = std::clamp(value(config, "color_intensity", 1.0), 0.0, 2.0);
        if (!sourceProfile.valid || !referenceProfile.valid || strength <= 0 || fade >= 1
            || (luminance <= 0 && colour <= 0)) return;
        st::TransferOptions options;
        const int version = config->getInt("statistical_version", 1);
        options.toneAmount = value(config, "tone_distribution", parameterDefault(QStringLiteral("tone_distribution"), version));
        options.bandAmount = value(config, "tonal_color", parameterDefault(QStringLiteral("tonal_color"), version));
        options.correlation = value(config, "color_correlation", parameterDefault(QStringLiteral("color_correlation"), version));
        options.maxGain = value(config, "gain_limit", 2);
        options.maxShift = value(config, "shift_limit", 51)/255;
        const double floor = value(config, "variance_floor", 2.55)/255;
        options.varianceFloor = floor*floor;
        options.composite = version >= 4;
        const st::Transfer transfer(sourceProfile, referenceProfile, options);
        KisPaintDeviceSP sourceLab = new KisPaintDevice(device->colorSpace());
        sourceLab->makeCloneFrom(device, applyRect);
        sourceLab->convertTo(lab, KoColorConversionTransformation::internalRenderingIntent(),
                             KoColorConversionTransformation::internalConversionFlags());
        const KoColorSpace *targetSpace = device->colorSpace();
        const bool protectSrgb = config->getBool("gamut_protection", version == 2) && targetSpace->profile()
            && targetSpace->profile()->name().contains(QStringLiteral("srgb"), Qt::CaseInsensitive);
        KisSequentialConstIterator sourceIt(sourceLab, applyRect);
        KisSequentialIterator targetIt(device, applyRect);
        while (sourceIt.nextPixel() && targetIt.nextPixel()) {
            const quint16 *src = reinterpret_cast<const quint16 *>(sourceIt.oldRawData());
            if (!src[3]) continue;
            const st::Pixel input{src[0]/65535.0, (src[1]-32896.0)/65535.0,
                                  (src[2]-32896.0)/65535.0, src[3]/65535.0};
            auto result = transfer.apply(input, strength, luminance, colour, fade);
            // Do not change a/b when the user explicitly disables colour.
            if (protectSrgb && colour > 0) result = st::compressSrgbGamut(result);
            quint16 pixel[4] = {
                quint16(std::clamp(qRound(result.l*65535),0,65535)),
                quint16(std::clamp(qRound(result.a*65535+32896),0,65535)),
                quint16(std::clamp(qRound(result.b*65535+32896),0,65535)), src[3]};
            const qreal alpha = targetSpace->opacityF(targetIt.oldRawData());
            targetSpace->fromLabA16(reinterpret_cast<const quint8 *>(pixel), targetIt.rawData(), 1);
            targetSpace->setOpacity(targetIt.rawData(), alpha, 1);
        }
        if (progressUpdater) progressUpdater->setProgress(100);
        return;
    }

    const bool hasGlobalStats = config->getBool("source_stats_valid", false);
    Stats source;
    if (!hasGlobalStats) return;
    source.meanL = value(config, "source_mean_l", 0.0);
    source.meanA = value(config, "source_mean_a", 0.0);
    source.meanB = value(config, "source_mean_b", 0.0);
    source.stdL = value(config, "source_std_l", 0.0);
    source.stdA = value(config, "source_std_a", 0.0);
    source.stdB = value(config, "source_std_b", 0.0);

    const double strength = std::clamp(value(config, "match_strength", 1.0), 0.0, 1.0);
    const double luminance = std::clamp(value(config, "luminance", 1.0), 0.0, 2.0);
    const double colorIntensity = std::clamp(value(config, "color_intensity", 1.0), 0.0, 2.0);
    const double fade = std::clamp(value(config, "fade", 0.0), 0.0, 1.0);
    const double totalStrength = strength * (1.0 - fade);
    const double lAmount = totalStrength * luminance;
    const double abAmount = totalStrength * colorIntensity;
    const double refMeanL = value(config, "reference_mean_l", source.meanL);
    const double refMeanA = value(config, "reference_mean_a", source.meanA);
    const double refMeanB = value(config, "reference_mean_b", source.meanB);
    const double refStdL = value(config, "reference_std_l", source.stdL);
    const double refStdA = value(config, "reference_std_a", source.stdA);
    const double refStdB = value(config, "reference_std_b", source.stdB);

    KisPaintDeviceSP sourceLab = new KisPaintDevice(device->colorSpace());
    sourceLab->makeCloneFrom(device, applyRect);
    sourceLab->convertTo(lab,
                         KoColorConversionTransformation::internalRenderingIntent(),
                         KoColorConversionTransformation::internalConversionFlags());
    const KoColorSpace *targetSpace = device->colorSpace();
    KisSequentialConstIterator sourceIt(sourceLab, applyRect);
    KisSequentialIterator targetIt(device, applyRect);
    quint16 labPixel[4] = {0, 0, 0, 0};
    while (sourceIt.nextPixel() && targetIt.nextPixel()) {
        const quint16 *src = reinterpret_cast<const quint16 *>(sourceIt.oldRawData());
        labPixel[0] = static_cast<quint16>(std::clamp(matchChannel(src[0], source.meanL, source.stdL, refMeanL, refStdL, lAmount), 0.0, 65535.0));
        labPixel[1] = static_cast<quint16>(std::clamp(matchChannel(src[1], source.meanA, source.stdA, refMeanA, refStdA, abAmount), 0.0, 65535.0));
        labPixel[2] = static_cast<quint16>(std::clamp(matchChannel(src[2], source.meanB, source.stdB, refMeanB, refStdB, abAmount), 0.0, 65535.0));
        labPixel[3] = src[3];
        targetSpace->fromLabA16(reinterpret_cast<const quint8 *>(labPixel), targetIt.rawData(), 1);
    }
    if (progressUpdater) progressUpdater->setProgress(100);
}

ClipboardColorMatchConfigurationWidget::ClipboardColorMatchConfigurationWidget(const QString &id,
                                                                                 const KisPaintDeviceSP &device,
                                                                                 QWidget *parent)
    : KisConfigWidget(parent)
    , m_id(id)
    , m_device(device)
{
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(10);

    auto *referenceGroup = new QGroupBox(i18n("Reference"), this);
    referenceGroup->setObjectName(QStringLiteral("reference"));
    auto *referenceLayout = new QVBoxLayout(referenceGroup);
    referenceLayout->setContentsMargins(8, 8, 8, 8);
    referenceLayout->setSpacing(8);

    auto *referenceRow = new QHBoxLayout;
    referenceRow->setSpacing(8);
    m_preview = new QLabel(this);
    m_preview->setObjectName(QStringLiteral("reference_preview"));
    m_preview->setFixedSize(144, 82);
    m_preview->setAlignment(Qt::AlignCenter);
    m_preview->setStyleSheet(QStringLiteral("QLabel { background: #202020; border: 1px solid #4a4a4a; color: #9a9a9a; padding: 0px; }") );
    m_preview->setText(i18n("Empty"));
    referenceRow->addWidget(m_preview, 0, Qt::AlignCenter);
    referenceLayout->addLayout(referenceRow);

    auto *sourceRow = new QHBoxLayout;
    sourceRow->setSpacing(6);
    auto *sourceLabel = new QLabel(i18n("Source"), this);
    sourceLabel->setObjectName(QStringLiteral("reference_source_label"));
    sourceLabel->setMinimumWidth(48);
    sourceRow->addWidget(sourceLabel);
    m_source = new QComboBox(this);
    m_source->setObjectName(QStringLiteral("reference_source"));
    m_source->addItem(i18n("Clipboard"), QStringLiteral("clipboard"));
    m_source->addItem(i18n("File"), QStringLiteral("file"));
    sourceRow->addWidget(m_source, 1);
    referenceLayout->addLayout(sourceRow);
    connect(m_source, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, [this] {
                updateSourceUi();
                emit sigConfigurationItemChanged();
            });

    auto *referenceActions = new QHBoxLayout;
    referenceActions->setSpacing(6);
    m_refresh = new QPushButton(i18n("Paste from Clipboard"), this);
    m_refresh->setObjectName(QStringLiteral("refresh_clipboard"));
    referenceActions->addWidget(m_refresh, 1);
    connect(m_refresh, &QPushButton::clicked, this, &ClipboardColorMatchConfigurationWidget::refreshClipboard);
    m_browse = new QPushButton(i18n("Load Image…"), this);
    m_browse->setObjectName(QStringLiteral("browse_reference"));
    referenceActions->addWidget(m_browse, 1);
    connect(m_browse, &QPushButton::clicked, this, &ClipboardColorMatchConfigurationWidget::browseFile);
    referenceLayout->addLayout(referenceActions);
    addRegionControls(referenceLayout, QStringLiteral("reference"), i18n("Reference Analysis Region"));
    auto *analyze = new QPushButton(i18n("Analyze Reference"), referenceGroup);
    analyze->setObjectName(QStringLiteral("analyze_reference"));
    referenceLayout->addWidget(analyze);
    m_status = new QLabel(this);
    m_status->setWordWrap(true);
    referenceLayout->addWidget(m_status);
    connect(analyze, &QPushButton::clicked, this, &ClipboardColorMatchConfigurationWidget::analyzeReference);
    root->addWidget(referenceGroup);

    auto *targetGroup = new QGroupBox(i18n("Target Analysis"), this);
    targetGroup->setObjectName(QStringLiteral("target_analysis"));
    auto *targetLayout = new QVBoxLayout(targetGroup);
    targetLayout->setContentsMargins(8, 8, 8, 8);
    targetLayout->setSpacing(8);
    addRegionControls(targetLayout, QStringLiteral("target"), i18n("Target Analysis Region"));
    auto *reanalyze = new QPushButton(i18n("Re-analyze Target"), targetGroup);
    reanalyze->setObjectName(QStringLiteral("reanalyze_target"));
    targetLayout->addWidget(reanalyze);
    connect(reanalyze, &QPushButton::clicked, this, &ClipboardColorMatchConfigurationWidget::reanalyzeTarget);
    root->addWidget(targetGroup);

    auto *matchGroup = new QGroupBox(i18n("Overall Match"), this);
    matchGroup->setObjectName(QStringLiteral("overall_match"));
    auto *form = new QFormLayout(matchGroup);
    form->setContentsMargins(8, 8, 8, 8);
    form->setFieldGrowthPolicy(QFormLayout::AllNonFixedFieldsGrow);
    addPercentControl(form, QStringLiteral("match_strength"), i18n("Match Strength"), 1.0);

    addPercentControl(form, QStringLiteral("luminance"), i18n("Luminance"), 1.0);
    m_boxes[QStringLiteral("luminance")]->setRange(0.0, 2.0);
    static_cast<FxManagerDragSpinBox *>(m_boxes[QStringLiteral("luminance")])->refreshValueBar();
    addPercentControl(form, QStringLiteral("color_intensity"), i18n("Color Intensity"), 1.0);
    m_boxes[QStringLiteral("color_intensity")]->setRange(0.0, 2.0);
    static_cast<FxManagerDragSpinBox *>(m_boxes[QStringLiteral("color_intensity")])->refreshValueBar();
    addPercentControl(form, QStringLiteral("fade"), i18n("Fade"), 0.0);

    m_preserveAlpha = new QCheckBox(i18n("Preserve Alpha (always on)"), this);
    m_preserveAlpha->setObjectName(QStringLiteral("preserve_alpha"));
    m_preserveAlpha->setChecked(true);
    m_preserveAlpha->setEnabled(false);
    form->addRow(m_preserveAlpha);
    root->addWidget(matchGroup);

    {
        m_advanced = new QGroupBox(i18n("Tone Distribution"), this);
        m_advanced->setObjectName(QStringLiteral("tone_distribution_group"));
        auto *toneForm = new QFormLayout(m_advanced);
        toneForm->setContentsMargins(8, 8, 8, 8);
        toneForm->setFieldGrowthPolicy(QFormLayout::AllNonFixedFieldsGrow);
        addSliderControl(toneForm, QStringLiteral("tone_distribution"), i18n("Tone Distribution"), 0);
        m_boxes[QStringLiteral("tone_distribution")]->setToolTip(i18n("0 keeps original lightness. Increase to match the reference distribution; Luminance scales this adjustment."));
        root->addWidget(m_advanced);

        auto *colorGroup = new QGroupBox(i18n("Color Matching"), this);
        colorGroup->setObjectName(QStringLiteral("color_matching_group"));
        auto *colorForm = new QFormLayout(colorGroup);
        colorForm->setContentsMargins(8, 8, 8, 8);
        colorForm->setFieldGrowthPolicy(QFormLayout::AllNonFixedFieldsGrow);
        addSliderControl(colorForm, QStringLiteral("tonal_color"), i18n("Tonal Color"), 0);
        m_boxes[QStringLiteral("tonal_color")]->setToolTip(i18n("0 uses one global color match; 1 matches shadows, midtones and highlights separately."));
        addSliderControl(colorForm, QStringLiteral("color_correlation"), i18n("Color Correlation"), 0);
        m_boxes[QStringLiteral("color_correlation")]->setToolTip(i18n("0 scales Lab a/b independently; 1 also matches their correlation."));
        root->addWidget(colorGroup);

        auto *protectionGroup = new QGroupBox(i18n("Protection Limits"), this);
        protectionGroup->setObjectName(QStringLiteral("protection_limits_group"));
        protectionGroup->setCheckable(true);
        protectionGroup->setChecked(false);
        auto *protectionContents = new QWidget(protectionGroup);
        protectionContents->setObjectName(QStringLiteral("protection_limits_contents"));
        auto *protectionForm = new QFormLayout(protectionContents);
        protectionForm->setContentsMargins(8, 4, 8, 8);
        protectionForm->setFieldGrowthPolicy(QFormLayout::AllNonFixedFieldsGrow);
        addPercentControl(protectionForm, QStringLiteral("gain_limit"), i18n("Gain Limit"), 2);
        m_boxes[QStringLiteral("gain_limit")]->setRange(1, 8);
        m_boxes[QStringLiteral("gain_limit")]->setSingleStep(0.1);
        m_boxes[QStringLiteral("gain_limit")]->setValue(2);
        addPercentControl(protectionForm, QStringLiteral("shift_limit"), i18n("Color Shift Limit"), 0);
        m_boxes[QStringLiteral("shift_limit")]->setRange(0, 100);
        m_boxes[QStringLiteral("shift_limit")]->setValue(51);
        m_boxes[QStringLiteral("shift_limit")]->setToolTip(i18n("Maximum color displacement in Lab a/b units. 0 disables color transfer."));
        addPercentControl(protectionForm, QStringLiteral("variance_floor"), i18n("Variance Floor"), 0);
        m_boxes[QStringLiteral("variance_floor")]->setRange(0.1, 10);
        m_boxes[QStringLiteral("variance_floor")]->setValue(2.55);
        m_boxes[QStringLiteral("variance_floor")]->setToolTip(i18n("Minimum Lab channel spread used when matching near-neutral or flat areas. Higher values reduce amplification."));
        for (const char *key : {"gain_limit", "shift_limit", "variance_floor"})
            static_cast<FxManagerDragSpinBox *>(m_boxes[QString::fromLatin1(key)])->refreshValueBar();
        m_gamutProtection = new QCheckBox(i18n("sRGB Gamut Protection"), protectionContents);
        m_gamutProtection->setObjectName(QStringLiteral("gamut_protection"));
        protectionForm->addRow(m_gamutProtection);
        connect(m_gamutProtection, &QCheckBox::toggled, this, &KisConfigWidget::sigConfigurationItemChanged);
        auto *protectionLayout = new QVBoxLayout(protectionGroup);
        protectionLayout->setContentsMargins(0, 0, 0, 0);
        protectionLayout->addWidget(protectionContents);
        connect(protectionGroup, &QGroupBox::toggled, protectionContents, &QWidget::setVisible);
        protectionContents->setVisible(false);
        root->addWidget(protectionGroup);
    }
    root->addStretch(1);
    updateSourceUi();
}

ClipboardColorMatchConfigurationWidget::~ClipboardColorMatchConfigurationWidget() = default;

void ClipboardColorMatchConfigurationWidget::addPercentControl(QFormLayout *layout,
                                                                const QString &key,
                                                                const QString &label,
                                                                double value)
{
    auto *box = new FxManagerDragSpinBox(this);
    box->setObjectName(key);
    box->setRange(0.0, 1.0);
    box->setSingleStep(0.01);
    box->setDecimals(2);
    box->setValue(value);
    m_boxes.insert(key, box);
    layout->addRow(label, box);
    connect(box, QOverload<double>::of(&QDoubleSpinBox::valueChanged),
            this, &KisConfigWidget::sigConfigurationItemChanged);
}

void ClipboardColorMatchConfigurationWidget::addSliderControl(QFormLayout *layout,
                                                               const QString &key,
                                                               const QString &label,
                                                               double value)
{
    auto *row = new QWidget(this);
    auto *rowLayout = new QHBoxLayout(row);
    rowLayout->setContentsMargins(0, 0, 0, 0);
    auto *slider = new QSlider(Qt::Horizontal, row);
    slider->setObjectName(key + QStringLiteral("_slider"));
    slider->setRange(0, 100);
    slider->setValue(qRound(value*100));
    auto *box = new QDoubleSpinBox(row);
    box->setObjectName(key);
    box->setRange(0, 1);
    box->setDecimals(2);
    box->setSingleStep(0.01);
    box->setFixedWidth(74);
    box->setValue(value);
    m_boxes.insert(key, box);
    m_sliders.insert(key, slider);
    rowLayout->addWidget(slider, 1);
    rowLayout->addWidget(box);
    layout->addRow(label, row);
    connect(slider, &QSlider::valueChanged, box, [box](int v) { box->setValue(v/100.0); });
    connect(box, QOverload<double>::of(&QDoubleSpinBox::valueChanged), this, [this, slider](double v) {
        const QSignalBlocker blocker(slider);
        slider->setValue(qRound(v*100));
        emit sigConfigurationItemChanged();
    });
}

void ClipboardColorMatchConfigurationWidget::addRegionControls(QVBoxLayout *layout,
                                                               const QString &prefix,
                                                               const QString &title)
{
    auto *group = new QGroupBox(title, this);
    group->setObjectName(prefix + QStringLiteral("_region"));
    auto *form = new QFormLayout(group);
    form->setContentsMargins(8, 8, 8, 8);
    form->setSpacing(6);
    auto *enabled = new QCheckBox(i18n("Use Region"), group);
    enabled->setObjectName(prefix + QStringLiteral("_region_enabled"));
    enabled->setToolTip(i18n("Unchecked samples the whole input. Region edits take effect only when you explicitly analyze this input."));
    m_regionEnabled.insert(prefix, enabled);
    form->addRow(enabled);
    const QStringList labels = {i18n("X"), i18n("Y"), i18n("Width"), i18n("Height")};
    const QStringList fields = {QStringLiteral("x"), QStringLiteral("y"), QStringLiteral("w"), QStringLiteral("h")};
    for (int i = 0; i < fields.size(); ++i) {
        const QString key = prefix + QStringLiteral("_region_") + fields[i];
        auto *box = new QDoubleSpinBox(group);
        box->setObjectName(key);
        box->setDecimals(2);
        box->setRange(i < 2 ? 0.0 : 0.01, i < 2 ? 99.99 : 100.0);
        box->setSingleStep(1.0);
        box->setSuffix(QStringLiteral(" %"));
        box->setValue(i < 2 ? 0.0 : 100.0);
        m_regionBoxes.insert(key, box);
        form->addRow(labels[i], box);
        connect(box, QOverload<double>::of(&QDoubleSpinBox::valueChanged), this, [this, prefix] {
            updateRegionControls(prefix);
            emit sigConfigurationItemChanged();
        });
    }
    connect(enabled, &QCheckBox::toggled, this, [this, prefix] {
        updateRegionControls(prefix);
        emit sigConfigurationItemChanged();
    });
    updateRegionControls(prefix);
    layout->addWidget(group);
}

void ClipboardColorMatchConfigurationWidget::updateRegionControls(const QString &prefix)
{
    const QString base = prefix + QStringLiteral("_region_");
    auto *w = m_regionBoxes.value(base + QStringLiteral("w"));
    auto *h = m_regionBoxes.value(base + QStringLiteral("h"));
    const QSignalBlocker bw(w), bh(h);
    w->setMaximum(100.0 - m_regionBoxes.value(base + QStringLiteral("x"))->value());
    h->setMaximum(100.0 - m_regionBoxes.value(base + QStringLiteral("y"))->value());
    for (const char *field : {"x", "y", "w", "h"})
        m_regionBoxes.value(base + QString::fromLatin1(field))->setEnabled(m_regionEnabled.value(prefix)->isChecked());
}

QRect ClipboardColorMatchConfigurationWidget::analysisRect(const QRect &bounds, const QString &prefix) const
{
    if (bounds.isEmpty() || !m_regionEnabled.value(prefix)->isChecked()) return bounds;
    const QString base = prefix + QStringLiteral("_region_");
    const auto v = [this, &base](const char *field) { return m_regionBoxes.value(base + QString::fromLatin1(field))->value() / 100.0; };
    // Half-open pixel edges: include every pixel touched by the percentage rectangle.
    const int x = std::clamp(int(std::floor(bounds.width() * v("x"))), 0, bounds.width()-1);
    const int y = std::clamp(int(std::floor(bounds.height() * v("y"))), 0, bounds.height()-1);
    const int right = std::clamp(int(std::ceil(bounds.width() * (v("x")+v("w")))), x+1, bounds.width());
    const int bottom = std::clamp(int(std::ceil(bounds.height() * (v("y")+v("h")))), y+1, bounds.height());
    return QRect(bounds.x()+x, bounds.y()+y, right-x, bottom-y).intersected(bounds);
}

void ClipboardColorMatchConfigurationWidget::analyzeReference()
{
    LabStats stats;
    if (!calculateStats(m_referenceImage, &stats)) {
        m_status->setText(i18n("Select the reference image again before analyzing it."));
        return;
    }
    m_stats = stats;
    updateReferenceUi();
    emit sigConfigurationItemChanged();
}

void ClipboardColorMatchConfigurationWidget::reanalyzeTarget()
{
    LabStats stats;
    if (!calculateDeviceStats(&stats)) return;
    m_sourceStats = stats;
    emit sigConfigurationItemChanged();
}

bool ClipboardColorMatchConfigurationWidget::calculateStats(const QImage &input, LabStats *stats) const
{
    if (!stats || input.isNull()) return false;
    QImage image = input.copy(analysisRect(input.rect(), QStringLiteral("reference")))
        .convertToFormat(QImage::Format_ARGB32).rgbSwapped();
    if (image.isNull()) return false;
    KisPaintDeviceSP device = new KisPaintDevice(KoColorSpaceRegistry::instance()->rgb8());
    device->convertFromQImage(image, device->colorSpace()->profile(), 0, 0);
    Stats calculated;
    if (!statsForDevice(device, QRect(0, 0, image.width(), image.height()), &calculated,
                        &stats->distribution)) return false;
    stats->meanL = calculated.meanL;
    stats->meanA = calculated.meanA;
    stats->meanB = calculated.meanB;
    stats->stdL = calculated.stdL;
    stats->stdA = calculated.stdA;
    stats->stdB = calculated.stdB;
    stats->width = image.width();
    stats->height = image.height();
    stats->hash = QString::fromLatin1(QCryptographicHash::hash(
        QByteArray(reinterpret_cast<const char *>(image.constBits()), image.sizeInBytes()),
        QCryptographicHash::Sha256).toHex());
    stats->valid = stats->distribution.valid;
    return stats->valid;
}

void ClipboardColorMatchConfigurationWidget::refreshClipboard()
{
    const QClipboard *clipboard = QGuiApplication::clipboard();
    const QImage image = clipboard && clipboard->mimeData()->hasImage() ? clipboard->image() : QImage();
    if (image.isNull()) {
        m_preview->setToolTip(i18n("Clipboard has no image; the previous analysis is unchanged."));
        return;
    }
    setReferenceImage(image, QStringLiteral("clipboard"));
    emit sigConfigurationItemChanged();
}
QRect ClipboardColorMatchConfigurationWidget::deviceBounds() const
{
    if (!m_device) return QRect();
    QRect bounds = m_device->defaultBounds() ? m_device->defaultBounds()->bounds() : QRect();
    if (bounds.isEmpty()) bounds = m_device->extent();
    return bounds;
}

bool ClipboardColorMatchConfigurationWidget::calculateDeviceStats(LabStats *stats) const
{
    if (!stats || !m_device) return false;
    const QRect bounds = analysisRect(deviceBounds(), QStringLiteral("target"));
    if (bounds.isEmpty()) return false;

    const KoColorSpace *lab = KoColorSpaceRegistry::instance()->lab16();
    if (!lab) return false;
    KisPaintDeviceSP labDevice = new KisPaintDevice(*m_device.data());
    labDevice->convertTo(lab,
                         KoColorConversionTransformation::internalRenderingIntent(),
                         KoColorConversionTransformation::internalConversionFlags());
    Stats calculated;
    if (!statsForDevice(labDevice, bounds, &calculated,
                        &stats->distribution)) return false;
    stats->meanL = calculated.meanL;
    stats->meanA = calculated.meanA;
    stats->meanB = calculated.meanB;
    stats->stdL = calculated.stdL;
    stats->stdA = calculated.stdA;
    stats->stdB = calculated.stdB;
    stats->valid = stats->distribution.valid;
    return stats->valid;
}

void ClipboardColorMatchConfigurationWidget::setReferenceImage(const QImage &image,
                                                                const QString &source,
                                                                const QString &path)
{
    LabStats stats;
    if (!calculateStats(image, &stats)) {
        m_preview->setToolTip(i18n("Could not analyze this image; the previous analysis is unchanged."));
        return;
    }
    m_referenceImage = image;
    m_status->clear();
    m_preview->setToolTip(QString());
    m_stats = stats;
    m_referenceSource = source;
    m_filePath = path;
    const QImage preview = image.scaled(QSize(320, 192), Qt::KeepAspectRatio, Qt::SmoothTransformation);
    m_previewData.clear();
    QBuffer buffer(&m_previewData);
    buffer.open(QIODevice::WriteOnly);
    preview.save(&buffer, "PNG");
    m_preview->setPixmap(QPixmap::fromImage(preview));
    updateReferenceUi();
}

void ClipboardColorMatchConfigurationWidget::browseFile()
{
    const QString path = QFileDialog::getOpenFileName(this,
                                                      i18n("Choose Reference Image"),
                                                      m_filePath,
                                                      i18n("Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff);;All Files (*)"));
    if (path.isEmpty()) return;
    const QImage image(path);
    if (image.isNull()) {
        m_preview->setToolTip(i18n("Could not load this image; the previous analysis is unchanged."));
        return;
    }
    setReferenceImage(image, QStringLiteral("file"), path);
    emit sigConfigurationItemChanged();
}

void ClipboardColorMatchConfigurationWidget::updateSourceUi()
{
    const QString source = m_source ? m_source->currentData().toString() : m_referenceSource;
    const bool file = source == QLatin1String("file");
    m_referenceSource = source.isEmpty() ? QStringLiteral("clipboard") : source;
    if (m_refresh) m_refresh->setVisible(!file);
    if (m_browse) m_browse->setVisible(file);
    updateReferenceUi();
}

void ClipboardColorMatchConfigurationWidget::updateReferenceUi()
{
    if (!m_stats.valid) {
        m_preview->setPixmap(QPixmap());
        m_preview->setText(i18n("Empty"));
        return;
    }
    QPixmap preview;
    if (preview.loadFromData(m_previewData, "PNG")) {
        m_preview->setText(QString());
        m_preview->setPixmap(preview.scaled(m_preview->size(), Qt::KeepAspectRatio, Qt::SmoothTransformation));
    } else {
        m_preview->setPixmap(QPixmap());
        m_preview->setText(i18n("Empty"));
    }
}

KisPropertiesConfigurationSP ClipboardColorMatchConfigurationWidget::configuration() const
{
    auto *config = new KisFilterConfiguration(m_id, 1, KisGlobalResourcesInterface::instance());
    config->setProperty("reference_valid", m_stats.valid);
    config->setProperty("reference_mean_l", m_stats.meanL);
    config->setProperty("reference_mean_a", m_stats.meanA);
    config->setProperty("reference_mean_b", m_stats.meanB);
    config->setProperty("reference_std_l", m_stats.stdL);
    config->setProperty("reference_std_a", m_stats.stdA);
    config->setProperty("reference_std_b", m_stats.stdB);
    config->setProperty("reference_width", m_stats.width);
    config->setProperty("reference_height", m_stats.height);
    config->setProperty("reference_hash", m_stats.hash);
    config->setProperty("reference_preview", m_previewData);
    config->setProperty("reference_source", m_referenceSource);
    // The image and its filesystem location are session-only; the compact
    // preview and frozen statistics are sufficient to restore the effect.
    config->setProperty("source_stats_valid", m_sourceStats.valid);
    config->setProperty("source_mean_l", m_sourceStats.meanL);
    config->setProperty("source_mean_a", m_sourceStats.meanA);
    config->setProperty("source_mean_b", m_sourceStats.meanB);
    config->setProperty("source_std_l", m_sourceStats.stdL);
    config->setProperty("source_std_a", m_sourceStats.stdA);
    config->setProperty("source_std_b", m_sourceStats.stdB);
    config->setProperty("statistical_version", m_statisticalVersion);
    config->setProperty("gamut_protection", m_gamutProtection && m_gamutProtection->isChecked());
    if (m_statisticalVersion >= 2) {
        config->setProperty("reference_distribution", fxmanager::statistical::encodeProfile(m_stats.distribution));
        config->setProperty("source_distribution", fxmanager::statistical::encodeProfile(m_sourceStats.distribution));
    }
    for (auto it = m_regionEnabled.cbegin(); it != m_regionEnabled.cend(); ++it)
        config->setProperty(it.key() + QStringLiteral("_region_enabled"), it.value()->isChecked());
    for (auto it = m_regionBoxes.cbegin(); it != m_regionBoxes.cend(); ++it)
        config->setProperty(it.key(), it.value()->value());
    for (auto it = m_boxes.cbegin(); it != m_boxes.cend(); ++it) config->setProperty(it.key(), it.value()->value());
    config->setProperty("preserve_alpha", true);
    return config;
}

void ClipboardColorMatchConfigurationWidget::setConfiguration(const KisPropertiesConfigurationSP config)
{
    if (!config) return;

    const QString previousHash = m_stats.hash;
    const QSignalBlocker widgetBlocker(this);
    const QSignalBlocker sourceBlocker(m_source);
    m_sourceStats = LabStats();
    m_statisticalVersion = config->getInt("statistical_version", 1);
    m_stats.distribution = fxmanager::statistical::decodeProfile(
        config->getProperty("reference_distribution").toByteArray());
    // Opening an existing configuration is a read, not a new analysis.
    // The live device may already contain this filter's processed output.
    m_sourceStats.distribution = fxmanager::statistical::decodeProfile(
        config->getProperty("source_distribution").toByteArray());
    std::vector<std::unique_ptr<QSignalBlocker>> parameterBlockers;
    for (auto it = m_boxes.cbegin(); it != m_boxes.cend(); ++it)
        parameterBlockers.emplace_back(std::make_unique<QSignalBlocker>(it.value()));
    for (auto it = m_sliders.cbegin(); it != m_sliders.cend(); ++it)
        parameterBlockers.emplace_back(std::make_unique<QSignalBlocker>(it.value()));
    m_stats.meanL = config->getDouble("reference_mean_l", 0.0);
    m_stats.meanA = config->getDouble("reference_mean_a", 0.0);
    m_stats.meanB = config->getDouble("reference_mean_b", 0.0);
    m_stats.stdL = config->getDouble("reference_std_l", 0.0);
    m_stats.stdA = config->getDouble("reference_std_a", 0.0);
    m_stats.stdB = config->getDouble("reference_std_b", 0.0);
    m_stats.width = config->getInt("reference_width", 0);
    m_stats.height = config->getInt("reference_height", 0);
    m_stats.hash = config->getString("reference_hash", QString());
    m_stats.valid = config->getBool("reference_valid", false);
    m_previewData = config->getProperty("reference_preview").toByteArray();
    m_referenceSource = config->getString("reference_source", QStringLiteral("clipboard"));
    if (previousHash.isEmpty() || previousHash != m_stats.hash) m_referenceImage = QImage();
    m_filePath.clear();
    m_status->setText(m_referenceImage.isNull() && m_stats.valid
        ? i18n("Select the reference image again to analyze another region. The saved analysis remains active.")
        : QString());
    for (auto it = m_regionEnabled.cbegin(); it != m_regionEnabled.cend(); ++it) {
        const QSignalBlocker blocker(it.value());
        it.value()->setChecked(config->getBool(it.key() + QStringLiteral("_region_enabled"), false));
    }
    for (const QString &prefix : {QStringLiteral("reference"), QStringLiteral("target")}) {
        const QString base = prefix + QStringLiteral("_region_");
        auto *x = m_regionBoxes.value(base + QStringLiteral("x"));
        auto *y = m_regionBoxes.value(base + QStringLiteral("y"));
        auto *w = m_regionBoxes.value(base + QStringLiteral("w"));
        auto *h = m_regionBoxes.value(base + QStringLiteral("h"));
        const QSignalBlocker bx(x), by(y), bw(w), bh(h);
        w->setMaximum(100.0);
        h->setMaximum(100.0);
        auto value = [&](const QString &key, double fallback) {
            const double v = config->getDouble(key, fallback);
            return std::isfinite(v) ? v : fallback;
        };
        x->setValue(value(base + QStringLiteral("x"), 0.0));
        y->setValue(value(base + QStringLiteral("y"), 0.0));
        updateRegionControls(prefix);
        w->setValue(value(base + QStringLiteral("w"), 100.0));
        h->setValue(value(base + QStringLiteral("h"), 100.0));
    }
    if (config->getBool("source_stats_valid", false)) {
        m_sourceStats.valid = config->getBool("source_stats_valid", false);
        m_sourceStats.meanL = config->getDouble("source_mean_l", 0.0);
        m_sourceStats.meanA = config->getDouble("source_mean_a", 0.0);
        m_sourceStats.meanB = config->getDouble("source_mean_b", 0.0);
        m_sourceStats.stdL = config->getDouble("source_std_l", 0.0);
        m_sourceStats.stdA = config->getDouble("source_std_a", 0.0);
        m_sourceStats.stdB = config->getDouble("source_std_b", 0.0);
    } else if (!m_stats.valid && config->getProperty("source_distribution").toByteArray().isEmpty()) {
        // Only a genuinely new, unconfigured filter takes an initial snapshot.
        calculateDeviceStats(&m_sourceStats);
    }

    for (auto it = m_boxes.begin(); it != m_boxes.end(); ++it) {
        const double fallback = parameterDefault(it.key(), m_statisticalVersion);
        const double saved = config->getDouble(it.key(), fallback);
        it.value()->setValue(std::isfinite(saved) ? saved : fallback);
        if (m_sliders.contains(it.key())) m_sliders[it.key()]->setValue(qRound(it.value()->value()*100));
    }
    if (m_advanced) m_advanced->setVisible(m_statisticalVersion >= 2);
    if (auto *colorGroup = findChild<QGroupBox *>(QStringLiteral("color_matching_group")))
        colorGroup->setVisible(m_statisticalVersion >= 2);
    if (auto *protectionGroup = findChild<QGroupBox *>(QStringLiteral("protection_limits_group")))
        protectionGroup->setVisible(m_statisticalVersion >= 2);
    if (m_gamutProtection) {
        const QSignalBlocker blocker(m_gamutProtection);
        m_gamutProtection->setChecked(config->getBool("gamut_protection", m_statisticalVersion == 2));
    }
    if (m_source) {
        const int index = m_source->findData(m_referenceSource);
        if (index >= 0) m_source->setCurrentIndex(index);
    }

    updateSourceUi();
    updateReferenceUi();
    for (auto it = m_boxes.cbegin(); it != m_boxes.cend(); ++it) {
        // Restoring values with blocked signals also bypasses value-bar updates.
        if (auto *box = dynamic_cast<FxManagerDragSpinBox *>(it.value())) box->refreshValueBar();
    }
}
