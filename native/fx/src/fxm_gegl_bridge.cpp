#include "fxm_gegl_bridge.h"

#include <QCoreApplication>
#include <QCryptographicHash>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLockFile>
#include <QTemporaryDir>
#include <QDir>
#include <QFileInfo>
#include <QMutex>
#include <QMutexLocker>
#include <QSet>
#include <QStandardPaths>
#include <QStringList>

#include <algorithm>
#include <cmath>
#include <cstdint>

#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace fxm_gegl {
namespace {

using gint = int;
using guint = unsigned int;
using gboolean = int;
using gchar = char;
using gdouble = double;
using gpointer = void *;
using GType = std::uintptr_t;

constexpr gboolean kGFalse = 0;
constexpr gboolean kGTrue = 1;

struct GeglRectangle {
    gint x;
    gint y;
    gint width;
    gint height;
};

struct GeglBuffer;
struct GeglNode;
struct GeglColor;
struct GeglConfig;
struct Babl;

struct GTypeClass {
    GType g_type;
};

struct GTypeInstance {
    GTypeClass *g_class;
};

struct GParamSpec {
    GTypeInstance g_type_instance;
    const gchar *name;
    guint flags;
    GType value_type;
    GType owner_type;
};

struct GEnumValue {
    gint value;
    const gchar *value_name;
    const gchar *value_nick;
};

struct GEnumClass {
    GTypeClass g_type_class;
    gint minimum;
    gint maximum;
    guint n_values;
    GEnumValue *values;
};

enum GeglBlitFlags : int {
    GEGL_BLIT_DEFAULT = 0
};

struct DynamicGeglApi {
    bool loaded = false;
    QString prefixPath;

    void (*g_free)(gpointer) = nullptr;
    void (*g_object_unref)(gpointer) = nullptr;
    void (*g_object_set)(gpointer, const gchar *, ...) = nullptr;
    const gchar *(*g_param_spec_get_name)(GParamSpec *) = nullptr;
    gpointer (*g_type_class_ref)(GType) = nullptr;
    void (*g_type_class_unref)(gpointer) = nullptr;
    GEnumValue *(*g_enum_get_value_by_nick)(GEnumClass *, const gchar *) = nullptr;

    const Babl *(*babl_format)(const char *) = nullptr;

    GeglConfig *(*gegl_config)(void) = nullptr;
    void (*gegl_init)(int *, char ***) = nullptr;
    gboolean (*gegl_has_operation)(const gchar *) = nullptr;
    GParamSpec **(*gegl_operation_list_properties)(const gchar *, guint *) = nullptr;
    GParamSpec *(*gegl_operation_find_property)(const gchar *, const gchar *) = nullptr;
    GeglBuffer *(*gegl_buffer_new)(const GeglRectangle *, const Babl *) = nullptr;
    void (*gegl_buffer_set)(GeglBuffer *, const GeglRectangle *, gint, const Babl *, const void *, gint) = nullptr;
    GeglNode *(*gegl_node_new)(void) = nullptr;
    GeglNode *(*gegl_node_new_child)(GeglNode *, const gchar *, ...) = nullptr;
    void (*gegl_node_set)(GeglNode *, const gchar *, ...) = nullptr;
    void (*gegl_node_link)(GeglNode *, GeglNode *) = nullptr;
    gboolean (*gegl_node_connect)(GeglNode *, const gchar *, GeglNode *, const gchar *) = nullptr;
    void (*gegl_node_blit)(GeglNode *, gdouble, const GeglRectangle *, const Babl *, gpointer, gint, int) = nullptr;
    GeglColor *(*gegl_color_new)(const gchar *) = nullptr;
};

QMutex g_geglMutex;
bool g_attemptedInit = false;
bool g_runtimeReady = false;
QString g_statusText;
DynamicGeglApi g_api;

struct RuntimeLayout {
    QString prefix;
    QString binDir;
    QString bablDir;
    QString geglDir;

    bool isValid() const
    {
        return QFileInfo::exists(binDir + QStringLiteral("/libgegl-0.4-0.dll"))
            && QFileInfo::exists(binDir + QStringLiteral("/libbabl-0.1-0.dll"))
            && QFileInfo(bablDir).isDir()
            && QFileInfo(geglDir).isDir();
    }
};

RuntimeLayout probePrefix(const QString &rawPrefix)
{
    RuntimeLayout layout;
    if (rawPrefix.trimmed().isEmpty()) return layout;
    QDir root(QDir::cleanPath(rawPrefix.trimmed()));
    if (!root.exists()) return layout;

    // Allow passing either <prefix> or <prefix>/bin.
    if (root.dirName().compare(QStringLiteral("bin"), Qt::CaseInsensitive) == 0
        && QFileInfo::exists(root.filePath(QStringLiteral("libgegl-0.4-0.dll")))) {
        root.cdUp();
    }

    layout.prefix = QFileInfo(root.absolutePath()).canonicalFilePath();
    root = QDir(layout.prefix);
    layout.binDir = root.filePath(QStringLiteral("bin"));
    layout.bablDir = root.filePath(QStringLiteral("lib/babl-0.1"));
    layout.geglDir = root.filePath(QStringLiteral("lib/gegl-0.4"));
    return layout;
}

RuntimeLayout discoverRuntimeLayout()
{
    QStringList candidates;

    const QString envPrefix = qEnvironmentVariable("TFM_GEGL_PREFIX");
    if (!envPrefix.isEmpty()) candidates << envPrefix;

    const QString envGeglPath = qEnvironmentVariable("GEGL_PATH");
    if (!envGeglPath.isEmpty()) {
        QDir d(envGeglPath);
        if (d.cdUp() && d.cdUp()) candidates << d.absolutePath();
    }

    const QString resDir = fxmanager::resourceDirectory();
    if (!resDir.isEmpty()) {
        candidates << QDir(resDir).filePath(QStringLiteral("TFM/gegl/runtime"));
        candidates << QDir(resDir).filePath(QStringLiteral("TFM/gegl"));
    }

    // Relative to Krita's own installation under Scoop (<scoop>/apps/krita/<ver>/bin -> <scoop>/apps/gimp/current).
    const QString appDir = QCoreApplication::applicationDirPath();
    if (!appDir.isEmpty()) {
        candidates << QDir::cleanPath(appDir + QStringLiteral("/../../../gimp/current"));
        candidates << QDir::cleanPath(appDir + QStringLiteral("/../../gimp/current"));
    }

    const QString scoopEnv = qEnvironmentVariable("SCOOP");
    if (!scoopEnv.isEmpty()) {
        candidates << QDir(scoopEnv).filePath(QStringLiteral("apps/gimp/current"));
    }
    const QString scoopGlobal = qEnvironmentVariable("SCOOP_GLOBAL");
    if (!scoopGlobal.isEmpty()) {
        candidates << QDir(scoopGlobal).filePath(QStringLiteral("apps/gimp/current"));
    }
    candidates << QDir(QDir::homePath()).filePath(QStringLiteral("scoop/apps/gimp/current"));

    for (const QString &exeName : {QStringLiteral("gegl"), QStringLiteral("gimp-3.2"), QStringLiteral("gimp")}) {
        const QString exe = QStandardPaths::findExecutable(exeName);
        if (!exe.isEmpty()) {
            candidates << QFileInfo(exe).absolutePath();
        }
    }

    for (const QFileInfo &driveRoot : QDir::drives()) {
        const QString drivePath = driveRoot.absoluteFilePath();
        candidates << QDir(drivePath).filePath(QStringLiteral("Scoop/apps/gimp/current"));
        candidates << QDir(drivePath).filePath(QStringLiteral("scoop/apps/gimp/current"));
    }

    for (const QString &candidate : candidates) {
        const RuntimeLayout layout = probePrefix(candidate);
        if (layout.isValid()) return layout;
    }
    return {};
}

// Only operation families used by TFM. File codecs pull conflicting host DLLs
// into the process; never scan GIMP's complete operation directory.
QStringList curatedModules(const RuntimeLayout &layout)
{
    QStringList names;
    const QStringList families{QStringLiteral("gegl-core"), QStringLiteral("gegl-common"),
        QStringLiteral("gegl-common-gpl3"), QStringLiteral("gegl-common-cxx"),
        QStringLiteral("gegl-generated"), QStringLiteral("gegl-transformops"),
        QStringLiteral("transformops")};
    for (const QString &family : families) {
        if (QFileInfo::exists(layout.geglDir + '/' + family + QStringLiteral(".dll")))
            names << family + QStringLiteral(".dll");
        for (const QString &name : QDir(layout.geglDir).entryList(
                 {family + QStringLiteral("-x86_64-*.dll")}, QDir::Files, QDir::Name))
            names << name;
    }
    names.removeDuplicates();
    names.sort();
    return names;
}

QByteArray fileHash(const QString &path)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) return {};
    QCryptographicHash hash(QCryptographicHash::Sha256);
    if (!hash.addData(&file)) return {};
    return hash.result().toHex();
}

bool prepareCuratedModules(const RuntimeLayout &layout, QString *pathOut, QString *errorOut)
{
    auto fail = [&](const QString &reason) {
        if (errorOut) *errorOut = QStringLiteral("TFM GEGL isolation: ") + reason;
        return false;
    };
    const QStringList modules = curatedModules(layout);
    for (const QString &required : {QStringLiteral("gegl-core.dll"), QStringLiteral("gegl-common.dll"),
             QStringLiteral("gegl-common-gpl3.dll"), QStringLiteral("gegl-common-cxx.dll"),
             QStringLiteral("gegl-generated.dll"), QStringLiteral("transformops.dll")}) {
        if (!modules.contains(required)) return fail(QStringLiteral("unsupported GIMP module layout: ") + required);
    }
    // Include every runtime dependency in the identity, so updating GIMP creates
    // a fresh generation even when the operation DLL filenames stay unchanged.
    QJsonObject hashes;
    for (const QString &subdir : {QStringLiteral("bin"), QStringLiteral("lib/babl-0.1")}) {
        for (const QString &name : QDir(layout.prefix + '/' + subdir).entryList(
                 {QStringLiteral("*.dll")}, QDir::Files, QDir::Name)) {
            const QString relative = subdir + '/' + name;
            const QByteArray hash = fileHash(layout.prefix + '/' + relative);
            if (hash.isEmpty()) return fail(QStringLiteral("cannot hash ") + relative);
            hashes.insert(relative, QString::fromLatin1(hash));
        }
    }
    for (const QString &name : modules) {
        const QByteArray hash = fileHash(layout.geglDir + '/' + name);
        if (hash.isEmpty()) return fail(QStringLiteral("cannot hash ") + name);
        hashes.insert(QStringLiteral("modules/") + name, QString::fromLatin1(hash));
    }
    const QByteArray manifest = QJsonDocument(hashes).toJson(QJsonDocument::Compact);
    const QString identity = QString::fromLatin1(QCryptographicHash::hash(manifest, QCryptographicHash::Sha256).toHex());
    QString resource = fxmanager::resourceDirectory();
    if (resource.isEmpty()) resource = QStandardPaths::writableLocation(QStandardPaths::CacheLocation);
    const QString root = resource + QStringLiteral("/TFM/gegl/modules-v1");
    if (!QDir().mkpath(root)) return fail(QStringLiteral("cannot create private module root"));
    QLockFile lock(root + QStringLiteral("/prepare.lock"));
    if (!lock.tryLock(10000)) return fail(QStringLiteral("module preparation is busy"));
    const QString generation = root + '/' + identity + QStringLiteral("-layout2");
    const QString destination = generation + QStringLiteral("/modules");
    auto valid = [&]() {
        QFile stored(generation + QStringLiteral("/manifest.json"));
        if (!stored.open(QIODevice::ReadOnly) || stored.readAll() != manifest) return false;
        if (QDir(destination).entryList({QStringLiteral("*.dll")}, QDir::Files, QDir::Name) != modules) return false;
        for (const QString &name : modules)
            if (fileHash(destination + '/' + name) != hashes.value(QStringLiteral("modules/") + name).toString().toLatin1()) return false;
        return true;
    };
    if (QFileInfo::exists(generation)) {
        if (!valid()) return fail(QStringLiteral("private module integrity mismatch; preserve directory for inspection: ") + destination);
    } else {
        QTemporaryDir staging(root + QStringLiteral("/.stage-XXXXXX"));
        if (!staging.isValid()) return fail(QStringLiteral("cannot stage modules"));
        if (!QDir().mkpath(staging.path() + QStringLiteral("/modules"))) return fail(QStringLiteral("cannot stage module directory"));
        for (const QString &name : modules) {
            const QString copy = staging.path() + QStringLiteral("/modules/") + name;
            if (!QFile::copy(layout.geglDir + '/' + name, copy)
                || fileHash(copy) != hashes.value(QStringLiteral("modules/") + name).toString().toLatin1())
                return fail(QStringLiteral("module copy or hash verification failed: ") + name);
        }
        QFile marker(staging.path() + QStringLiteral("/manifest.json"));
        if (!marker.open(QIODevice::WriteOnly) || marker.write(manifest) != manifest.size())
            return fail(QStringLiteral("cannot write module manifest"));
        marker.close();
        // Same-volume rename publishes a complete generation. Old generations
        // remain intact for rollback and are never deleted by the plugin.
        if (!QDir().rename(staging.path(), generation)) return fail(QStringLiteral("cannot publish modules"));
        staging.setAutoRemove(false);
        if (!valid()) return fail(QStringLiteral("published module integrity mismatch"));
    }
    *pathOut = destination;
    return true;
}

bool loadDynamicApi(const RuntimeLayout &layout, QString *errorOut)
{
    if (g_api.loaded) return true;
    if (!layout.isValid()) {
        if (errorOut) *errorOut = QStringLiteral("GEGL runtime directory not found (set TFM_GEGL_PREFIX or install GIMP 3 / TFM/gegl/runtime).");
        return false;
    }

#ifdef Q_OS_WIN
    auto loadDll = [&](const QString &dllName) -> HMODULE {
        const QString fullPath = QDir::toNativeSeparators(QDir(layout.binDir).filePath(dllName));
        HMODULE mod = LoadLibraryExW(
            reinterpret_cast<LPCWSTR>(fullPath.utf16()),
            nullptr,
            LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS | LOAD_LIBRARY_SEARCH_USER_DIRS);
        if (!mod) {
            mod = LoadLibraryExW(
                reinterpret_cast<LPCWSTR>(fullPath.utf16()),
                nullptr,
                LOAD_WITH_ALTERED_SEARCH_PATH);
        }
        return mod;
    };

    HMODULE hGlib = loadDll(QStringLiteral("libglib-2.0-0.dll"));
    HMODULE hGObject = loadDll(QStringLiteral("libgobject-2.0-0.dll"));
    HMODULE hBabl = loadDll(QStringLiteral("libbabl-0.1-0.dll"));
    HMODULE hGegl = loadDll(QStringLiteral("libgegl-0.4-0.dll"));
    if (!hGlib || !hGObject || !hBabl || !hGegl) {
        if (errorOut) {
            *errorOut = QStringLiteral("Failed to load GEGL runtime DLLs from %1").arg(layout.binDir);
        }
        return false;
    }

    auto resolveSym = [&](HMODULE mod, const char *name, auto &target) -> bool {
        FARPROC proc = GetProcAddress(mod, name);
        if (!proc) {
            if (errorOut) *errorOut = QStringLiteral("Missing GEGL symbol: %1").arg(QLatin1String(name));
            return false;
        }
        target = reinterpret_cast<std::decay_t<decltype(target)>>(proc);
        return true;
    };

    if (!resolveSym(hGlib, "g_free", g_api.g_free)
        || !resolveSym(hGObject, "g_object_unref", g_api.g_object_unref)
        || !resolveSym(hGObject, "g_object_set", g_api.g_object_set)
        || !resolveSym(hGObject, "g_param_spec_get_name", g_api.g_param_spec_get_name)
        || !resolveSym(hGObject, "g_type_class_ref", g_api.g_type_class_ref)
        || !resolveSym(hGObject, "g_type_class_unref", g_api.g_type_class_unref)
        || !resolveSym(hGObject, "g_enum_get_value_by_nick", g_api.g_enum_get_value_by_nick)
        || !resolveSym(hBabl, "babl_format", g_api.babl_format)
        || !resolveSym(hGegl, "gegl_config", g_api.gegl_config)
        || !resolveSym(hGegl, "gegl_init", g_api.gegl_init)
        || !resolveSym(hGegl, "gegl_has_operation", g_api.gegl_has_operation)
        || !resolveSym(hGegl, "gegl_operation_list_properties", g_api.gegl_operation_list_properties)
        || !resolveSym(hGegl, "gegl_operation_find_property", g_api.gegl_operation_find_property)
        || !resolveSym(hGegl, "gegl_buffer_new", g_api.gegl_buffer_new)
        || !resolveSym(hGegl, "gegl_buffer_set", g_api.gegl_buffer_set)
        || !resolveSym(hGegl, "gegl_node_new", g_api.gegl_node_new)
        || !resolveSym(hGegl, "gegl_node_new_child", g_api.gegl_node_new_child)
        || !resolveSym(hGegl, "gegl_node_set", g_api.gegl_node_set)
        || !resolveSym(hGegl, "gegl_node_link", g_api.gegl_node_link)
        || !resolveSym(hGegl, "gegl_node_connect", g_api.gegl_node_connect)
        || !resolveSym(hGegl, "gegl_node_blit", g_api.gegl_node_blit)
        || !resolveSym(hGegl, "gegl_color_new", g_api.gegl_color_new)) {
        return false;
    }

    g_api.prefixPath = layout.prefix;
    g_api.loaded = true;
    return true;
#else
    if (errorOut) *errorOut = QStringLiteral("GEGL dynamic loader is only supported on Windows.");
    return false;
#endif
}

bool checkOperationProperties(const char *opName,
                              std::initializer_list<const char *> expectedProps,
                              QString *errorOut)
{
    if (!g_api.gegl_has_operation(opName)) {
        if (errorOut) {
            *errorOut = QStringLiteral("Missing GEGL operation: %1").arg(QString::fromLatin1(opName));
        }
        return false;
    }

    guint count = 0;
    GParamSpec **specs = g_api.gegl_operation_list_properties(opName, &count);
    QSet<QString> names;
    for (guint i = 0; i < count; ++i) {
        if (specs && specs[i]) {
            names.insert(QString::fromUtf8(g_api.g_param_spec_get_name(specs[i])));
        }
    }
    if (specs) {
        g_api.g_free(specs);
    }

    for (const char *prop : expectedProps) {
        const QString propName = QString::fromLatin1(prop);
        if (!names.contains(propName)) {
            if (errorOut) {
                *errorOut = QStringLiteral("GEGL operation %1 is missing property '%2'")
                                .arg(QString::fromLatin1(opName), propName);
            }
            return false;
        }
    }
    return true;
}

bool ensureRuntimeUnlocked()
{
    if (g_attemptedInit) {
        return g_runtimeReady;
    }
    g_attemptedInit = true;

    const RuntimeLayout layout = discoverRuntimeLayout();
    QString err;
#ifdef Q_OS_WIN
    // GEGL has process-global registration and no supported initialized query.
    // Even a loaded but apparently idle foreign instance cannot be safely owned.
    if (GetModuleHandleW(L"libgegl-0.4-0.dll")) {
        g_statusText = QStringLiteral("TFM GEGL conflict: GEGL is already loaded by another component; restart without that component.");
        return false;
    }
#endif
    if (!qEnvironmentVariableIsEmpty("GEGL_PATH") || !qEnvironmentVariableIsEmpty("BABL_PATH")) {
        g_statusText = QStringLiteral("TFM GEGL conflict: external GEGL_PATH or BABL_PATH is set; isolated initialization requires these to be unset.");
        return false;
    }
    QString modulePath;
    if (!layout.isValid() || !prepareCuratedModules(layout, &modulePath, &err)) {
        g_statusText = err.isEmpty() ? QStringLiteral("Compatible GIMP GEGL runtime not found.") : err;
        return false;
    }
    if (!loadDynamicApi(layout, &err)) {
        g_statusText = err;
        g_runtimeReady = false;
        return false;
    }

    // GModule later reopens operation DLLs with legacy LoadLibrary semantics.
    // Preload with explicit dependency search flags and retain the references,
    // avoiding a process-wide PATH or SetDefaultDllDirectories change.
#ifdef Q_OS_WIN
    struct SearchDirectory {
        DLL_DIRECTORY_COOKIE cookie;
        ~SearchDirectory() { if (cookie) RemoveDllDirectory(cookie); }
    } search{AddDllDirectory(reinterpret_cast<PCWSTR>(QDir::toNativeSeparators(layout.binDir).utf16()))};
    if (!search.cookie) {
        g_statusText = QStringLiteral("TFM GEGL could not establish temporary DLL dependency search directory.");
        return false;
    }
    for (const QString &name : curatedModules(layout)) {
        const QString full = QDir::toNativeSeparators(modulePath + '/' + name);
        if (!LoadLibraryExW(reinterpret_cast<LPCWSTR>(full.utf16()), nullptr,
                LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS | LOAD_LIBRARY_SEARCH_USER_DIRS)) {
            g_statusText = QStringLiteral("TFM GEGL module dependency load failed: %1 (Windows %2)").arg(name).arg(GetLastError());
            return false;
        }
    }
#endif
    // Temporary initialization environment; GEGL retains its module database.
    // This mutex serializes TFM callers. Foreign GEGL consumers must initialize
    // before TFM (and are rejected above); concurrent foreign initialization is
    // unsupported because GEGL and the environment are process-global.
    qputenv("BABL_PATH", QDir::toNativeSeparators(layout.bablDir).toUtf8());
    qputenv("GEGL_PATH", QDir::toNativeSeparators(modulePath).toUtf8());

    // GPL operations are selected while modules are registered, during gegl_init.
    // Krita and this plugin are GPL3; setting this afterwards is too late.
    if (GeglConfig *cfg = g_api.gegl_config()) {
        g_api.g_object_set(cfg, "application-license", "GPL3", "use-opencl", kGFalse, nullptr);
    }
    int argc = 0;
    char **argv = nullptr;
    g_api.gegl_init(&argc, &argv);
    qunsetenv("GEGL_PATH");
    qunsetenv("BABL_PATH");

    if (GeglConfig *cfg = g_api.gegl_config()) {
        g_api.g_object_set(cfg, "use-opencl", kGFalse, nullptr);
    }

    if (!checkOperationProperties("gegl:buffer-source", {"buffer"}, &err)
        || !checkOperationProperties("gegl:motion-blur-circular", {"center-x", "center-y", "angle"}, &err)
        || !checkOperationProperties("gegl:motion-blur-zoom", {"center-x", "center-y", "factor"}, &err)
        || !checkOperationProperties("gegl:focus-blur",
                                     {"blur-type", "blur-radius", "highlight-factor",
                                      "highlight-threshold-low", "highlight-threshold-high",
                                      "shape", "x", "y", "radius", "focus",
                                      "midpoint", "aspect-ratio", "rotation", "high-quality"},
                                     &err)
        || !checkOperationProperties("gegl:vignette",
                                     {"shape", "x", "y", "radius", "softness",
                                      "gamma", "proportion", "squeeze", "rotation"},
                                     &err)
        || !checkOperationProperties("gegl:variable-blur", {"radius", "high-quality", "linear-mask"}, &err)
        || !checkOperationProperties("gegl:lens-blur",
                                     {"radius", "highlight-factor", "highlight-threshold-low",
                                      "highlight-threshold-high", "clip", "linear-mask"},
                                     &err)) {
        g_statusText = err;
        g_runtimeReady = false;
        return false;
    }

    g_runtimeReady = true;
    g_statusText = QStringLiteral("GEGL 0.4 ready (OpenCL off)");
    return true;
}

bool resolveEnumNick(const char *opName, const char *propName, const QString &nick, gint *valueOut)
{
    GParamSpec *spec = g_api.gegl_operation_find_property(opName, propName);
    if (!spec || !spec->value_type) return false;
    GEnumClass *enumClass = static_cast<GEnumClass *>(g_api.g_type_class_ref(spec->value_type));
    if (!enumClass) return false;
    const QByteArray nickUtf8 = nick.toUtf8();
    const GEnumValue *ev = g_api.g_enum_get_value_by_nick(enumClass, nickUtf8.constData());
    const bool found = (ev != nullptr);
    if (found && valueOut) {
        *valueOut = ev->value;
    }
    g_api.g_type_class_unref(enumClass);
    return found;
}

bool applyParameters(GeglNode *node,
                     const QByteArray &opUtf8,
                     const ParamMap &params,
                     QString *errorOut)
{
    for (auto it = params.cbegin(); it != params.cend(); ++it) {
        const QByteArray keyUtf8 = it.key().toUtf8();
        const QVariant &val = it.value();

        if (!g_api.gegl_operation_find_property(opUtf8.constData(), keyUtf8.constData())) {
            if (errorOut) {
                *errorOut = QStringLiteral("Unknown GEGL property '%1' on %2")
                                .arg(it.key(), QString::fromUtf8(opUtf8));
            }
            return false;
        }

        switch (val.type()) {
        case QVariant::Bool:
            g_api.gegl_node_set(node, keyUtf8.constData(), val.toBool() ? kGTrue : kGFalse, nullptr);
            break;
        case QVariant::Int:
        case QVariant::LongLong:
            g_api.gegl_node_set(node, keyUtf8.constData(), static_cast<gint>(val.toInt()), nullptr);
            break;
        case QVariant::String: {
            gint enumVal = 0;
            if (resolveEnumNick(opUtf8.constData(), keyUtf8.constData(), val.toString(), &enumVal)) {
                g_api.gegl_node_set(node, keyUtf8.constData(), enumVal, nullptr);
            } else {
                const QByteArray strUtf8 = val.toString().toUtf8();
                g_api.gegl_node_set(node, keyUtf8.constData(), strUtf8.constData(), nullptr);
            }
            break;
        }
        default:
            g_api.gegl_node_set(node, keyUtf8.constData(), static_cast<gdouble>(val.toDouble()), nullptr);
            break;
        }
    }
    return true;
}

} // namespace

bool ensureRuntime(QString *errorOut)
{
    QMutexLocker lock(&g_geglMutex);
    const bool ok = ensureRuntimeUnlocked();
    if (!ok && errorOut) {
        *errorOut = g_statusText;
    }
    return ok;
}

QString runtimeStatusText()
{
    QMutexLocker lock(&g_geglMutex);
    ensureRuntimeUnlocked();
    return g_statusText;
}

QImage renderRgba8(const QImage &source,
                   const QString &operation,
                   const ParamMap &params,
                   QString *errorOut)
{
    if (source.isNull() || source.width() <= 0 || source.height() <= 0) {
        if (errorOut) *errorOut = QStringLiteral("Source image is empty.");
        return QImage();
    }

    QMutexLocker lock(&g_geglMutex);
    if (!ensureRuntimeUnlocked()) {
        if (errorOut) *errorOut = g_statusText;
        return QImage();
    }

    const QImage rgbaInput =
        (source.format() == QImage::Format_RGBA8888)
            ? source
            : source.convertToFormat(QImage::Format_RGBA8888);

    const GeglRectangle extent{0, 0, rgbaInput.width(), rgbaInput.height()};
    const Babl *format = g_api.babl_format("R'G'B'A u8");
    if (!format) {
        if (errorOut) *errorOut = QStringLiteral("Failed to resolve babl format \"R'G'B'A u8\".");
        return QImage();
    }

    GeglBuffer *inputBuffer = g_api.gegl_buffer_new(&extent, format);
    if (!inputBuffer) {
        if (errorOut) *errorOut = QStringLiteral("gegl_buffer_new failed.");
        return QImage();
    }

    g_api.gegl_buffer_set(inputBuffer, &extent, 0, format, rgbaInput.constBits(), rgbaInput.bytesPerLine());

    GeglNode *graph = g_api.gegl_node_new();
    GeglNode *srcNode = g_api.gegl_node_new_child(
        graph, "operation", "gegl:buffer-source", "buffer", inputBuffer, nullptr);
    const QByteArray opUtf8 = operation.toUtf8();
    GeglNode *effectNode = g_api.gegl_node_new_child(
        graph, "operation", opUtf8.constData(), nullptr);

    if (!srcNode || !effectNode || !applyParameters(effectNode, opUtf8, params, errorOut)) {
        g_api.g_object_unref(graph);
        g_api.g_object_unref(inputBuffer);
        return QImage();
    }

    g_api.gegl_node_link(srcNode, effectNode);

    QImage output(rgbaInput.size(), QImage::Format_RGBA8888);
    g_api.gegl_node_blit(
        effectNode, 1.0, &extent, format, output.bits(), output.bytesPerLine(), GEGL_BLIT_DEFAULT);

    g_api.g_object_unref(graph);
    g_api.g_object_unref(inputBuffer);
    return output;
}

fxmanager::FloatRgbaImage renderOperationRegion(const fxmanager::FloatRgbaImage &source,
                                                const QRect &readRect,
                                                const QRect &targetRect,
                                                const QString &operation,
                                                const ParamMap &params,
                                                QString *errorOut)
{
    fxmanager::FloatRgbaImage out;
    const bool circular = operation == QLatin1String("gegl:motion-blur-circular");
    const bool zoom = operation == QLatin1String("gegl:motion-blur-zoom");
    if (source.isNull() || readRect.isEmpty() || targetRect.isEmpty()
        || source.width != readRect.width() || source.height != readRect.height()
        || !readRect.contains(targetRect) || (!circular && !zoom)) {
        if (errorOut) *errorOut = QStringLiteral("Invalid finite motion region or unsupported operation.");
        return out;
    }
    const qint64 count = qint64(targetRect.width()) * targetRect.height();
    if (count <= 0 || count > 64LL * 1024 * 1024) {
        if (errorOut) *errorOut = QStringLiteral("Motion output exceeds 64M pixels."); return out;
    }
    out.width=targetRect.width(); out.height=targetRect.height(); out.linearHdr=source.linearHdr; out.pixels.resize(int(count*4));
    const double cx = params.contains(QStringLiteral("absolute-center-x"))
        ? params.value(QStringLiteral("absolute-center-x")).toDouble()
        : readRect.x() + source.width * params.value(QStringLiteral("center-x")).toDouble();
    const double cy = params.contains(QStringLiteral("absolute-center-y"))
        ? params.value(QStringLiteral("absolute-center-y")).toDouble()
        : readRect.y() + source.height * params.value(QStringLiteral("center-y")).toDouble();
    const double angle = std::clamp(params.value(QStringLiteral("angle"), 20.0).toDouble(), 0.0, 360.0);
    const double factor = std::clamp(params.value(QStringLiteral("factor"), 0.1).toDouble(), -10.0, 1.0);
    if (!std::isfinite(cx) || !std::isfinite(cy) || !std::isfinite(angle) || !std::isfinite(factor)) return {};
    const double extent = angle * 3.14159265358979323846 / 360.0;
    // Sampling count and positions are independent of the host's requested patch.
    // Zoom deliberately excludes t=1, so even factor=1 has finite inverse support.
    const int samples = (circular ? angle == 0.0 : factor == 0.0) ? 1 : 200;
    double cosine[200], sine[200];
    if (circular) for (int i = 0; i < samples; ++i) {
        const double a = samples == 1 ? 0.0 : (-1.0 + 2.0 * i / (samples-1)) * extent;
        cosine[i] = std::cos(a);
        sine[i] = std::sin(a);
    }
    const float *src = source.pixels.constData();
    auto sample = [&](double gx, double gy, double *rgba) {
        const double localX = gx - readRect.x(), localY = gy - readRect.y();
        const int ix = int(std::floor(localX)), iy = int(std::floor(localY));
        const double tx = localX - ix, ty = localY - iy;
        for (int v = 0; v < 2; ++v) for (int u = 0; u < 2; ++u) {
            const int x = ix + u, y = iy + v;
            if (x < 0 || y < 0 || x >= source.width || y >= source.height) continue;
            const double weight = (u ? tx : 1.0-tx) * (v ? ty : 1.0-ty);
            const float *pixel = src + (y * source.width + x) * 4;
            const double alpha = pixel[3];
            rgba[3] += weight * alpha;
            if (alpha != 0.0) for (int c = 0; c < 3; ++c) rgba[c] += weight * alpha * pixel[c];
        }
    };
    for (int y = 0; y < out.height; ++y) for (int x = 0; x < out.width; ++x) {
        const double px = targetRect.x() + x, py = targetRect.y() + y;
        double rgba[4] = {};
        for (int i = 0; i < samples; ++i) {
            double sx = px, sy = py;
            if (circular && samples > 1) {
                const double dx = px-cx, dy = py-cy;
                sx = cx + dx * cosine[i] - dy * sine[i];
                sy = cy + dx * sine[i] + dy * cosine[i];
            } else if (!circular) {
                const double scale = 1.0 - double(i) / samples * factor;
                sx = cx + (px-cx) * scale;
                sy = cy + (py-cy) * scale;
            }
            sample(sx, sy, rgba);
        }
        float *pixel = out.pixels.data() + (y * out.width + x) * 4;
        pixel[3] = float(rgba[3] / samples);
        for (int c = 0; c < 3; ++c) pixel[c] = rgba[3] != 0.0 ? float(rgba[c] / rgba[3]) : 0.0f;
    }
    return out;
}
fxmanager::FloatRgbaImage renderFocusBlurRegion(const fxmanager::FloatRgbaImage &source,
                                                const QRect &readRect,
                                                const QRect &targetRect,
                                                const QRect &refFrame,
                                                const FocusBlurParams &params,
                                                QString *errorOut)
{
    fxmanager::FloatRgbaImage out;
    if (source.isNull() || readRect.isEmpty() || targetRect.isEmpty() || refFrame.isEmpty()
        || source.width != readRect.width() || source.height != readRect.height()) {
        if (errorOut) *errorOut = QStringLiteral("Invalid region geometry for GEGL focus-blur.");
        return out;
    }

    const qint64 inputCount = qint64(readRect.width()) * readRect.height();
    const qint64 outputCount = qint64(targetRect.width()) * targetRect.height();
    if (inputCount > 64LL * 1024 * 1024 || outputCount > 64LL * 1024 * 1024
        || !readRect.contains(targetRect)) {
        if (errorOut) *errorOut = QStringLiteral("Focus finite support exceeds the 64M pixel limit or excludes the output.");
        return out;
    }
    QMutexLocker lock(&g_geglMutex);
    if (!ensureRuntimeUnlocked()) {
        if (errorOut) *errorOut = g_statusText;
        return out;
    }

    const Babl *format = g_api.babl_format(source.linearHdr ? "RGBA float" : "R'G'B'A float");
    if (!format) {
        if (errorOut) *errorOut = QStringLiteral("Failed to resolve float babl format.");
        return out;
    }

    const GeglRectangle srcExtent{readRect.x(), readRect.y(), readRect.width(), readRect.height()};
    const GeglRectangle dstExtent{targetRect.x(), targetRect.y(), targetRect.width(), targetRect.height()};

    GeglBuffer *inputBuffer = g_api.gegl_buffer_new(&srcExtent, format);
    if (!inputBuffer) {
        if (errorOut) *errorOut = QStringLiteral("gegl_buffer_new failed.");
        return out;
    }

    // GEGL's Lens path may divide hidden RGB by zero. Normalize only invisible
    // input RGB in a detached copy; never mutate the caller's shared pixels.
    QVector<float> inputPixels = source.pixels;
    float *rgba = inputPixels.data();
    for (qint64 i = 0; i < inputCount; ++i) {
        if (rgba[i * 4 + 3] == 0.0f) {
            rgba[i * 4] = rgba[i * 4 + 1] = rgba[i * 4 + 2] = 0.0f;
        }
    }
    g_api.gegl_buffer_set(
        inputBuffer,
        &srcExtent,
        0,
        format,
        inputPixels.constData(),
        source.width * 4 * int(sizeof(float)));

    // The analytic mask uses the saved global frame even outside that frame.
    // Gaussian levels use finite FIR support; Lens callers use canonical 64px cores.
    GeglNode *graph = g_api.gegl_node_new();

    GeglNode *srcNode = g_api.gegl_node_new_child(
        graph, "operation", "gegl:buffer-source", "buffer", inputBuffer, nullptr);
    // Globally defined, configuration-only focus mask.
    const Babl *maskFormat = g_api.babl_format("Y float");
    QVector<float> mask(readRect.width()*readRect.height());
    const double cx = int(refFrame.x()+refFrame.width()*params.x);
    const double cy = int(refFrame.y()+refFrame.height()*params.y);
    const double scale = params.aspectRatio < 0 ? std::max(1.0+params.aspectRatio,1e-6) : 1.0/std::max(1.0-params.aspectRatio,1e-6);
    const double length = refFrame.width()/2.0/std::max(1.0,scale);
    const double outer = params.radius;
    const double inner = outer*params.focus;
    const double transition = std::max(outer-inner,0.0001);
    const double gamma = params.midpoint>=1?1000:std::min(1000.0,-0.6931471805599453/std::log(std::max(params.midpoint,1e-6)));
    const double angle = -params.rotation*3.14159265358979323846/180;
    for(int y=0;y<readRect.height();++y) for(int x=0;x<readRect.width();++x) {
        const double dx=readRect.x()+x-cx,dy=readRect.y()+y-cy;
        const double u=std::abs((std::cos(angle)*dx-std::sin(angle)*dy)/scale);
        const double v=std::abs(std::sin(angle)*dx+std::cos(angle)*dy);
        double d=std::hypot(u,v);
        if(params.shape=="square")d=std::max(u,v);
        if(params.shape=="diamond")d=u+v;
        if(params.shape=="horizontal")d=v;
        if(params.shape=="vertical")d=u;
        // Upstream focus-blur: black center (sharp), white exterior (max blur).
        mask[y*readRect.width()+x]=float(std::pow(std::clamp((d/length-inner)/transition,0.0,1.0),gamma));
    }
    GeglBuffer *maskBuffer=g_api.gegl_buffer_new(&srcExtent,maskFormat);
    if (!maskBuffer) {
        if (errorOut) *errorOut = QStringLiteral("Failed to allocate focus mask.");
        g_api.g_object_unref(graph);
        g_api.g_object_unref(inputBuffer);
        return out;
    }
    g_api.gegl_buffer_set(maskBuffer,&srcExtent,0,maskFormat,mask.constData(),readRect.width()*int(sizeof(float)));
    GeglNode *vignetteNode=g_api.gegl_node_new_child(graph,"operation","gegl:buffer-source","buffer",maskBuffer,nullptr);
    const bool isLens = (params.blurType == QLatin1String("lens"));
    const char *blurOp = isLens ? "gegl:lens-blur" : "gegl:variable-blur";
    GeglNode *blurNode = g_api.gegl_node_new_child(
        graph,
        "operation", blurOp,
        "linear-mask", kGTrue,
        nullptr);


    if (!srcNode || !vignetteNode || !blurNode) {
        if (errorOut) *errorOut = QStringLiteral("Failed to construct GEGL focus-blur nodes.");
        g_api.g_object_unref(graph);
        g_api.g_object_unref(inputBuffer);
        g_api.g_object_unref(maskBuffer);
        return out;
    }

    if (isLens) {
        g_api.gegl_node_set(
            blurNode,
            "clip", kGTrue,
            "radius", gdouble(params.blurRadius),
            "highlight-factor", gdouble(params.highlightFactor),
            "highlight-threshold-low", gdouble(params.highlightThresholdLow),
            "highlight-threshold-high", gdouble(params.highlightThresholdHigh),
            nullptr);
    } else {
        g_api.gegl_node_set(
            blurNode,
            "radius", gdouble(params.blurRadius),
            "high-quality", params.highQuality ? kGTrue : kGFalse,
            nullptr);
    }

    if(isLens) {
        g_api.gegl_node_link(srcNode,blurNode);
        g_api.gegl_node_connect(vignetteNode,"output",blurNode,"aux");
    } else {
        // Explicitly finite FIR pyramid; intentionally differs from GEGL auto/IIR.
        const int levels=params.highQuality?16:int(std::ceil(std::clamp(std::log2(std::max(params.blurRadius,1e-6))+3,2.0,16.0)));
        blurNode=g_api.gegl_node_new_child(graph,"operation","gegl:piecewise-blend","levels",levels,"gamma",double(1.5),"linear-mask",kGTrue,nullptr);
        g_api.gegl_node_link(vignetteNode,blurNode);
        g_api.gegl_node_connect(srcNode,"output",blurNode,"aux1");
        gint fir=0; resolveEnumNick("gegl:gaussian-blur","filter","fir",&fir);
        for(int i=1;i<levels;++i) {
            const double sigma=params.blurRadius*std::pow(double(i)/(levels-1),1.5);
            GeglNode *g=g_api.gegl_node_new_child(graph,"operation","gegl:gaussian-blur","std-dev-x",sigma,"std-dev-y",sigma,"filter",fir,nullptr);
            g_api.gegl_node_link(srcNode,g);
            QByteArray pad="aux"+QByteArray::number(i+1);
            g_api.gegl_node_connect(g,"output",blurNode,pad.constData());
        }
    }
    out.width = targetRect.width();
    out.height = targetRect.height();
    out.linearHdr = source.linearHdr;
    out.pixels.resize(out.width * out.height * 4);

    // Lens blur scatters/accumulates samples within the requested ROI. Use a
    // stable ROI as well as a stable input extent, then extract the patch.
    const GeglRectangle renderExtent = dstExtent;
    QVector<float> rendered(renderExtent.width * renderExtent.height * 4);
    g_api.gegl_node_blit(
        blurNode,
        1.0,
        &renderExtent,
        format,
        rendered.data(),
        renderExtent.width * 4 * int(sizeof(float)),
        GEGL_BLIT_DEFAULT);
    for (int y = 0; y < out.height; ++y) {
        const int offset = ((targetRect.y() - renderExtent.y + y) * renderExtent.width
                            + targetRect.x() - renderExtent.x) * 4;
        std::copy_n(rendered.constData() + offset, out.width * 4,
                    out.pixels.data() + y * out.width * 4);
    }

    g_api.g_object_unref(graph);
    g_api.g_object_unref(inputBuffer);
    g_api.g_object_unref(maskBuffer);
    // Zero coverage has no visible RGB. GEGL can leave 0/0 here in HDR Lens;
    // positive-alpha nonfinite values remain visible to callers and regressions.
    float *result = out.pixels.data();
    for (qint64 i = 0; i < outputCount; ++i) {
        if (result[i * 4 + 3] == 0.0f) {
            result[i * 4] = result[i * 4 + 1] = result[i * 4 + 2] = 0.0f;
        }
    }
    return out;
}

} // namespace fxm_gegl
