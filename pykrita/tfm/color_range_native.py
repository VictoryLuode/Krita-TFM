"""Load the bundled Windows color-range kernel."""
import ctypes
import math
from pathlib import Path


class _Sample(ctypes.Structure):
    _fields_ = [(name, ctypes.c_double) for name in ('r', 'g', 'b', 'x', 'y')] + [('add', ctypes.c_int)]


_U8 = ctypes.c_uint8
_U8_PTR = ctypes.POINTER(_U8)
_LIBRARY_PATH = Path(__file__).parent / 'native' / 'tfm_color_range.dll'
_library = None
_functions = {}


def _option(value):
    if value is None:
        return -1.0
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError('Tolerance and softness must be finite and non-negative.')
    return value


def _function(name, argtypes):
    function = _functions.get(name)
    if function is not None:
        return function
    global _library
    if _library is None:
        try:
            _library = ctypes.CDLL(str(_LIBRARY_PATH))
        except OSError as error:
            raise RuntimeError('Advance Selection native component could not be loaded: ' + str(error)) from error
    try:
        function = getattr(_library, name)
    except AttributeError as error:
        raise RuntimeError('Advance Selection native component is missing or outdated: ' + name) from error
    function.argtypes = argtypes
    function.restype = ctypes.c_int
    _functions[name] = function
    return function


def _image_source(image):
    if image.format() != image.Format.Format_ARGB32:
        raise ValueError('Advance Selection requires an ARGB32 image.')
    width, height, stride = image.width(), image.height(), image.bytesPerLine()
    pointer = image.constBits()
    pointer.setsize(stride * height)
    return ctypes.cast(int(pointer), _U8_PTR), width, height, stride


def _output(size):
    result = bytearray(size)
    return result, (_U8 * size).from_buffer(result)


def _mutable(data):
    return data if isinstance(data, bytearray) else bytearray(data)


def mask(image, samples, fuzziness, localized, radius, invert, threshold_enabled=True,
         *, tolerance=None, softness=None):
    """Sample mask. Tolerance and softness use RMS RGB distance (0..255)."""
    options = tolerance is not None or softness is not None
    tolerance, softness = _option(tolerance), _option(softness)
    fn = _function(
        'tfm_color_range_options' if options else 'tfm_color_range',
        [_U8_PTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
         ctypes.POINTER(_Sample), ctypes.c_int, ctypes.c_double,
         ctypes.c_int, ctypes.c_double, ctypes.c_int, ctypes.c_int] +
        ([ctypes.c_double, ctypes.c_double] if options else []) + [_U8_PTR])
    source, width, height, stride = _image_source(image)
    output, out = _output(width * height)
    sample_array = (_Sample * len(samples))(*(_Sample(*sample) for sample in samples))
    args = [source, width, height, stride, sample_array, len(samples), fuzziness,
            int(localized), radius, int(invert), int(threshold_enabled)]
    if options:
        args.extend((tolerance, softness))
    if fn(*args, out) != 0:
        raise RuntimeError('Advance Selection native calculation failed.')
    return output


def perceptual(image, luminance, mode, threshold, invert, threshold_enabled=True,
               *, tolerance=None, softness=None):
    """Calculate perceptual masks; overrides use degrees for hue/skin and luminance levels for tonal modes."""
    options = tolerance is not None or softness is not None
    tolerance, softness = _option(tolerance), _option(softness)
    names = ('hue_red', 'hue_yellow', 'hue_green', 'hue_cyan', 'hue_blue',
             'hue_magenta', 'skin', 'highlights', 'midtones', 'shadows')
    if mode not in names:
        raise ValueError('Unknown perceptual selection mode.')
    source, width, height, stride = _image_source(image)
    if len(luminance) != width * height:
        raise ValueError('Invalid Advance Selection luminance.')
    fn = _function(
        'tfm_perceptual_options' if options else 'tfm_perceptual',
        [_U8_PTR, _U8_PTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
         ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int] +
        ([ctypes.c_double, ctypes.c_double] if options else []) + [_U8_PTR])
    lum_data = _mutable(luminance)
    lum = (_U8 * len(lum_data)).from_buffer(lum_data)
    output, out = _output(width * height)
    args = [source, lum, width, height, stride, names.index(mode), threshold,
            int(invert), int(threshold_enabled)]
    if options:
        args.extend((tolerance, softness))
    if fn(*args, out) != 0:
        raise RuntimeError('Advance Selection native calculation failed.')
    return output


def channel_mask(image, luminance, channel, threshold, invert, threshold_enabled=True,
                 *, tolerance=None, softness=None):
    """Calculate one RGB or luminance channel mask in native code."""
    if channel not in ('red', 'green', 'blue', 'luminance'):
        raise ValueError('Unknown channel selection mode.')
    tolerance, softness = _option(tolerance), _option(softness)
    source, width, height, stride = _image_source(image)
    if len(luminance) != width * height:
        raise ValueError('Invalid Advance Selection luminance.')
    fn = _function('tfm_channel_mask',
                    [_U8_PTR, _U8_PTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                     ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                     ctypes.c_double, ctypes.c_double, _U8_PTR])
    lum_data = _mutable(luminance)
    lum = (_U8 * len(lum_data)).from_buffer(lum_data)
    output, out = _output(width * height)
    args = [source, lum, width, height, stride,
            ('red', 'green', 'blue', 'luminance').index(channel), threshold,
            int(invert), int(threshold_enabled), tolerance, softness]
    if fn(*args, out) != 0:
        raise RuntimeError('Advance Selection native calculation failed.')
    return output


def outline(mask, width, height):
    """Extract indexed marching-ant edges without touching document selection."""
    if width <= 0 or height <= 0 or len(mask) != width * height:
        raise ValueError('Invalid outline mask dimensions.')
    fn = _function('tfm_color_range_outline', [_U8_PTR, ctypes.c_int, ctypes.c_int, _U8_PTR])
    source_data = _mutable(mask)
    source = (_U8 * len(source_data)).from_buffer(source_data)
    output, target = _output(len(mask))
    if fn(source, width, height, target) != 0:
        raise RuntimeError('Advance Selection outline calculation failed.')
    return output


def combine(mask, old, mode):
    """Combine two byte masks: replace, add, subtract, or intersect."""
    names = {'replace': 0, 'add': 1, 'subtract': 2, 'intersect': 3}
    if mode not in names:
        raise ValueError('Unknown selection combination mode.')
    if len(mask) != len(old) or not mask:
        raise ValueError('Selection masks have incompatible dimensions.')
    fn = _function('tfm_color_range_combine',
                    [_U8_PTR, _U8_PTR, ctypes.c_int, ctypes.c_int, ctypes.c_int, _U8_PTR])
    mask_data, old_data = _mutable(mask), _mutable(old)
    m = (_U8 * len(mask_data)).from_buffer(mask_data)
    o = (_U8 * len(old_data)).from_buffer(old_data)
    result, out = _output(len(mask))
    if fn(m, o, len(mask), 1, names[mode], out) != 0:
        raise RuntimeError('Advance Selection selection combination failed.')
    return result
