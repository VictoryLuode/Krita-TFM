"""Registry inspection for TFM filter settings.

Only answers "is this filter present in the running Krita?" - no node creation,
no applying, no masks. Usage belongs to Krita's own filter menu and layer stack.
"""

from krita import Krita

from .catalog import FILTERS


class RegistryQueryError(RuntimeError):
    """Krita's filter registry could not be queried reliably."""


def registered_names():
    """Return the filter names Krita currently knows about.

    LibKis exposes filters() as a list of internal names, so membership here is
    the real registration state, not a guess based on the DLL being on disk.
    """
    try:
        names = Krita.instance().filters()
        if not isinstance(names, (list, tuple)) or any(not isinstance(name, str) for name in names):
            raise TypeError("filters() did not return a list of filter names")
        return set(names)
    except Exception as error:
        raise RegistryQueryError("Could not query Krita's filter registry: {}".format(error)) from error


def inspect():
    """Report every managed filter as registered or missing."""
    present = registered_names()
    rows = []
    for entry in FILTERS:
        fid = entry["id"]
        label = entry["label"]
        found = fid in present or label in present
        rows.append(
            {
                "id": fid,
                "label": label,
                "category": entry.get("category", ""),
                "description": entry.get("description", ""),
                "settings": entry.get("settings", []),
                "registered": found,
            }
        )
    return rows


def summary(rows):
    """One-line registry state for the panel header."""
    total = len(rows)
    if total == 0:
        return "No filters managed."
    found = sum(1 for row in rows if row["registered"])
    if found == total:
        return "{}/{} filters registered.".format(found, total)
    missing = [row["label"] for row in rows if not row["registered"]]
    return "{}/{} registered - missing: {}".format(found, total, ", ".join(missing))
