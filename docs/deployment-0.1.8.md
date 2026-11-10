# 0.1.8 installation record

Version 0.1.8 was installed into the user-authorized Krita 5.3 Qt5 installation.
All 83 program files were read back and matched the verified build inventory.
Six existing configuration files (menu/filter/backend and Krita profile files)
retained their pre-installation hashes. Complete prior program files were backed
up outside the active Krita plugin/resource scan paths.

Batch: `edfac017e6e26893e4b9fb5a0154f6fa47e4b4360924fb89bf5215e911bf4867`.
Package: `dist/TFM-0.1.8.zip`.
SHA-256: `18ed4c3189a6c95031c9669268493fbca3a39a25ba1c1e703041b7dd780ef927`.

Validation: 260 unit tests per language, three installed-Qt offline tests per
language, 35 native tests, complete staging/rollback/package checks passed.
The cache restoration test now waits for its fixture write before closing;
production shutdown is still allowed to abandon regenerable cache writes.

Live interaction is left to the user's own testing. Installation/readback does
not certify preview/apply, undo/redo or external search-provider behavior.
Local paths and backup inventory are recorded in the ignored
`build/candidate-evidence/deployment-0.1.8.json`.
