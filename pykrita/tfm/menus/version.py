"""TFM version - the single source of the number shown in the editor.

`RELEASE_NOTES.md` and the release zip name are generated from this value at
release time; `python verify.py` fails when it falls behind the newest git tag.
Bump it in the same commit that gets tagged.
"""

__version__ = "0.1.10"
