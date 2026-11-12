#pragma once

#include <QObject>
#include <QVariant>

class QFileSystemWatcher;
class QTimer;

class TfmPlugin : public QObject
{
    Q_OBJECT
public:
    TfmPlugin(QObject *parent, const QVariantList &);

private:
    void syncFilters();
    void watchSettings();

    QFileSystemWatcher *m_watcher = nullptr;
    QTimer *m_debounce = nullptr;
};
