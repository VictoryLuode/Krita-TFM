#pragma once
#include <QObject>
#include <QVariant>
class TfmPlugin : public QObject { public: TfmPlugin(QObject*,const QVariantList&); };
