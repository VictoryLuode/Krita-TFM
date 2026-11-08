#include "fxmanager_processing.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
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

bool gpuRequested(const QString &filterId)
{
    return requestedBackend(filterId) != QLatin1String("cpu");
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

    auto number = [&](const char *key, double min, double max, bool integer = false) {
        const QJsonValue value = values.value(QLatin1String(key));
        if (!value.isDouble()) return;
        const double n = value.toDouble();
        if (!std::isfinite(n) || n < min || n > max || (integer && std::floor(n) != n)) return;
        if (integer) config->setProperty(key, int(n)); else config->setProperty(key, n);
    };
    auto boolean = [&](const char *key) {
        const QJsonValue value = values.value(QLatin1String(key));
        if (value.isBool()) config->setProperty(key, value.toBool());
    };
    auto choice = [&](const char *key, std::initializer_list<const char *> options) {
        const QJsonValue value = values.value(QLatin1String(key));
        if (!value.isString()) return;
        const QString text = value.toString();
        for (const char *option : options) if (text == QLatin1String(option)) { config->setProperty(key, text); return; }
    };
    if (filterId == QLatin1String("tfm_bloom") || filterId == QLatin1String("fxmanager_bloom")) {
        number("threshold",0,1); number("radius",1,64); number("strength",0,2); number("diffusion",0,1); number("softness",0,1);
    } else if (filterId == QLatin1String("tfm_filmgrain") || filterId == QLatin1String("fxmanager_filmgrain")) {
        choice("preset",{"8mm_caffenol","8mm_home_movie","super_8","16mm_broadcast","16mm_indie_cinema","35mm_portra_400","super_35","70mm_cinema","custom"});
        number("amount",0,1); number("size",0.5,8); number("seed",0,999,true); boolean("monochrome");
    } else if (filterId == QLatin1String("tfm_lens_distortion") || filterId == QLatin1String("fxmanager_lens_distortion")) {
        choice("mode",{"radial","horizontal"}); number("distortion",-1,1); number("dispersion",0,1); boolean("jitter"); boolean("fit");
    } else if (filterId == QLatin1String("tfm_vignette") || filterId == QLatin1String("fxmanager_vignette")) {
        number("factor",0,1); number("feather",0,1); number("corner_roundness",0,1); number("scale_x",0.0001,4); number("scale_y",0.0001,4); number("offset_x",-2,2); number("offset_y",-2,2); number("angle",-180,180);
    } else if (filterId == QLatin1String("tfm_clipboard_color_match") || filterId == QLatin1String("fxmanager_clipboard_color_match")) {
        choice("reference_source",{"clipboard","file"}); number("match_strength",0,1); number("luminance",0,2); number("color_intensity",0,2); number("fade",0,1); number("tone_distribution",0,1); number("tonal_color",0,1); number("color_correlation",0,1); number("gain_limit",1,8); number("shift_limit",0,100); number("variance_floor",0.1,10); boolean("gamut_protection");
    } else if (filterId == QLatin1String("tfm_guided_color_match") || filterId == QLatin1String("fxmanager_guided_color_match")) {
        number("align_brightness",0,1); number("match_strength",0,1); number("chroma",0,2); number("keep_local",0,1); number("match_local",0,1); number("smoothness",0,1);
    } else if (filterId == QLatin1String("tfm_background_removal") || filterId == QLatin1String("fxmanager_background_removal")) {
        choice("model",{"BiRefNet-lite-F16.gguf","BiRefNet-dynamic-F16.gguf"}); choice("backend",{"cpu","gpu"}); choice("output_mode",{"cutout","grayscale_mask"}); choice("foreground_mode",{"fast_mask","refined_foreground"}); number("preserve_foreground",0,100,true); number("mask_contrast",-100,100,true);
    } else if (filterId == QLatin1String("tfm_halation") || filterId == QLatin1String("fxmanager_halation")) {
        number("threshold",0,1); number("radius",1,200); number("intensity",0,4);
        number("tint",0,1); number("blend",0,1); number("quality",8,64);
        boolean("channel_r"); boolean("channel_g"); boolean("channel_b");
        choice("glow_mode",{"color","channels"});
    } else if (filterId == QLatin1String("tfm_color_range_mask") || filterId == QLatin1String("fxmanager_color_range_mask")) {
        choice("channel",{"gray","r","g","b","hue","saturation"}); number("range_min",0,1); number("range_max",0,1); number("softness",0,0.5); boolean("invert");
    } else if (filterId == QLatin1String("tfm_motion_blur_circular") || filterId == QLatin1String("fxmanager_motion_blur_circular")) {
        number("center_x",-1,2); number("center_y",-1,2); number("angle",0,360);
    } else if (filterId == QLatin1String("tfm_motion_blur_zoom") || filterId == QLatin1String("fxmanager_motion_blur_zoom")) {
        number("center_x",-1,2); number("center_y",-1,2); number("factor",-10,1);
    } else if (filterId == QLatin1String("tfm_focus_blur") || filterId == QLatin1String("fxmanager_focus_blur")) {
        choice("blur_type",{"gaussian","lens"});
        number("blur_radius",0,200);
        number("highlight_factor",0,1);
        number("highlight_threshold_low",0,1);
        number("highlight_threshold_high",0,1);
        choice("shape",{"circle","square","diamond","horizontal","vertical"});
        number("x",-1,2); number("y",-1,2);
        number("radius",0,3);
        number("focus",0,1);
        number("midpoint",0,1);
        number("aspect_ratio",-1,1);
        number("rotation",-180,180);
        boolean("high_quality");
    } else if (filterId == QLatin1String("tfm_color_temperature") || filterId == QLatin1String("fxmanager_color_temperature")) {
        number("temperature", 2000, 12000); number("tint", -100, 100); number("blend", 0, 1); number("preserve_luminance", 0, 1);
    } else if (filterId == QLatin1String("tfm_vibrance") || filterId == QLatin1String("fxmanager_vibrance")) {
        number("vibrance", -100, 100); number("saturation", -100, 100); number("skin_protect", 0, 1); number("protect_highlights", 0, 1); number("blend", 0, 1);
    } else if (filterId == QLatin1String("tfm_kuwahara") || filterId == QLatin1String("fxmanager_kuwahara")) {
        number("size", 1, 12, true); number("iterations", 1, 4, true);
    } else if (filterId == QLatin1String("tfm_lens_flare") || filterId == QLatin1String("fxmanager_lens_flare")) {
        number("threshold", 0, 1); number("length", 0.01, 1); number("decay", 1, 6); number("intensity", 0, 4); number("tint", 0, 1); number("sources", 1, 8, true); number("blend", 0, 1);
    } else if (filterId == QLatin1String("tfm_anamorphic_flare") || filterId == QLatin1String("fxmanager_anamorphic_flare")) {
        number("threshold", 0, 1); number("length", 0.01, 1); number("decay", 0.05, 2); number("aspect", 0.002, 0.2); number("intensity", 0, 4); number("tint", 0, 1); number("sources", 1, 8, true); number("blend", 0, 1);
    } else if (filterId == QLatin1String("tfm_light_rays") || filterId == QLatin1String("fxmanager_light_rays")) {
        number("threshold", 0, 1); number("length", 0.01, 1); number("decay", 0.1, 6); number("intensity", 0, 4); number("blend", 0, 1);
    } else if (filterId == QLatin1String("tfm_light_leaks") || filterId == QLatin1String("fxmanager_light_leaks")) {
        choice("leak_type", {"wash_horizontal", "wash_vertical", "glow_top_left", "glow_bottom_right", "edge_ring", "diagonal"});
        choice("blend", {"screen", "add", "lighten"});
        number("angle", -180, 180); number("scale_x", 0.1, 4); number("scale_y", 0.1, 4); number("hue", -180, 180); number("opacity", 0, 100);
    } else if (filterId == QLatin1String("tfm_light_patch") || filterId == QLatin1String("fxmanager_light_patch")) {
        number("density", 1, 60, true); number("darkness", 0, 1); number("lightness", 0, 4);
    }
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

class BandJob final : public QRunnable
{
public:
    BandJob(std::function<void(int, int)> work, int y0, int y1, QSemaphore *done)
        : m_work(std::move(work)), m_y0(y0), m_y1(y1), m_done(done) { setAutoDelete(true); }
    void run() override { m_work(m_y0, m_y1); m_done->release(); }
private:
    std::function<void(int, int)> m_work;
    int m_y0;
    int m_y1;
    QSemaphore *m_done;
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

} // namespace

FloatRgbaImage readFloatImage(KisPaintDeviceSP device, const QRect &rect)
{
    FloatRgbaImage out;
    if (!device || rect.isEmpty()) return out;
    const KoColorSpace *cs = device->colorSpace();
    const KoColorSpace *working = floatWorkingColorSpace();
    if (!cs || !working) return out;

    const qint64 count = qint64(rect.width()) * rect.height();
    if (count <= 0 || count > 268435456LL ||
        count * cs->pixelSize() > std::numeric_limits<int>::max()) return out;

    // Convert an independent buffer: reading must not change the source device,
    // its profile, or its default pixel. No integer intermediate clips HDR.
    QVector<quint8> raw(int(count * cs->pixelSize()));
    device->readBytes(raw.data(), rect.x(), rect.y(), rect.width(), rect.height());
    out.pixels.resize(int(count * 4));
    if (!cs->convertPixelsTo(raw.constData(),
                            reinterpret_cast<quint8 *>(out.pixels.data()),
                            working, quint32(count),
                            KoColorConversionTransformation::internalRenderingIntent(),
                            KoColorConversionTransformation::internalConversionFlags())) {
        return FloatRgbaImage();
    }
    out.width = rect.width();
    out.height = rect.height();
    out.linearHdr = true;
    return out;
}

bool writeFloatImage(KisPaintDeviceSP device, const FloatRgbaImage &image, const QRect &rect)
{
    if (!device || image.isNull() || rect.isEmpty() || !image.linearHdr) return false;
    if (image.width != rect.width() || image.height != rect.height()) return false;
    const KoColorSpace *cs = device->colorSpace();
    const KoColorSpace *working = floatWorkingColorSpace();
    if (!cs || !working) return false;

    const qint64 count = qint64(rect.width()) * rect.height();
    if (count <= 0 || count > 268435456LL ||
        count * cs->pixelSize() > std::numeric_limits<int>::max()) return false;

    QVector<quint8> raw(int(count * cs->pixelSize()));
    if (!working->convertPixelsTo(reinterpret_cast<const quint8 *>(image.pixels.constData()),
                                 raw.data(), cs, quint32(count),
                                 KoColorConversionTransformation::internalRenderingIntent(),
                                 KoColorConversionTransformation::internalConversionFlags())) return false;
    // Publish only after the complete reverse ICC conversion succeeds.
    device->writeBytes(raw.constData(), rect.x(), rect.y(), rect.width(), rect.height());
    return true;
}

void parallelRows(int rows, const std::function<void(int, int)> &body)
{
    const int workers = workerCount(rows);
    if (workers <= 1) { body(0, rows); return; }
    static QThreadPool pool;
    pool.setMaxThreadCount(workers);
    QSemaphore done(0);
    const int band = (rows + workers - 1) / workers;
    int launched = 0;
    for (int start = 0; start < rows; start += band) {
        pool.start(new BandJob(body, start, std::min(rows, start + band), &done));
        ++launched;
    }
    done.acquire(launched);
    pool.waitForDone();
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
