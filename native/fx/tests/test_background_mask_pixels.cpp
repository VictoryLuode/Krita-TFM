#include "../src/fxmanager_background_mask.h"

#include <cassert>
#include <cstdio>
#include <cstdint>

int main()
{
    const uint8_t mask[] = {0, 1, 64, 127, 128, 200, 254, 255};
    const QImage result = fxmanager::background_removal::grayscaleMaskImage(mask, 4, 2);
    assert(!result.isNull());
    assert(result.format() == QImage::Format_ARGB32);
    assert(result.width() == 4 && result.height() == 2);

    for (int y = 0; y < result.height(); ++y) {
        const QRgb *row = reinterpret_cast<const QRgb *>(result.constScanLine(y));
        for (int x = 0; x < result.width(); ++x) {
            const int expected = mask[y * result.width() + x];
            assert(qRed(row[x]) == expected);
            assert(qGreen(row[x]) == expected);
            assert(qBlue(row[x]) == expected);
            assert(qAlpha(row[x]) == 255);
        }
    }

    const QImage nullInput = fxmanager::background_removal::grayscaleMaskImage(nullptr, 4, 2);
    const QImage invalidExtent = fxmanager::background_removal::grayscaleMaskImage(mask, 0, 2);
    assert(nullInput.isNull());
    assert(invalidExtent.isNull());

    std::puts("Background grayscale mask pixels: 0/1/64/127/128/200/254/255 map exactly to opaque RGB gray; invalid inputs rejected PASS");
}
