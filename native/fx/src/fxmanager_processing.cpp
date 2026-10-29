#include "fxmanager_processing.h"

#include <algorithm>
#include <cmath>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSemaphore>
#include <QStandardPaths>
#include <QThreadPool>
#include <QTemporaryFile>
#include <QRunnable>
#include <KoColorSpace.h>

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

void applyFilterDefaults(const QString &filterId, KisFilterConfigurationSP config)
{
    if (!config) return;
    QFile file(settingsReadPath());
    if (!file.open(QIODevice::ReadOnly)) return;
    const QJsonObject values = QJsonDocument::fromJson(file.readAll()).object()
        .value(QStringLiteral("filter_defaults")).toObject().value(filterId).toObject();
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
    if (filterId == QLatin1String("tfm_bloom")) {
        number("threshold",0,1); number("radius",1,64); number("strength",0,2); number("diffusion",0,1); number("softness",0,1);
    } else if (filterId == QLatin1String("tfm_filmgrain")) {
        choice("preset",{"8mm_caffenol","8mm_home_movie","super_8","16mm_broadcast","16mm_indie_cinema","35mm_portra_400","super_35","70mm_cinema","custom"});
        number("amount",0,1); number("size",0.5,8); number("seed",0,999,true); boolean("monochrome");
    } else if (filterId == QLatin1String("tfm_lens_distortion")) {
        choice("mode",{"radial","horizontal"}); number("distortion",-1,1); number("dispersion",0,1); boolean("jitter"); boolean("fit");
    } else if (filterId == QLatin1String("tfm_vignette")) {
        number("factor",0,1); number("feather",0,1); number("corner_roundness",0,1); number("scale_x",0.0001,4); number("scale_y",0.0001,4); number("offset_x",-2,2); number("offset_y",-2,2); number("angle",-180,180);
    } else if (filterId == QLatin1String("tfm_clipboard_color_match")) {
        choice("reference_source",{"clipboard","file"}); number("match_strength",0,1); number("luminance",0,2); number("color_intensity",0,2); number("fade",0,1); number("tone_distribution",0,1); number("tonal_color",0,1); number("color_correlation",0,1); number("gain_limit",1,8); number("shift_limit",0,100); number("variance_floor",0.1,10); boolean("gamut_protection");
    } else if (filterId == QLatin1String("tfm_guided_color_match")) {
        number("match_strength",0,1); number("luminance",0,1); number("chroma",0,2); number("shadow_color",0,1); number("highlight_warmth",0,2); number("neutral_protection",0,1); number("smoothness",0,1);
    } else if (filterId == QLatin1String("tfm_background_removal")) {
        choice("model",{"BiRefNet-lite-F16.gguf","BiRefNet-dynamic-F16.gguf"}); choice("backend",{"cpu","gpu"}); choice("output_mode",{"cutout","grayscale_mask"}); choice("foreground_mode",{"fast_mask","refined_foreground"}); number("preserve_foreground",0,100,true); number("mask_contrast",-100,100,true);
    } else if (filterId == QLatin1String("tfm_color_range_mask")) {
        choice("channel",{"gray","r","g","b","hue","saturation"}); number("range_min",0,1); number("range_max",0,1); number("softness",0,0.5); boolean("invert");
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
    return std::clamp(std::min(configured > 0 ? configured : 1, rows), 1, 48);
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
