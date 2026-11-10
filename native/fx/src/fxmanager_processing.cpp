#include "fxmanager_processing.h"
#include "filter_metadata.h"
#include "float_profile_transform.h"
#include "pointwise_math.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <memory>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSet>
#include <QCoreApplication>
#include <QSaveFile>
#include <QDateTime>
#include <QHash>
#include <QMutex>
#include <QMutexLocker>
#include <QSemaphore>
#include <QStandardPaths>
#include <QThreadPool>
#include <QTemporaryFile>
#include <QRunnable>
#include <KoColorModelStandardIds.h>
#include <KoColorSpace.h>
#include <KoColorSpaceRegistry.h>
#include <KoColorProfile.h>
#include <KoUpdater.h>

namespace fxmanager {
namespace {

QString legacySettingsPath()
{
    const QString base = QStandardPaths::writableLocation(QStandardPaths::AppConfigLocation);
    return base.isEmpty() ? QString() : base + QStringLiteral("/FilterManager/settings.json");
}

const QString &cachedResourceDirectory()
{
    static const QString cached = [] {
        const QString base = qEnvironmentVariable("KLOCALAPPDATA");
        const QString local = base.isEmpty() ? qEnvironmentVariable("LOCALAPPDATA") : base;
        if (local.isEmpty()) return QString();
        QFile kritarc(local + QStringLiteral("/kritarc"));
        if (!kritarc.open(QIODevice::ReadOnly)) return QString();
        const QByteArray content = kritarc.readAll();
        const QList<QByteArray> lines = content.split('\n');
        for (const QByteArray &line : lines) {
            const int separator = line.indexOf('=');
            if (separator <= 0) continue;
            if (line.left(separator).trimmed() != QByteArrayLiteral("ResourceDirectory")) continue;
            return QString::fromUtf8(line.mid(separator + 1)).trimmed();
        }
        return QString();
    }();
    return cached;
}

} // namespace

QString resourceDirectory()
{
    return cachedResourceDirectory();
}

QString settingsPath()
{
    const QString resource = cachedResourceDirectory();
    if (!resource.isEmpty()) {
        return QDir(resource).filePath(QStringLiteral("TFM/settings.json"));
    }
    return legacySettingsPath();
}

QStringList legacySettingsPaths()
{
    const QString resource = cachedResourceDirectory();
    QStringList paths;
    if (!resource.isEmpty()) paths << QDir(resource).filePath(QStringLiteral("pykrita/fxmanager/data/settings.json"));
    if (!resource.isEmpty()) paths << QDir(resource).filePath(QStringLiteral("FilterManager/settings.json"));
    paths << legacySettingsPath();
    return paths;
}

void migrateLegacySettings()
{
    const QString canonical = settingsPath();
    if (canonical.isEmpty() || QFileInfo::exists(canonical)) return;
    for (const QString &legacy : legacySettingsPaths()) {
        if (legacy == canonical || !QFileInfo(legacy).isFile()) continue;
        const QString directory = QFileInfo(canonical).absolutePath();
        if (!QDir().mkpath(directory)) continue;
        QTemporaryFile temporary(QDir(directory).filePath(QStringLiteral("settings.migrate.XXXXXX.tmp")));
        temporary.setAutoRemove(false);
        if (!temporary.open()) continue;
        QFile source(legacy);
        if (!source.open(QIODevice::ReadOnly)) { temporary.remove(); continue; }
        if (temporary.write(source.readAll()) < 0 || !temporary.flush()) {
            temporary.remove();
            continue;
        }
        const QString temporaryPath = temporary.fileName();
        temporary.close();
        // Renaming publishes a complete file and refuses an existing target.
        if (QFile::rename(temporaryPath, canonical)) {
            return;
        }
        QFile::remove(temporaryPath);
        if (QFileInfo::exists(canonical)) return;
    }
}

QString settingsReadPath()
{
    const QString canonical = settingsPath();
    if (QFileInfo(canonical).isFile()) return canonical;
    for (const QString &legacy : legacySettingsPaths()) {
        if (legacy != canonical && QFileInfo(legacy).isFile()) return legacy;
    }
    return QString();
}

namespace {
struct BackendCache {
    QString path;
    qint64 mtime = -1;
    QString globalBackend = QStringLiteral("auto");
    QHash<QString, QString> filterBackends;
};

BackendCache &backendCache()
{
    static BackendCache cache;
    return cache;
}

QMutex &backendMutex()
{
    static QMutex mutex;
    return mutex;
}

void refreshBackendCacheLocked()
{
    BackendCache &cache = backendCache();
    const QString path = settingsReadPath();
    qint64 mtime = 0;
    if (!path.isEmpty()) {
        const QFileInfo info(path);
        mtime = info.exists() ? info.lastModified().toMSecsSinceEpoch() : 0;
    }
    if (path == cache.path && mtime == cache.mtime) return;
    cache.path = path;
    cache.mtime = mtime;
    cache.globalBackend = QStringLiteral("auto");
    cache.filterBackends.clear();
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) return;
    const QJsonObject root = QJsonDocument::fromJson(file.readAll()).object();
    const QString global = root.value(QStringLiteral("backend")).toString();
    if (global == QLatin1String("cpu") || global == QLatin1String("gpu") || global == QLatin1String("auto")) {
        cache.globalBackend = global;
    }
    const QJsonObject perFilter = root.value(QStringLiteral("filter_backends")).toObject();
    for (auto it = perFilter.begin(); it != perFilter.end(); ++it) {
        const QString value = it.value().toString();
        if (value == QLatin1String("cpu") || value == QLatin1String("gpu")) {
            cache.filterBackends.insert(it.key(), value);
        }
    }
}

QString canonicalFilterId(const QString &filterId)
{
    if (filterId.startsWith(QLatin1String("fxmanager_"))) {
        return QStringLiteral("tfm_") + filterId.mid(10);
    }
    return filterId;
}

QString requestedBackend(const QString &filterId)
{
    const QString override = qEnvironmentVariable("TFM_BACKEND").toLower();
    if (override == QLatin1String("cpu") || override == QLatin1String("gpu") || override == QLatin1String("auto")) {
        return override;
    }
    QMutexLocker lock(&backendMutex());
    refreshBackendCacheLocked();
    const BackendCache &cache = backendCache();
    if (!filterId.isEmpty()) {
        const QString canonical = canonicalFilterId(filterId);
        const auto it = cache.filterBackends.constFind(canonical);
        if (it != cache.filterBackends.cend()) return *it;
        if (canonical != filterId) {
            const auto legacy = cache.filterBackends.constFind(filterId);
            if (legacy != cache.filterBackends.cend()) return *legacy;
        }
    }
    return cache.globalBackend;
}
}

namespace {
int configuredThreadCount();
qint64 autoGpuThreshold(const QString &filterId)
{
    const QString id=canonicalFilterId(filterId);
    // End-to-end U8, one CPU thread, RTX 5090; see docs/quality-performance.md.
    // The conservative cold-start crossover was observed at 5120 squared.
    if (id == QLatin1String("tfm_vibrance") && configuredThreadCount() <= 1) return 5120LL*5120;
    if (id == QLatin1String("tfm_vibrance") || id == QLatin1String("tfm_color_temperature")
        || id == QLatin1String("tfm_filmgrain") || id == QLatin1String("tfm_vignette")
        || id == QLatin1String("tfm_color_range_mask"))
        return 128LL*1024*1024/4+1; // No measured GPU win within the U8 buffer budget.
    return 0;
}
}

bool gpuRequested(const QString &filterId, qint64 pixels)
{
    const QString requested=requestedBackend(filterId);
    if (requested == QLatin1String("cpu")) return false;
    if (requested == QLatin1String("gpu")) return true;
    return pixels < 0 || pixels >= autoGpuThreshold(filterId);
}

QString cpuBackendReason(const QString &filterId, qint64 pixels)
{
    if (requestedBackend(filterId) == QLatin1String("auto") && pixels >= 0 && pixels < autoGpuThreshold(filterId))
        return QStringLiteral("Auto: CPU selected by measured image-size threshold");
    return QStringLiteral("CPU selected");
}

void reportBackend(const QString &filter, const QString &actual, const QString &reason, const QString &device)
{
    static QMutex mutex;
    QMutexLocker lock(&mutex);
    // Tiled GPU filters call this once per patch. Keep the last status only.
    static QString lastFilter;
    static QString lastActual;
    static QString lastReason;
    static QString lastDevice;
    if (filter == lastFilter && actual == lastActual && reason == lastReason && device == lastDevice) return;
    lastFilter = filter;
    lastActual = actual;
    lastReason = reason;
    lastDevice = device;

    const QString directory = QFileInfo(settingsPath()).absolutePath();
    if (!QDir().mkpath(directory)) return;
    QJsonObject record;
    record.insert(QStringLiteral("pid"), double(QCoreApplication::applicationPid()));
    record.insert(QStringLiteral("timestamp"), QDateTime::currentDateTimeUtc().toString(Qt::ISODateWithMs));
    record.insert(QStringLiteral("requested"), requestedBackend(filter));
    record.insert(QStringLiteral("actual"), actual);
    record.insert(QStringLiteral("filter"), filter);
    record.insert(QStringLiteral("device"), device);
    record.insert(QStringLiteral("reason"), reason);
    QSaveFile file(QDir(directory).filePath(QStringLiteral("backend-status.json")));
    if (file.open(QIODevice::WriteOnly)) {
        const QByteArray content = QJsonDocument(record).toJson();
        if (file.write(content) == content.size()) file.commit();
    }
}

bool filterEnabled(const QString &filterId)
{
    if (filterId.isEmpty()) return true;
    migrateLegacySettings();
    QFile file(settingsReadPath());
    if (!file.open(QIODevice::ReadOnly)) return true;
    const QJsonObject root = QJsonDocument::fromJson(file.readAll()).object();
    const QJsonValue enabledValue = root.value(QStringLiteral("enabled_filters"));
    if (!enabledValue.isArray()) return true; // missing key → all filters on (legacy)
    QSet<QString> enabled;
    const QJsonArray array = enabledValue.toArray();
    for (const QJsonValue &entry : array) {
        if (entry.isString()) enabled.insert(entry.toString());
    }
    if (enabled.contains(filterId)) return true;
    if (filterId.startsWith(QLatin1String("tfm_"))) {
        const QString legacy = QStringLiteral("fxmanager_") + filterId.mid(4);
        if (enabled.contains(legacy)) return true;
    } else if (filterId.startsWith(QLatin1String("fxmanager_"))) {
        const QString tfm = QStringLiteral("tfm_") + filterId.mid(10);
        if (enabled.contains(tfm)) return true;
    }
    return false;
}

void applyFilterDefaults(const QString &filterId, KisFilterConfigurationSP config)
{
    if (!config) return;
    QFile file(settingsReadPath());
    if (!file.open(QIODevice::ReadOnly)) return;
    const QJsonObject allDefaults = QJsonDocument::fromJson(file.readAll()).object()
        .value(QStringLiteral("filter_defaults")).toObject();
    QJsonObject values = allDefaults.value(filterId).toObject();
    if (values.isEmpty() && filterId.startsWith(QLatin1String("tfm_"))) {
        const QString legacyId = QStringLiteral("fxmanager_") + filterId.mid(4);
        values = allDefaults.value(legacyId).toObject();
    } else if (values.isEmpty() && filterId.startsWith(QLatin1String("fxmanager_"))) {
        const QString tfmId = QStringLiteral("tfm_") + filterId.mid(10);
        values = allDefaults.value(tfmId).toObject();
    }
    if (values.isEmpty()) return;

    const QString canonical = tfm_metadata::canonicalId(filterId);
    for (const auto &spec : tfm_metadata::parameters()) {
        if (spec.filter != canonical || !spec.editable) continue;
        const QJsonValue value = values.value(spec.key);
        if (spec.type == QLatin1String("bool")) {
            if (value.isBool()) config->setProperty(spec.key, value.toBool());
        } else if (spec.type == QLatin1String("enum")) {
            if (value.isString() && spec.options.contains(value.toString()))
                config->setProperty(spec.key, value.toString());
        } else if (value.isDouble()) {
            const double number = value.toDouble();
            const bool integer = spec.type == QLatin1String("integer");
            if (!std::isfinite(number) || number < spec.min || number > spec.max ||
                (integer && std::floor(number) != number)) continue;
            if (integer) config->setProperty(spec.key, int(number));
            else config->setProperty(spec.key, number);
        }
    }
}

void applyBuiltinDefaults(const QString &filterId, KisFilterConfigurationSP config)
{
    if (!config) return;
    const QString canonical = tfm_metadata::canonicalId(filterId);
    for (const auto &spec : tfm_metadata::parameters())
        if (spec.filter == canonical) config->setProperty(spec.key, spec.value);
}

namespace {

int configuredThreadCount()
{
    static const int cached = [] {
        const QByteArray raw = qgetenv("TFM_THREADS");
        if (!raw.isEmpty()) {
            bool ok = false;
            const int value = raw.toInt(&ok);
            if (ok && value > 0) return value;
        }
        migrateLegacySettings();
        QFile file(settingsReadPath());
        if (file.open(QIODevice::ReadOnly)) {
            const int value = QJsonDocument::fromJson(file.readAll()).object().value(QStringLiteral("cpu_threads")).toInt(0);
            if (value > 0) return value;
        }
        return 0;
    }();
    return cached;
}

int workerCount(int rows)
{
    if (rows <= 1) return 1;
    const int configured = configuredThreadCount();
    return std::clamp(std::min(configured > 0 ? configured : 1, rows), 1, 32);
}

thread_local bool insideBand = false;

class BandJob final : public QRunnable
{
public:
    BandJob(std::function<void(int, int)> work, int y0, int y1, std::shared_ptr<QSemaphore> done)
        : m_work(std::move(work)), m_y0(y0), m_y1(y1), m_done(done) { setAutoDelete(true); }
    void run() override {
        insideBand = true;
        m_work(m_y0, m_y1);
        insideBand = false;
        m_done->release();
    }
private:
    std::function<void(int, int)> m_work;
    int m_y0;
    int m_y1;
    std::shared_ptr<QSemaphore> m_done;
};

} // namespace

QImage readImage(KisPaintDeviceSP device, const QRect &rect)
{
    const QImage image = device->convertToQImage(device->colorSpace()->profile(), rect.x(), rect.y(), rect.width(), rect.height());
    return image.convertToFormat(QImage::Format_ARGB32).rgbSwapped();
}

void writeImage(KisPaintDeviceSP device, const QImage &image, const QRect &rect)
{
    device->convertFromQImage(image.rgbSwapped(), device->colorSpace()->profile(), rect.x(), rect.y());
}

namespace {

const KoColorSpace *floatWorkingColorSpace()
{
    // babl's "RGBA float" uses linear sRGB/Rec.709 primaries. Never infer
    // the transfer curve or primaries from the source channel depth.
    auto *registry = KoColorSpaceRegistry::instance();
    const KoColorProfile *profile = registry->p709G10Profile();
    if (!profile) return nullptr;
    const KoColorSpace *space = registry->colorSpace(
        RGBAColorModelID.id(), Float32BitsColorDepthID.id(), profile);
    return space && space->pixelSize() == 4 * sizeof(float) ? space : nullptr;
}

bool needsExtendedSrgbTransfer(const KoColorSpace *space)
{
    // ICC sampled TRCs clamp values outside [0,1]. For Krita's standard sRGB
    // float storage use its analytic extended transfer and a depth-only
    // conversion instead. Other profiles still use the colour engine.
    const auto *standard=KoColorSpaceRegistry::instance()->p709SRGBProfile();
    return space && space->colorModelId()==RGBAColorModelID
        && (space->colorDepthId()==Float16BitsColorDepthID || space->colorDepthId()==Float32BitsColorDepthID)
        && standard && space->profile() && *space->profile()==*standard;
}

} // namespace

FloatRgbaImage readFloatImage(KisPaintDeviceSP device, const QRect &rect)
{
    FloatRgbaImage out;
    if (!device || rect.isEmpty()) return out;
    const KoColorSpace *cs = device->colorSpace();
    const bool extended=needsExtendedSrgbTransfer(cs);
    const KoColorSpace *working = extended
        ? KoColorSpaceRegistry::instance()->colorSpace(RGBAColorModelID.id(),Float32BitsColorDepthID.id(),cs->profile())
        : floatWorkingColorSpace();
    if (!cs || !working) return out;
    const bool floatStorage = cs->colorModelId() == RGBAColorModelID &&
        (cs->colorDepthId() == Float16BitsColorDepthID || cs->colorDepthId() == Float32BitsColorDepthID);
    FloatProfileTransform profileTransform;
    const bool customCurve = floatStorage && !extended && cs->profile() && !cs->profile()->isLinear();
    const bool matrixFloat = customCurve && profileTransform.initialize(cs->profile(), working->profile());

    const qint64 count = qint64(rect.width()) * rect.height();
    if (count <= 0 || count > 268435456LL ||
        count * cs->pixelSize() > std::numeric_limits<int>::max()) return out;

    // Convert an independent buffer: reading must not change the source device,
    // its profile, or its default pixel. No integer intermediate clips HDR.
    QVector<quint8> raw(int(count * cs->pixelSize()));
    device->readBytes(raw.data(), rect.x(), rect.y(), rect.width(), rect.height());
    out.pixels.resize(int(count * 4));
    if (customCurve && !matrixFloat) {
        QVector<float> channels(4);
        for (int i=0;i<count;++i) {
            cs->normalisedChannelsValue(raw.constData()+i*cs->pixelSize(),channels);
            for(int c=0;c<3;++c) if(channels[c]<0 || channels[c]>1) {
                qWarning() << "TFM: HDR ICC LUT/unsupported TRC conversion refused; original pixels retained";
                return {};
            }
        }
    }
    if(extended || matrixFloat) {
        QVector<float> channels(4);
        for(int i=0;i<count;++i) {
            cs->normalisedChannelsValue(raw.constData()+i*cs->pixelSize(),channels);
            std::copy_n(channels.constData(),4,out.pixels.data()+i*4);
            if(matrixFloat) profileTransform.toWorking(out.pixels.data()+i*4);
        }
    } else if (!cs->convertPixelsTo(raw.constData(),
                            reinterpret_cast<quint8 *>(out.pixels.data()),
                            working, quint32(count),
                            KoColorConversionTransformation::internalRenderingIntent(),
                            KoColorConversionTransformation::internalConversionFlags())) {
        return FloatRgbaImage();
    }
    out.width = rect.width();
    out.height = rect.height();
    out.linearHdr = true;
    if(extended) for(int i=0;i<out.pixels.size();i+=4)
        for(int c=0;c<3;++c) out.pixels[i+c]=pointwise::decode(out.pixels[i+c]);
    return out;
}

RawFloatRgbaData readDataFloatRgba(KisPaintDeviceSP device, const QRect &rect)
{
    RawFloatRgbaData out;
    if (!device || rect.isEmpty()) return out;
    const KoColorSpace *cs = device->colorSpace();
    if (!cs) return out;

    const qint64 count = qint64(rect.width()) * rect.height();
    if (count <= 0 || count > 268435456LL ||
        count * cs->pixelSize() > std::numeric_limits<int>::max()) return out;

    // Position/Depth AOVs are data, not colours. Prefer a raw F32 dump when the
    // layer already stores RGBA float so ICC conversion cannot warp XYZ.
    if (cs->colorModelId() == RGBAColorModelID
            && cs->colorDepthId() == Float32BitsColorDepthID
            && cs->pixelSize() == 4 * sizeof(float)) {
        out.pixels.resize(int(count * 4));
        device->readBytes(reinterpret_cast<quint8 *>(out.pixels.data()),
                          rect.x(), rect.y(), rect.width(), rect.height());
        out.width = rect.width();
        out.height = rect.height();
        return out;
    }
    return {};
}

bool writeFloatImage(KisPaintDeviceSP device, const FloatRgbaImage &image, const QRect &rect)
{
    if (!device || image.isNull() || rect.isEmpty() || !image.linearHdr) return false;
    if (image.width != rect.width() || image.height != rect.height()) return false;
    const KoColorSpace *cs = device->colorSpace();
    const bool extended=needsExtendedSrgbTransfer(cs);
    const KoColorSpace *working = extended
        ? KoColorSpaceRegistry::instance()->colorSpace(RGBAColorModelID.id(),Float32BitsColorDepthID.id(),cs->profile())
        : floatWorkingColorSpace();
    if (!cs || !working) return false;
    const bool floatStorage = cs->colorModelId() == RGBAColorModelID &&
        (cs->colorDepthId() == Float16BitsColorDepthID || cs->colorDepthId() == Float32BitsColorDepthID);
    FloatProfileTransform profileTransform;
    const bool customCurve = floatStorage && !extended && cs->profile() && !cs->profile()->isLinear();
    const bool matrixFloat = customCurve && profileTransform.initialize(cs->profile(), working->profile());

    const qint64 count = qint64(rect.width()) * rect.height();
    if (count <= 0 || count > 268435456LL ||
        count * cs->pixelSize() > std::numeric_limits<int>::max()) return false;

    QVector<quint8> raw(int(count * cs->pixelSize()));
    QVector<float> encoded;
    const float *source=image.pixels.constData();
    if(customCurve && !matrixFloat) {
        for(int i=0;i<image.pixels.size();i+=4) for(int c=0;c<3;++c) if(image.pixels[i+c]<0 || image.pixels[i+c]>1) {
            qWarning() << "TFM: HDR ICC LUT/unsupported TRC output refused; original pixels retained";
            return false;
        }
    }
    if(extended || matrixFloat) {
        encoded=image.pixels;
        float *values=encoded.data();
        for(int i=0;i<encoded.size();i+=4) {
            if(matrixFloat) profileTransform.fromWorking(values+i);
            else for(int c=0;c<3;++c) values[i+c]=pointwise::encode(values[i+c]);
        }
        source=encoded.constData();
    }
    if(extended || matrixFloat) {
        QVector<float> channels(4);
        for(int i=0;i<count;++i) {
            std::copy_n(source+i*4,4,channels.data());
            cs->fromNormalisedChannelsValue(raw.data()+i*cs->pixelSize(),channels);
        }
    } else if (!working->convertPixelsTo(reinterpret_cast<const quint8 *>(source),
                                 raw.data(), cs, quint32(count),
                                 KoColorConversionTransformation::internalRenderingIntent(),
                                 KoColorConversionTransformation::internalConversionFlags())) return false;
    // Publish only after the complete reverse ICC conversion succeeds.
    device->writeBytes(raw.constData(), rect.x(), rect.y(), rect.width(), rect.height());
    return true;
}

bool requiresFloatProcessing(KisPaintDeviceSP device)
{
    return device && device->colorSpace()->colorDepthId() != Integer8BitsColorDepthID;
}

EncodedRgbaImage EncodedRgbaImage::copy(const QRect &rect) const
{
    if(isNull() || rect.isEmpty() || !QRect(0,0,width,height).contains(rect)) return {};
    EncodedRgbaImage out{rect.width(),rect.height(),QVector<float>(rect.width()*rect.height()*4)};
    for(int y=0;y<rect.height();++y)
        std::copy_n(pixels.constData()+4*((rect.y()+y)*width+rect.x()),rect.width()*4,out.pixels.data()+4*y*rect.width());
    return out;
}

EncodedRgbaImage readEncodedImage(KisPaintDeviceSP device, const QRect &rect)
{
    auto linear=readFloatImage(device,rect);
    if(linear.isNull()) return {};
    EncodedRgbaImage out{linear.width,linear.height,std::move(linear.pixels)};
    for(int i=0;i<out.pixels.size();i+=4)
        for(int c=0;c<3;++c) out.pixels[i+c]=pointwise::encode(out.pixels[i+c]);
    return out;
}

bool writeEncodedImage(KisPaintDeviceSP device, const EncodedRgbaImage &image, const QRect &rect)
{
    if(image.isNull()) return false;
    FloatRgbaImage linear;
    linear.width=image.width; linear.height=image.height; linear.pixels=image.pixels;
    for(int i=0;i<linear.pixels.size();i+=4)
        for(int c=0;c<3;++c) linear.pixels[i+c]=pointwise::decode(linear.pixels[i+c]);
    return writeFloatImage(device,linear,rect);
}

bool transformEncoded(KisPaintDeviceSP device, const QRect &rect, const QString &filter,
                      KoUpdater *updater, const std::function<void(float *, int, int)> &transform)
{
    if(updater && updater->interrupted()) return false;
    auto output=readEncodedImage(device,rect);
    if(output.isNull()) {
        reportBackend(filter,QStringLiteral("cpu"),QStringLiteral("Float colour conversion unavailable; pixels unchanged"));
        return false;
    }
    // Detach on the caller thread before parallel writers take disjoint rows.
    float *pixels=output.pixels.data();
    parallelRows(output.height,[&](int y0,int y1) {
        for(int y=y0;y<y1;++y) {
            if(updater && updater->interrupted()) return;
            for(int x=0;x<output.width;++x)
                transform(pixels+4*(y*output.width+x),rect.x()+x,rect.y()+y);
        }
    });
    if(updater && updater->interrupted()) return false;
    const bool written=writeEncodedImage(device,output,rect);
    reportBackend(filter,QStringLiteral("cpu"),written
        ? QStringLiteral("High-depth CPU: float GPU implementation unavailable")
        : QStringLiteral("Float output conversion failed; pixels unchanged"));
    if(written && updater) updater->setProgress(100);
    return written;
}

void parallelRows(int rows, const std::function<void(int, int)> &body)
{
    const int workers = workerCount(rows);
    if (workers <= 1 || insideBand) { body(0, rows); return; }
    // One fixed concurrency cap for this plugin, not a resized pool per patch.
    // Krita already schedules tiles; the default remains a single CPU worker.
    static QThreadPool *pool = [] {
        auto *value = new QThreadPool;
        value->setMaxThreadCount(workerCount(32));
        return value;
    }();
    auto done = std::make_shared<QSemaphore>(0);
    const int band = (rows + workers - 1) / workers;
    int launched = 0;
    for (int start = 0; start < rows; start += band) {
        pool->start(new BandJob(body, start, std::min(rows, start + band), done));
        ++launched;
    }
    done->acquire(launched);
}

double deterministicNoise(int x, int y, int seed, int channel)
{
    const quint32 ux = quint32(x);
    const quint32 uy = quint32(y);
    const quint32 us = quint32(seed);
    const quint32 uc = quint32(channel);
    quint32 h = ux * 374761393u + uy * 668265263u + us * 2246822519u + uc * 3266489917u;
    h = (h ^ (h >> 13)) * 1274126177u;
    h ^= h >> 16;
    return (double(h % 10000u) / 5000.0) - 1.0;
}

} // namespace fxmanager
