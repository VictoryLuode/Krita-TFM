#include "tfm_birefnet.h"

#include "tfm_processing.h"

#include <QDir>
#include <QFileInfo>
#include <QMutexLocker>
#include <QStandardPaths>

#include <algorithm>
#include <stdexcept>

#ifdef _WIN32
#include <windows.h>
#endif

#include <ggml-backend.h>

namespace {

QString modelsDirectory()
{
    const QString resource = tfm::resourceDirectory();
    const QStringList roots = resource.isEmpty()
        ? QStringList{QStandardPaths::writableLocation(QStandardPaths::AppDataLocation)}
        : QStringList{resource};
    for (const QString &root : roots) {
        if (root.isEmpty()) continue;
        const QString canonical = QDir(root).filePath(QStringLiteral("TFM/background-removal/models"));
        if (QFileInfo(canonical).isDir()
            && !QDir(canonical).entryList({QStringLiteral("BiRefNet-*.gguf")}, QDir::Files).isEmpty()) {
            return canonical;
        }
        // Read-only compatibility for the archived fxmanager layout.
        const QString fxm = QDir(root).filePath(QStringLiteral("pykrita/fxmanager/filters/background-removal/models"));
        if (QFileInfo(fxm).isDir()) return fxm;
        // Read-only compatibility for files installed by the previous candidate.
        const QString legacy = QDir(root).filePath(QStringLiteral("pykrita/vision_tools/models/birefnet"));
        if (QFileInfo(legacy).isDir()) return legacy;
        const QString old = QDir(root).filePath(QStringLiteral("FilterManager/models/birefnet"));
        if (QFileInfo(old).isDir()) return old;
    }
    return {};
}

QStringList modelFiles()
{
    const QDir dir(modelsDirectory());
    QStringList files = dir.entryList({QStringLiteral("BiRefNet-lite-F16.gguf"),
                                       QStringLiteral("BiRefNet-dynamic-F16.gguf")},
                                      QDir::Files, QDir::Name);
    return files;
}

} // namespace

BirefnetRuntime &BirefnetRuntime::instance()
{
    static BirefnetRuntime runtime;
    return runtime;
}

BirefnetRuntime::BirefnetRuntime()
    : m_modelName(QStringLiteral("BiRefNet-lite-F16.gguf"))
{
}

BirefnetRuntime::~BirefnetRuntime() = default;

QStringList BirefnetRuntime::availableModels() const
{
    return modelFiles();
}

QString BirefnetRuntime::modelName() const
{
    QMutexLocker lock(&m_mutex);
    return m_modelName;
}

void BirefnetRuntime::setModelName(const QString &name)
{
    QMutexLocker lock(&m_mutex);
    if (name != QStringLiteral("BiRefNet-lite-F16.gguf")
        && name != QStringLiteral("BiRefNet-dynamic-F16.gguf")) {
        return;
    }
    if (m_modelName == name) return;
    m_modelName = name;
    m_model.reset();
}

visp::backend_type BirefnetRuntime::backend() const
{
    QMutexLocker lock(&m_mutex);
    return m_backendType;
}

bool BirefnetRuntime::backendAvailable(visp::backend_type type) const
{
    QMutexLocker lock(&m_mutex);
    return visp::backend_is_available(type);
}

QString BirefnetRuntime::runtimeDirectory() const
{
    const QString resource = tfm::resourceDirectory();
    const QString root = resource.isEmpty()
        ? QStandardPaths::writableLocation(QStandardPaths::AppDataLocation)
        : resource;
    if (root.isEmpty()) return QString();
    const QString canonical = QDir(root).filePath(QStringLiteral("TFM/background-removal/runtime"));
    if (QFileInfo(canonical).isDir()) return canonical;
    // Read-only compatibility for the archived fxmanager layout.
    const QString fxm = QDir(root).filePath(QStringLiteral("pykrita/fxmanager/filters/background-removal/runtime"));
    return QFileInfo(fxm).isDir() ? fxm : canonical;
}

bool BirefnetRuntime::loadVulkanBackendLocked(const QString &absoluteFile, QString *error)
{
    const QFileInfo file(absoluteFile);
    if (!file.isAbsolute() || !file.isFile() || file.fileName() != QStringLiteral("ggml-vulkan.dll")) {
        if (error) *error = QStringLiteral("Expected an existing absolute ggml-vulkan.dll path");
        return false;
    }
#ifdef _WIN32
    if (!preloadVulkanDependenciesLocked(file.absolutePath(), error)) return false;
#endif
    const QByteArray path = file.canonicalFilePath().toUtf8();
    const auto reg = ggml_backend_load(path.constData());
    if (!reg || QString::fromUtf8(ggml_backend_reg_name(reg)) != QStringLiteral("Vulkan")) {
        if (error) *error = QStringLiteral("Could not register the supplied Vulkan backend");
        return false;
    }
    if (ggml_backend_reg_dev_count(reg) == 0) {
        if (error) *error = QStringLiteral("Vulkan backend loaded but no compatible GPU is available");
        return false;
    }
    return true;
}

bool BirefnetRuntime::preloadVulkanDependenciesLocked(const QString &directory, QString *error)
{
#ifdef _WIN32
    if (!m_vulkanDependencies.empty()) return true;

    const QStringList names{
        QStringLiteral("libunwind.dll"),
        QStringLiteral("libc++.dll"),
        QStringLiteral("ggml-base.dll")};
    std::vector<HMODULE> loaded;
    loaded.reserve(names.size());
    for (const QString &name : names) {
        const QString path = QDir(directory).filePath(name);
        const QFileInfo file(path);
        if (!file.isFile()) {
            if (error) *error = QStringLiteral("Vulkan runtime dependency is missing: %1").arg(path);
            for (HMODULE handle : loaded) FreeLibrary(handle);
            return false;
        }
        HMODULE handle = LoadLibraryExW(
            reinterpret_cast<LPCWSTR>(file.absoluteFilePath().utf16()),
            nullptr,
            LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
        if (!handle) {
            const DWORD code = GetLastError();
            if (error) {
                *error = QStringLiteral("Could not load Vulkan runtime dependency %1 (Windows error %2)")
                    .arg(path)
                    .arg(code);
            }
            for (HMODULE loadedHandle : loaded) FreeLibrary(loadedHandle);
            return false;
        }
        loaded.push_back(handle);
    }
    m_vulkanDependencies = std::move(loaded);
    return true;
#else
    Q_UNUSED(directory)
    if (error) *error = QStringLiteral("The Vulkan runtime loader is only implemented on Windows");
    return false;
#endif
}

bool BirefnetRuntime::loadVulkanBackend(const QString &absoluteFile, QString *error)
{
    QMutexLocker lock(&m_mutex);
    return loadVulkanBackendLocked(absoluteFile, error);
}

bool BirefnetRuntime::setBackend(visp::backend_type type, QString *error)
{
    QMutexLocker lock(&m_mutex);
    if (type == m_backendType && m_backend) return true;
    m_backend.reset();
    m_model.reset();
    m_backendType = type;
    return ensureBackend(error);
}

QString BirefnetRuntime::backendDescription() const
{
    QMutexLocker lock(&m_mutex);
    if (!m_backend || !m_backend->device) return {};
    return QString::fromUtf8(ggml_backend_dev_description(m_backend->device));
}

QString BirefnetRuntime::modelPath() const
{
    return QDir(modelsDirectory()).filePath(m_modelName);
}

bool BirefnetRuntime::ensureBackend(QString *error)
{
    if (m_backend) return true;
    try {
        if (m_backendType == visp::backend_type::gpu) {
            const QString vulkan = QDir(runtimeDirectory()).filePath(QStringLiteral("ggml-vulkan.dll"));
            if (!QFileInfo(vulkan).isFile() || !loadVulkanBackendLocked(vulkan, error)) return false;
        }
        m_backend = std::make_unique<visp::backend_device>(visp::backend_init(m_backendType));
        if (!m_backend || !m_backend->device) {
            if (error) *error = QStringLiteral("GPU backend initialized without a usable device");
            m_backend.reset();
            return false;
        }
        return true;
    } catch (const std::exception &e) {
        if (error) *error = QString::fromUtf8(e.what());
        return false;
    }
}

bool BirefnetRuntime::ensureModel(QString *error)
{
    if (m_model) return true;
    QString path = modelPath();
    if (!QFileInfo(path).isFile()) {
        const QStringList models = modelFiles();
        if (!models.isEmpty()) {
            m_modelName = models.constFirst();
            path = modelPath();
        } else {
            if (error) *error = QStringLiteral("BiRefNet model not found: %1").arg(path);
            return false;
        }
    }
    try {
        const QByteArray encodedPath = path.toUtf8();
        m_model = std::make_unique<visp::birefnet_model>(
            visp::birefnet_load_model(encodedPath.constData(), *m_backend));
        return true;
    } catch (const std::exception &e) {
        if (error) *error = QString::fromUtf8(e.what());
        m_model.reset();
        return false;
    }
}

visp::image_data BirefnetRuntime::removeBackground(visp::image_view image,
                                                   const QString &modelName,
                                                   visp::backend_type backendType)
{
    QMutexLocker lock(&m_mutex);
    if (modelName != QStringLiteral("BiRefNet-lite-F16.gguf")
        && modelName != QStringLiteral("BiRefNet-dynamic-F16.gguf")) {
        throw std::runtime_error("Unsupported BiRefNet model");
    }
    if (m_modelName != modelName) {
        m_modelName = modelName;
        m_model.reset();
    }
    if (backendType != m_backendType) {
        m_backend.reset();
        m_backendType = backendType;
        m_model.reset();
    }
    QString error;
    if (!ensureBackend(&error)) throw std::runtime_error(error.toStdString());
    if (!ensureModel(&error)) throw std::runtime_error(error.toStdString());

    visp::image_data resized;
    visp::image_view input = image;
    if (m_model->params.image_size == -1 && m_backendType == visp::backend_type::cpu) {
        const int maxSide = std::max(input.extent[0], input.extent[1]);
        if (maxSide > 2304) {
            const float scale = 2304.0f / float(maxSide);
            visp::i32x2 target{int(input.extent[0] * scale), int(input.extent[1] * scale)};
            const int multiple = m_model->params.image_multiple;
            target[0] = (target[0] + multiple - 1) / multiple * multiple;
            target[1] = (target[1] + multiple - 1) / multiple * multiple;
            resized = visp::image_scale(input, target);
            input = resized;
        }
    }

    visp::image_data result = visp::birefnet_compute(*m_model, input);
    if (resized.data) result = visp::image_scale(result, image.extent);
    return result;
}
