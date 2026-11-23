"""Pack QImage pixels into the channel order Krita paint layers expect.

On the supported little-endian host, U8 ARGB32 bytes are already BGRA.
U16 layers receive straight BGRA64 pixels from the original QImage.
"""

import array
import sys


def expand_u8_to_u16(raw):
    values = array.array("H", (byte * 257 for byte in raw))
    if sys.byteorder != "little":
        values.byteswap()
    return values.tobytes()


def downsample_u16_bgra(raw):
    """Keep the high byte of each little-endian 16-bit channel."""
    high = 1 if sys.byteorder == "little" else 0
    return bytes(raw[index + high] for index in range(0, len(raw) - 1, 2))


def qimage_from_bgra8(raw, width, height):
    from ..menus.qtcompat import QImage

    row = width * 4
    if width < 1 or height < 1 or len(raw) < row * height:
        return None
    image = QImage(bytes(raw[:row * height]), width, height, QImage.Format.Format_ARGB32)
    if image.isNull():
        return None
    return image.copy()


def paint_bytes(image, depth):
    if image is None or image.isNull():
        return b"", 0, 0
    if depth == "U8":
        return pack_bgra8(image)
    if depth == "U16":
        from ..menus.qtcompat import QImage

        # Qt converts premultiplied and lower-depth inputs to straight RGBA64.
        # rgbSwapped exchanges the 16-bit R/B words in Qt's native code.
        bgra = image.convertToFormat(QImage.Format.Format_RGBA64).rgbSwapped()
        return _packed_rows(bgra, 8)
    return None


def pack_bgra8(image):
    from ..menus.qtcompat import QImage

    if image is None or image.isNull() or image.width() < 1 or image.height() < 1:
        return b"", 0, 0
    converted = image
    if converted.format() != QImage.Format.Format_ARGB32:
        converted = converted.convertToFormat(QImage.Format.Format_ARGB32)
    return _packed_rows(converted, 4)


def _packed_rows(converted, bytes_per_pixel):
    width = converted.width()
    height = converted.height()
    stride = converted.bytesPerLine()
    raw = _image_bytes(converted)
    row = width * bytes_per_pixel
    if len(raw) < stride * height:
        raise ValueError("short image buffer")
    if stride == row:
        packed = raw[:height * row]
    else:
        packed = b"".join(raw[y * stride:y * stride + row] for y in range(height))
    return packed, width, height


def qbytearray_from(data):
    from ..menus.qtcompat import QByteArray

    payload = bytes(data)
    array = QByteArray(payload)
    if array.size() != len(payload):
        raise ValueError("could not copy pixel bytes")
    return array


def _image_bytes(image):
    size = image.sizeInBytes() if hasattr(image, "sizeInBytes") else image.byteCount()
    bits = image.constBits()
    setsize = getattr(bits, "setsize", None)
    if setsize is not None:
        setsize(size)
    data = bytes(bits)
    if len(data) < size:
        asstring = getattr(bits, "asstring", None)
        if asstring is None:
            raise ValueError("could not read image pixels")
        data = asstring(size)
    return data
