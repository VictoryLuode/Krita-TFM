#pragma once

#include <QImage>
#include <QtGlobal>

#include <cstdint>

namespace fxmanager::background_removal {

inline QImage grayscaleMaskImage(const uint8_t *mask, int width, int height)
{
    if (!mask || width <= 0 || height <= 0) return {};

    QImage output(width, height, QImage::Format_ARGB32);
    if (output.isNull()) return {};

    for (int y = 0; y < height; ++y) {
        QRgb *row = reinterpret_cast<QRgb *>(output.scanLine(y));
        const uint8_t *maskRow = mask + size_t(y) * size_t(width);
        for (int x = 0; x < width; ++x) {
            const int gray = maskRow[x];
            row[x] = qRgb(gray, gray, gray);
        }
    }
    return output;
}

} // namespace fxmanager::background_removal
