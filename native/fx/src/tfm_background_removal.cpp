#include "tfm_processing.h"
#include "tfm_background_removal.h"
#include "background_composite.h"

#include "tfm_birefnet.h"
#include "tfm_background_mask.h"

#include <KisGlobalResourcesInterface.h>
#include <KoUpdater.h>
#include <filter/kis_filter_category_ids.h>
#include <kis_config_widget.h>
#include <kis_paint_device.h>
#include <klocalizedstring.h>

#include <QApplication>
#include <QCheckBox>
#include <QComboBox>
#include <QDesktopServices>
#include <QDir>
#include <QElapsedTimer>
#include <QHBoxLayout>
#include <QMetaObject>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QSignalBlocker>
#include <QSlider>
#include <QSpinBox>
#include <QUrl>
#include <QVBoxLayout>

#include <algorithm>
#include <cstring>
#include <stdexcept>
#include <vector>

namespace {

constexpr auto kFastMaskMode = "fast_mask";
constexpr auto kRefinedForegroundMode = "refined_foreground";
constexpr auto kCutoutOutput = "cutout";
constexpr auto kGrayscaleMaskOutput = "grayscale_mask";

QString outputMode(const KisPropertiesConfigurationSP &config)
{
    return config && config->getString("output_mode", QString::fromLatin1(kCutoutOutput))
            == QString::fromLatin1(kGrayscaleMaskOutput)
        ? QString::fromLatin1(kGrayscaleMaskOutput) : QString::fromLatin1(kCutoutOutput);
}

QString foregroundMode(const KisPropertiesConfigurationSP &config)
{
    if (!config) return QString::fromLatin1(kRefinedForegroundMode);
    if (config->hasProperty("foreground_mode")) {
        const QString mode = config->getString("foreground_mode", QString::fromLatin1(kRefinedForegroundMode));
        if (mode == QString::fromLatin1(kFastMaskMode)
            || mode == QString::fromLatin1(kRefinedForegroundMode)) {
            return mode;
        }
    }
    return config->getBool("foreground_estimation", true)
        ? QString::fromLatin1(kRefinedForegroundMode)
        : QString::fromLatin1(kFastMaskMode);
}

class BackgroundRemovalConfigurationWidget final : public KisConfigWidget
{
public:
    explicit BackgroundRemovalConfigurationWidget(QWidget *parent)
        : KisConfigWidget(parent)
    {
        auto *layout = new QVBoxLayout(this);
        layout->addWidget(new QLabel(i18n("Separate foreground from background with BiRefNet."), this));

        auto *modelRow = new QHBoxLayout;
        modelRow->addWidget(new QLabel(i18n("Model"), this));
        m_model = new QComboBox(this);
        for (const QString &model : BirefnetRuntime::instance().availableModels()) {
            m_model->addItem(model, model);
        }
        const bool missingModels = m_model->count() == 0;
        if (missingModels) {
            m_model->addItem(i18n("No BiRefNet model files found"));
            m_model->setEnabled(false);
        }
        modelRow->addWidget(m_model, 1);
        layout->addLayout(modelRow);
        if (missingModels) {
            auto *cta = new QLabel(
                i18n("Place BiRefNet-lite-F16.gguf or BiRefNet-dynamic-F16.gguf in the models folder, then reopen this filter."),
                this);
            cta->setWordWrap(true);
            layout->addWidget(cta);
            auto *openModels = new QPushButton(i18n("Open BiRefNet models folder"), this);
            openModels->setObjectName(QStringLiteral("background_open_models"));
            layout->addWidget(openModels);
            connect(openModels, &QPushButton::clicked, this, [] {
                const QString directory = BirefnetRuntime::instance().modelsDirectory();
                if (directory.isEmpty()) {
                    QMessageBox::warning(nullptr, i18n("Background Removal"),
                                         i18n("Could not locate Krita’s resource directory."));
                    return;
                }
                if (!QDir().mkpath(directory)) {
                    QMessageBox::warning(nullptr, i18n("Background Removal"),
                                         i18n("Could not create %1").arg(directory));
                    return;
                }
                if (!QDesktopServices::openUrl(QUrl::fromLocalFile(directory))) {
                    QMessageBox::warning(nullptr, i18n("Background Removal"),
                                         i18n("Could not open %1").arg(directory));
                }
            });
        }

        auto *backendRow = new QHBoxLayout;
        backendRow->addWidget(new QLabel(i18n("Backend"), this));
        m_backend = new QComboBox(this);
        m_backend->addItem(i18n("CPU"), QStringLiteral("cpu"));
        m_backend->addItem(i18n("GPU"), QStringLiteral("gpu"));
        // Backend initialization belongs to processing, never dialog creation.
        backendRow->addWidget(m_backend, 1);
        layout->addLayout(backendRow);

        auto *outputRow = new QHBoxLayout;
        outputRow->addWidget(new QLabel(i18n("Output"), this));
        m_outputMode = new QComboBox(this);
        m_outputMode->setObjectName(QStringLiteral("output_mode"));
        m_outputMode->addItem(i18n("Cutout"), QString::fromLatin1(kCutoutOutput));
        m_outputMode->addItem(i18n("Grayscale Mask"), QString::fromLatin1(kGrayscaleMaskOutput));
        m_outputMode->setToolTip(i18n("Grayscale Mask shows the processed model mask as opaque grayscale, independent of the original alpha. Foreground refinement applies only to Cutout."));
        outputRow->addWidget(m_outputMode, 1);
        layout->addLayout(outputRow);

        auto *foregroundRow = new QHBoxLayout;
        foregroundRow->addWidget(new QLabel(i18n("Foreground"), this));
        m_foregroundMode = new QComboBox(this);
        m_foregroundMode->addItem(i18n("Fast Mask"), QString::fromLatin1(kFastMaskMode));
        m_foregroundMode->addItem(i18n("Refined Foreground"), QString::fromLatin1(kRefinedForegroundMode));
        foregroundRow->addWidget(m_foregroundMode, 1);
        layout->addLayout(foregroundRow);
        const auto updateForegroundAvailability = [this] {
            m_foregroundMode->setEnabled(m_outputMode->currentData().toString()
                                         != QString::fromLatin1(kGrayscaleMaskOutput));
        };
        connect(m_outputMode, QOverload<int>::of(&QComboBox::currentIndexChanged),
                this, [updateForegroundAvailability](int) { updateForegroundAvailability(); });
        updateForegroundAvailability();

        auto addMaskControl = [this, layout](const QString &key, const QString &label, int minimum, int maximum) {
            auto *row = new QHBoxLayout;
            auto *title = new QLabel(label, this);
            title->setMinimumWidth(150);
            row->addWidget(title);
            auto *slider = new QSlider(Qt::Orientation::Horizontal, this);
            slider->setObjectName(key + QStringLiteral("_slider"));
            slider->setRange(minimum, maximum);
            slider->setSingleStep(1);
            slider->setPageStep(10);
            row->addWidget(slider, 1);
            auto *value = new QSpinBox(this);
            value->setObjectName(key);
            value->setRange(minimum, maximum);
            value->setSuffix(QStringLiteral("%"));
            value->setFixedWidth(76);
            row->addWidget(value);
            layout->addLayout(row);
            connect(slider, &QSlider::valueChanged, value, &QSpinBox::setValue);
            connect(value, QOverload<int>::of(&QSpinBox::valueChanged), slider, &QSlider::setValue);
            return value;
        };
        m_preserve = addMaskControl(QStringLiteral("preserve_foreground"), i18n("Preserve Foreground"), 0, 100);
        m_contrast = addMaskControl(QStringLiteral("mask_contrast"), i18n("Mask Contrast"), -100, 100);
        auto *automaticPreview = new QCheckBox(i18n("Automatic Preview"), this);
        automaticPreview->setObjectName(QStringLiteral("background_auto_preview"));
        automaticPreview->setChecked(true);
        layout->addWidget(automaticPreview);
        connect(automaticPreview, &QCheckBox::toggled, this, [this](bool enabled) {
            m_autoPreview = enabled;
            if (enabled) applyEditedConfiguration();
        });

        auto *preview = new QPushButton(i18n("Apply Preview"), this);
        preview->setObjectName(QStringLiteral("background_apply_preview"));
        layout->addWidget(preview);
        connect(preview, &QPushButton::clicked, this, [this] { applyEditedConfiguration(); });
        auto persistAutomaticPreview = [this](int) {
            if (m_autoPreview) applyEditedConfiguration();
        };
        connect(m_model, QOverload<int>::of(&QComboBox::currentIndexChanged), this, persistAutomaticPreview);
        connect(m_backend, QOverload<int>::of(&QComboBox::currentIndexChanged), this, persistAutomaticPreview);
        connect(m_foregroundMode, QOverload<int>::of(&QComboBox::currentIndexChanged), this, persistAutomaticPreview);
        connect(m_outputMode, QOverload<int>::of(&QComboBox::currentIndexChanged), this, persistAutomaticPreview);
        connect(m_preserve, QOverload<int>::of(&QSpinBox::valueChanged), this, persistAutomaticPreview);
        connect(m_contrast, QOverload<int>::of(&QSpinBox::valueChanged), this, persistAutomaticPreview);
        layout->addStretch();
    }

    void setConfiguration(const KisPropertiesConfigurationSP config) override
    {
        const QSignalBlocker modelSignals(m_model);
        const QSignalBlocker backendSignals(m_backend);
        const QSignalBlocker foregroundSignals(m_foregroundMode);
        const QSignalBlocker outputSignals(m_outputMode);
        const QSignalBlocker preserveSignals(m_preserve);
        const QSignalBlocker contrastSignals(m_contrast);
        const QSignalBlocker preserveSliderSignals(findChild<QSlider *>(QStringLiteral("preserve_foreground_slider")));
        const QSignalBlocker contrastSliderSignals(findChild<QSlider *>(QStringLiteral("mask_contrast_slider")));
        m_preserve->setValue(config->getInt("preserve_foreground", 0));
        m_contrast->setValue(config->getInt("mask_contrast", 0));
        findChild<QSlider *>(QStringLiteral("preserve_foreground_slider"))->setValue(m_preserve->value());
        findChild<QSlider *>(QStringLiteral("mask_contrast_slider"))->setValue(m_contrast->value());
        const QString model = config->getString("model", QStringLiteral("BiRefNet-lite-F16.gguf"));
        const int modelIndex = m_model->findData(model);
        if (modelIndex >= 0) m_model->setCurrentIndex(modelIndex);
        const QString backend = config->getString("backend", QStringLiteral("cpu"));
        const int backendIndex = m_backend->findData(backend);
        if (backendIndex >= 0) m_backend->setCurrentIndex(backendIndex);
        const int foregroundIndex = m_foregroundMode->findData(foregroundMode(config));
        if (foregroundIndex >= 0) m_foregroundMode->setCurrentIndex(foregroundIndex);
        m_outputMode->setCurrentIndex(m_outputMode->findData(outputMode(config)));
        m_foregroundMode->setEnabled(m_outputMode->currentData().toString()
                                     != QString::fromLatin1(kGrayscaleMaskOutput));
        m_applied = editedConfiguration();
    }

    KisPropertiesConfigurationSP configuration() const override
    {
        return m_applied ? m_applied : editedConfiguration();
    }

private:
    void applyEditedConfiguration()
    {
        m_preserve->interpretText();
        m_contrast->interpretText();
        // Replace the snapshot before notifying Krita. The host may finish the
        // currently running stroke on accept without reading configuration again.
        m_applied = editedConfiguration();
        emit sigConfigurationItemChanged();
    }

    KisPropertiesConfigurationSP editedConfiguration() const
    {
        auto config = KisFilterConfigurationSP(new KisFilterConfiguration(
            KisFilterBackgroundRemoval::id().id(), 1, KisGlobalResourcesInterface::instance()));
        config->setProperty("model", m_model->currentData().toString());
        config->setProperty("backend", m_backend->currentData().toString());
        config->setProperty("output_mode", m_outputMode->currentData().toString());
        const QString mode = m_foregroundMode->currentData().toString();
        config->setProperty("foreground_mode", mode);
        config->setProperty("foreground_estimation", mode != QString::fromLatin1(kFastMaskMode));
        config->setProperty("preserve_foreground", m_preserve->value());
        config->setProperty("mask_contrast", m_contrast->value());
        return config;
    }

private:
    KisPropertiesConfigurationSP m_applied;
    QComboBox *m_model = nullptr;
    QComboBox *m_backend = nullptr;
    QComboBox *m_foregroundMode = nullptr;
    QComboBox *m_outputMode = nullptr;
    QSpinBox *m_preserve = nullptr;
    QSpinBox *m_contrast = nullptr;
    bool m_autoPreview = true;
};

std::vector<uint8_t> rgbPixels(const QImage &image)
{
    std::vector<uint8_t> pixels(size_t(image.width()) * size_t(image.height()) * 3);
    for (int y = 0; y < image.height(); ++y) {
        const QRgb *row = reinterpret_cast<const QRgb *>(image.constScanLine(y));
        auto *dst = pixels.data() + size_t(y) * size_t(image.width()) * 3;
        for (int x = 0; x < image.width(); ++x) {
            dst[x * 3 + 0] = qRed(row[x]);
            dst[x * 3 + 1] = qGreen(row[x]);
            dst[x * 3 + 2] = qBlue(row[x]);
        }
    }
    return pixels;
}

} // namespace

KisFilterBackgroundRemoval::KisFilterBackgroundRemoval()
    : KisFilter(id(), FiltersCategoryOtherId, i18n("&Background Removal..."))
{
    setSupportsPainting(false);
    setSupportsAdjustmentLayers(false);
    setSupportsThreading(false);
    setSupportsLevelOfDetail(false);
    setColorSpaceIndependence(TO_RGBA8);
}

KisFilterConfigurationSP KisFilterBackgroundRemoval::defaultConfiguration(KisResourcesInterfaceSP resources) const
{
    auto config = factoryConfiguration(resources);

    config->setProperty("foreground_estimation", true);

    tfm::applyBuiltinDefaults(id().id(), config);
    tfm::applyFilterDefaults(id().id(), config); return config;
}

KisConfigWidget *KisFilterBackgroundRemoval::createConfigurationWidget(QWidget *parent,
                                                                        const KisPaintDeviceSP,
                                                                        bool) const
{
    return new BackgroundRemovalConfigurationWidget(parent);
}

void KisFilterBackgroundRemoval::processImpl(KisPaintDeviceSP device,
                                             const QRect &applyRect,
                                             const KisFilterConfigurationSP config,
                                             KoUpdater *updater) const
{
    if (!device || applyRect.isEmpty() || (updater && updater->interrupted())) return;
    if (updater) updater->setAutoNestedName(i18n("Background Removal"));

    QImage image = device->convertToQImage(device->colorSpace()->profile(), applyRect.x(), applyRect.y(),
                                           applyRect.width(), applyRect.height());
    if (image.isNull() || image.width() < 64 || image.height() < 64) return;
    image = image.convertToFormat(QImage::Format_ARGB32);
    const bool highDepth=tfm::requiresFloatProcessing(device);
    tfm::EncodedRgbaImage originalFloat;
    QByteArray originalBytes;
    if(highDepth) {
        originalFloat=tfm::readEncodedImage(device,applyRect);
        if(originalFloat.isNull()) return;
        originalBytes.resize(image.width()*image.height()*device->pixelSize());
        device->readBytes(reinterpret_cast<quint8*>(originalBytes.data()),applyRect);
        // A deliberately bounded inference proxy, separate from the original.
        for(int y=0;y<image.height();++y) {
            auto *row=reinterpret_cast<QRgb*>(image.scanLine(y));
            for(int x=0;x<image.width();++x) {
                const auto *p=originalFloat.pixels.constData()+4*(y*image.width()+x);
                auto channel=[&](int c) { return int(std::lround(std::clamp(p[c],0.0f,1.0f)*255)); };
                row[x]=qRgba(channel(0),channel(1),channel(2),channel(3));
            }
        }
    }
    const std::vector<uint8_t> rgb = rgbPixels(image);
    const visp::image_view input({image.width(), image.height()}, visp::image_format::rgb_u8, rgb.data());

    auto &runtime = BirefnetRuntime::instance();
    const QString modelName = config ? config->getString("model", QStringLiteral("BiRefNet-lite-F16.gguf"))
                                     : QStringLiteral("BiRefNet-lite-F16.gguf");
    const QString backend = config ? config->getString("backend", QStringLiteral("cpu")) : QStringLiteral("cpu");
    const visp::backend_type backendType = backend == QStringLiteral("gpu")
        ? visp::backend_type::gpu : visp::backend_type::cpu;

    if (updater) updater->setProgress(10);
    try {
        QElapsedTimer stageTimer;
        stageTimer.start();
        visp::image_data mask = runtime.removeBackground(input, modelName, backendType);
        const int preserve = std::clamp(config ? config->getInt("preserve_foreground", 0) : 0, 0, 100);
        const int contrast = std::clamp(config ? config->getInt("mask_contrast", 0) : 0, -100, 100);
        if (preserve || contrast) {
            uint8_t lookup[256];
            for (int i = 0; i < 256; ++i) {
                float alpha = float(i) / 255.0f;
                if (preserve) alpha = std::pow(alpha, 1.0f - 0.8f * preserve / 100.0f);
                alpha = std::clamp(0.5f + (alpha - 0.5f) * (1.0f + contrast / 100.0f), 0.0f, 1.0f);
                lookup[i] = uint8_t(std::clamp(int(std::lround(alpha * 255.0f)), 0, 255));
            }
            auto values = visp::image_span(mask).as_bytes();
            for (auto &value : values) value = lookup[value];
        }
        qInfo().noquote() << "FXM Background Removal stage=inference ms=" << stageTimer.elapsed()
                          << " model=" << modelName << " backend=" << backend;
        if (updater && updater->interrupted()) return;
        if (updater) updater->setProgress(80);
        if (outputMode(config) == QString::fromLatin1(kGrayscaleMaskOutput)) {
            const auto bytes = visp::image_view(mask).as_bytes();
            const QImage output = tfm::background_removal::grayscaleMaskImage(
                bytes.data(), image.width(), image.height());
            if (output.isNull()) return;
            if (updater && updater->interrupted()) return;
            device->convertFromQImage(output, device->colorSpace()->profile(), applyRect.x(), applyRect.y());
        } else if (foregroundMode(config) == QString::fromLatin1(kRefinedForegroundMode)) {
            constexpr int kForegroundMaxSide = 1024;
            visp::i32x2 foregroundExtent = mask.extent;
            const int foregroundMaxSide = std::max(foregroundExtent[0], foregroundExtent[1]);
            if (foregroundMaxSide > kForegroundMaxSide) {
                const float scale = float(kForegroundMaxSide) / float(foregroundMaxSide);
                foregroundExtent = {
                    std::max(64, int(foregroundExtent[0] * scale)),
                    std::max(64, int(foregroundExtent[1] * scale))};
            }

            // Downsample the compact 8-bit inputs before converting to float. This
            // avoids allocating full-resolution float RGBA and alpha buffers for
            // the foreground estimator on large documents.
            visp::image_data foregroundRgbData;
            visp::image_view foregroundRgb = input;
            visp::image_data foregroundMaskData;
            visp::image_view foregroundMask = mask;
            if (foregroundExtent != mask.extent) {
                foregroundRgbData = visp::image_scale(input, foregroundExtent);
                foregroundRgb = foregroundRgbData;
                foregroundMaskData = visp::image_scale(mask, foregroundExtent);
                foregroundMask = foregroundMaskData;
            }
            // image_u8_to_f32 already normalizes byte channels to [0, 1].
            visp::image_data foregroundInput = visp::image_u8_to_f32(
                foregroundRgb, visp::image_format::rgba_f32);
            visp::image_data foregroundMaskF32 = visp::image_u8_to_f32(
                foregroundMask, visp::image_format::alpha_f32);
            visp::image_data foreground = visp::image_estimate_foreground(
                foregroundInput, foregroundMaskF32);
            if (foregroundExtent != mask.extent) {
                foreground = visp::image_scale(foreground, mask.extent);
            }
            auto foregroundPixels = visp::image_span(foreground).as_floats();
            const auto fullMaskPixels = visp::image_view(mask).as_bytes();
            if(highDepth) {
                tfm::background_removal::compositeRefined(originalFloat.pixels.data(),foregroundPixels.data(),
                    rgb.data(),fullMaskPixels.data(),size_t(image.width())*image.height());
                if(updater && updater->interrupted()) return;
                const bool written=tfm::writeEncodedImage(device,originalFloat,applyRect);
                if(!written) throw std::runtime_error("High-depth foreground conversion failed; pixels unchanged");
                if(updater) updater->setProgress(100);
                return;
            }
            for (int y = 0; y < image.height(); ++y) {
                const QRgb *sourceRow = reinterpret_cast<const QRgb *>(image.constScanLine(y));
                const int rowOffset = y * image.width();
                for (int x = 0; x < image.width(); ++x) {
                    const size_t pixel = size_t(rowOffset + x);
                    const float originalAlpha = qAlpha(sourceRow[x]) / 255.0f;
                    foregroundPixels[pixel * 4 + 3]
                        = (float(fullMaskPixels[pixel]) / 255.0f) * originalAlpha;
                }
            }
            const visp::image_data foregroundU8 = visp::image_f32_to_u8(
                foreground, visp::image_format::rgba_u8);
            QImage result(image.size(), QImage::Format_RGBA8888);
            const auto view = visp::image_view(foregroundU8);
            const auto bytes = view.as_bytes();
            const int rowBytes = result.width() * 4;
            for (int y = 0; y < result.height(); ++y) {
                std::memcpy(result.scanLine(y), bytes.data() + size_t(y) * rowBytes, size_t(rowBytes));
            }
            if (updater && updater->interrupted()) return;
            device->convertFromQImage(result, device->colorSpace()->profile(), applyRect.x(), applyRect.y());
        } else {
            const auto bytes = visp::image_view(mask).as_bytes();
            if(highDepth) {
                const auto *space=device->colorSpace();
                auto *raw=reinterpret_cast<quint8*>(originalBytes.data());
                for(int y=0;y<image.height();++y) {
                    if(updater && updater->interrupted()) return;
                    for(int x=0;x<image.width();++x) {
                        const int i=y*image.width()+x;
                        auto *pixel=raw+i*space->pixelSize();
                        if(bytes[i]!=255) space->setOpacity(pixel,space->opacityF(pixel)*(double(bytes[i])/255.0),1);
                    }
                }
                if(updater && updater->interrupted()) return;
                device->writeBytes(reinterpret_cast<const quint8*>(originalBytes.constData()),applyRect);
                if(updater) updater->setProgress(100);
                return;
            }
            QImage output = image;
            for (int y = 0; y < output.height(); ++y) {
                QRgb *row = reinterpret_cast<QRgb *>(output.scanLine(y));
                const auto *maskRow = bytes.data() + size_t(y) * output.width();
                for (int x = 0; x < output.width(); ++x) {
                    const int alpha = (qAlpha(row[x]) * maskRow[x] + 127) / 255;
                    row[x] = qRgba(qRed(row[x]), qGreen(row[x]), qBlue(row[x]), alpha);
                }
            }
            if(updater && updater->interrupted()) return;
            device->convertFromQImage(output, device->colorSpace()->profile(), applyRect.x(), applyRect.y());
        }
    } catch (const std::exception &e) {
        const QString message = QString::fromUtf8(e.what());
        if (QCoreApplication::closingDown() || (updater && updater->interrupted())) return;
        qWarning().noquote() << "FXM Background Removal stage=failed error=" << message;
        if (qApp) QMetaObject::invokeMethod(qApp, [message] {
            if (QCoreApplication::closingDown()) return;
            auto *dialog = new QMessageBox(QMessageBox::Critical,
                                           i18n("Background Removal"),
                                           i18n("Background removal failed: %1").arg(message),
                                           QMessageBox::Ok,
                                           QApplication::activeWindow());
            dialog->setAttribute(Qt::WidgetAttribute::WA_DeleteOnClose);
            dialog->open();
        }, Qt::ConnectionType::QueuedConnection);
    }
    if (updater) updater->setProgress(100);
}
