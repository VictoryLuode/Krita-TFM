"""Color range selection calculations, independent of the host UI."""
import math


def selection_value(rgb, x, y, samples, fuzziness, localized=False, radius=1.0,
                    alpha=255, invert=False):
    """Return an 8-bit selection value for positive and negative samples.

    Samples are (red, green, blue, x, y, add); coordinates are normalized.
    """
    scale = max(1.0, float(fuzziness))
    positive = 0.0
    negative = 0.0
    for r, g, b, sx, sy, add in samples:
        distance = math.sqrt(sum((a - c) ** 2 for a, c in zip(rgb, (r, g, b))) / 3.0)
        weight = max(0.0, min(1.0, 1.0 - distance / scale))
        if localized and radius < 1.0:
            spatial = math.hypot(x - sx, y - sy)
            weight *= max(0.0, min(1.0, (radius - spatial) / max(radius * 0.2, 0.001)))
        if add:
            positive = max(positive, weight)
        else:
            negative = max(negative, weight)
    value = round(255 * max(0.0, positive - negative))
    if invert:
        value = 255 - value
    return round(value * max(0, min(255, alpha)) / 255.0)
