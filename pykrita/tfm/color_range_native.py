"""Load the bundled Windows color-range kernel."""
import ctypes
import math
from pathlib import Path


class _Sample(ctypes.Structure):
    _fields_ = [(name, ctypes.c_double) for name in ('r', 'g', 'b', 'x', 'y')] + [('add', ctypes.c_int)]


def _option(value):
    if value is None:
        return -1.0
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError('Tolerance and softness must be finite and non-negative.')
    return value


def mask(image, samples, fuzziness, localized, radius, invert, threshold_enabled=True,
         *, tolerance=None, softness=None):
    """Sample mask. Tolerance and softness use RMS RGB distance (0..255).

    When either is specified, smoothstep spans tolerance +/- softness;
    an omitted value defaults to half the legacy fuzziness scale. Zero
    softness produces a hard edge. Omitting both retains the legacy curve.
    """
    options = tolerance is not None or softness is not None
    tolerance, softness = _option(tolerance), _option(softness)
    path = Path(__file__).parent / 'native' / 'tfm_color_range.dll'
    try:
        library = ctypes.CDLL(str(path))
        fn = library.tfm_color_range_options if options else library.tfm_color_range
    except (OSError, AttributeError) as error:
        raise RuntimeError('Advance Selection native component could not be loaded: ' + str(error)) from error
    u8 = ctypes.c_uint8
    fn.argtypes = [ctypes.POINTER(u8), ctypes.c_int, ctypes.c_int, ctypes.c_int,
                   ctypes.POINTER(_Sample), ctypes.c_int, ctypes.c_double,
                   ctypes.c_int, ctypes.c_double, ctypes.c_int, ctypes.c_int] + (
                   [ctypes.c_double, ctypes.c_double] if options else []) + [ctypes.POINTER(u8)]
    fn.restype = ctypes.c_int
    width, height, stride = image.width(), image.height(), image.bytesPerLine()
    pointer = image.constBits()
    pointer.setsize(stride * height)
    source = ctypes.cast(int(pointer), ctypes.POINTER(u8))
    output = bytearray(width * height)
    out = (u8 * len(output)).from_buffer(output)
    sample_array = (_Sample * len(samples))(*(_Sample(*s) for s in samples))
    if image.format() != image.Format.Format_ARGB32:
        raise ValueError('Advance Selection requires an ARGB32 image.')
    args = [source, width, height, stride, sample_array, len(samples), fuzziness,
            int(localized), radius, int(invert), int(threshold_enabled)]
    if options:
        args.extend((tolerance, softness))
    if fn(*args, out) != 0:
        raise RuntimeError('Advance Selection native calculation failed.')
    return output


def perceptual(image, luminance, mode, threshold, invert, threshold_enabled=True,
               *, tolerance=None, softness=None):
    """Calculate perceptual masks; overrides use degrees for hue/skin and
    luminance levels for tonal modes. Zero softness makes a hard edge.
    Unspecified overrides retain the corresponding legacy defaults.
    """
    options = tolerance is not None or softness is not None
    tolerance, softness = _option(tolerance), _option(softness)
    names = ('hue_red', 'hue_yellow', 'hue_green', 'hue_cyan', 'hue_blue',
             'hue_magenta', 'skin', 'highlights', 'midtones', 'shadows')
    if mode not in names:
        raise ValueError('Unknown perceptual selection mode.')
    width, height, stride = image.width(), image.height(), image.bytesPerLine()
    if image.format() != image.Format.Format_ARGB32 or len(luminance) != width * height:
        raise ValueError('Invalid Advance Selection image or luminance.')
    try:
        library = ctypes.CDLL(str(Path(__file__).parent / 'native' / 'tfm_color_range.dll'))
        fn = library.tfm_perceptual_options if options else library.tfm_perceptual
    except (OSError, AttributeError) as error:
        raise RuntimeError('Advance Selection native component is missing or outdated: ' + str(error)) from error
    u8 = ctypes.c_uint8
    fn.argtypes = [ctypes.POINTER(u8), ctypes.POINTER(u8), ctypes.c_int, ctypes.c_int,
                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                   ctypes.c_int] + ([ctypes.c_double, ctypes.c_double] if options else []) + [ctypes.POINTER(u8)]
    fn.restype = ctypes.c_int
    pointer = image.constBits()
    pointer.setsize(stride * height)
    source = ctypes.cast(int(pointer), ctypes.POINTER(u8))
    lum = (u8 * len(luminance)).from_buffer_copy(luminance)
    output = bytearray(width * height)
    out = (u8 * len(output)).from_buffer(output)
    args = [source, lum, width, height, stride, names.index(mode), threshold,
            int(invert), int(threshold_enabled)]
    if options:
        args.extend((tolerance, softness))
    if fn(*args, out) != 0:
        raise RuntimeError('Advance Selection native calculation failed.')
    return bytes(output)


def outline(mask, width, height):
    """Extract indexed marching-ant edges without touching document selection."""
    if width <= 0 or height <= 0 or len(mask) != width * height:
        raise ValueError('Invalid outline mask dimensions.')
    library = ctypes.CDLL(str(Path(__file__).parent / 'native' / 'tfm_color_range.dll'))
    u8 = ctypes.c_uint8
    fn = library.tfm_color_range_outline
    fn.argtypes = [ctypes.POINTER(u8), ctypes.c_int, ctypes.c_int, ctypes.POINTER(u8)]
    fn.restype = ctypes.c_int
    source = (u8 * len(mask)).from_buffer_copy(mask)
    output = bytearray(len(mask))
    target = (u8 * len(mask)).from_buffer(output)
    if fn(source, width, height, target) != 0:
        raise RuntimeError('Advance Selection outline calculation failed.')
    return bytes(output)


def combine(mask, old, mode):
    """Combine two byte masks: replace, add, subtract, or intersect."""
    library_path = Path(__file__).parent / 'native' / 'tfm_color_range.dll'
    try:
        library = ctypes.CDLL(str(library_path))
        fn = library.tfm_color_range_combine
    except (OSError, AttributeError) as error:
        raise RuntimeError('Advance Selection native component could not be loaded: ' + str(error)) from error
    fn.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint8),
                   ctypes.c_int, ctypes.c_int, ctypes.c_int,
                   ctypes.POINTER(ctypes.c_uint8)]
    fn.restype = ctypes.c_int
    if len(mask) != len(old) or len(mask) == 0:
        raise ValueError('Selection masks have incompatible dimensions.')
    names = {'replace': 0, 'add': 1, 'subtract': 2, 'intersect': 3}
    if mode not in names:
        raise ValueError('Unknown selection combination mode.')
    size = len(mask)
    m = (ctypes.c_uint8 * size).from_buffer_copy(mask)
    o = (ctypes.c_uint8 * size).from_buffer_copy(old)
    result = bytearray(size)
    out = (ctypes.c_uint8 * size).from_buffer(result)
    if fn(m, o, size, 1, names[mode], out) != 0:
        raise RuntimeError('Advance Selection selection combination failed.')
    return result

