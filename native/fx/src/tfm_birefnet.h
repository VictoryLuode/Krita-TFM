#pragma once

#include <QMutex>
#include <QString>
#include <QStringList>

#include <memory>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#endif

#include <visp/vision.h>

class BirefnetRuntime final
{
public:
    static BirefnetRuntime &instance();

    QStringList availableModels() const;
    QString modelName() const;
    void setModelName(const QString &name);

    visp::backend_type backend() const;
    bool setBackend(visp::backend_type type, QString *error = nullptr);
    bool backendAvailable(visp::backend_type type) const;
    QString runtimeDirectory() const;
    bool loadVulkanBackend(const QString &absoluteFile, QString *error = nullptr);
    QString backendDescription() const;

    visp::image_data removeBackground(visp::image_view image,
                                      const QString &modelName,
                                      visp::backend_type backendType);

private:
    BirefnetRuntime();
    ~BirefnetRuntime();
    BirefnetRuntime(const BirefnetRuntime &) = delete;
    BirefnetRuntime &operator=(const BirefnetRuntime &) = delete;

    QString modelPath() const;
    bool ensureBackend(QString *error);
    bool preloadVulkanDependenciesLocked(const QString &runtimeDirectory, QString *error);
    bool loadVulkanBackendLocked(const QString &absoluteFile, QString *error);
    bool ensureModel(QString *error);

    mutable QMutex m_mutex;
    QString m_modelName;
    visp::backend_type m_backendType = visp::backend_type::cpu;
    std::unique_ptr<visp::backend_device> m_backend;
    std::unique_ptr<visp::birefnet_model> m_model;
#ifdef _WIN32
    std::vector<HMODULE> m_vulkanDependencies;
#endif
};
