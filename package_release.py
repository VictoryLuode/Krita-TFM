#!/usr/bin/env python3
"""Build a versioned TFM zip from the repo and the current native build outputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from build_artifacts import resource_inventory, license_inventory, validated_current
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NATIVE_BIN = ROOT / "build" / "native-5.3" / "bin"


def version() -> str:
    text = (ROOT / "pykrita" / "tfm" / "menus" / "version.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.M)
    if not match:
        raise SystemExit("missing __version__")
    return match.group(1)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_file(source: Path, target: Path, created: list[Path]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    created.append(target)
    if digest(source) != digest(target):
        raise SystemExit(f"copy verification failed: {target}")


def package_files(staging: Path) -> list[tuple[Path, str]]:
    """Package only a source-verified, complete native batch."""
    batch, manifest = validated_current(ROOT)
    validation_path = ROOT / 'build/test-results/candidate-validation.json'
    validation = json.loads(validation_path.read_text(encoding='utf-8'))
    if validation.get('batch_id') != manifest['batch_id'] or validation.get('status') not in ('passed', 'passed_with_live_host_gap'):
        raise ValueError('Candidate validation does not match this complete build batch')
    created = []
    for source, relative in resource_inventory(ROOT, batch / 'tfm_color_range.dll'):
        copy_file(source, staging / 'resource' / relative, created)
    for name in ('kritatfm.dll', 'tfm_vulkan_worker.exe'):
        copy_file(batch / name, staging / 'kritaplugins' / name, created)
    for source, relative in license_inventory(ROOT):
        copy_file(source, staging / relative, created)
    for name in ('README.md', 'RELEASE_NOTES.md', 'SOURCE-NOTES.md', 'LICENSE'):
        copy_file(ROOT / name, staging / name, created)
    copy_file(batch / 'manifest.json', staging / 'BUILD-MANIFEST.json', created)
    copy_file(validation_path, staging / 'VALIDATION.json', created)
    for name in ('quality-testing.md', 'quality-performance.md', 'quality-compatibility.md', 'candidate-install.md'):
        source = ROOT / 'docs' / name
        if source.is_file():
            copy_file(source, staging / 'docs' / name, created)
    install = staging / 'INSTALL.txt'
    install.write_text(
        "Close Krita before installation. Back up the existing TFM program files.\n"
        "Copy resource/ contents into the chosen Krita resource directory.\n"
        "Copy BOTH kritaplugins files into the same Krita lib/kritaplugins directory.\n"
        "Keep TFM user configuration, assets, scripts and models unchanged.\n"
        "Start Krita and enable TFM in the Python Plugin Manager if necessary.\n"
        "To roll back, restore the complete previous program set with Krita closed.\n"
        "See docs/candidate-install.md for verification, installation and rollback details.\n",
        encoding='utf-8')
    created.append(install)
    # Verify sources again after copying; concurrent edits must not produce a mixed package.
    validated_current(ROOT)
    inventory = {p.relative_to(staging).as_posix(): digest(p) for p in created}
    package_manifest = staging / 'PACKAGE-MANIFEST.json'
    package_manifest.write_text(json.dumps({'schema_version': 1, 'batch_id': manifest['batch_id'],
                                           'files': inventory}, indent=2) + '\n', encoding='utf-8')
    created.append(package_manifest)
    return [(path, path.relative_to(staging).as_posix()) for path in created]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Zip path (default: dist/TFM-<version>.zip)",
    )
    args = parser.parse_args()
    ver = version()
    out = args.output or (ROOT / "dist" / f"TFM-{ver}.zip")
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = ROOT / "build" / "release-staging"
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"TFM-{ver}-", dir=staging_parent))
    pending_zip = out.with_name(out.name + '.pending')

    try:
        members = package_files(staging)
        prefix = f"TFM-{ver}"
        with zipfile.ZipFile(pending_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, relative in members:
                archive.write(path, f"{prefix}/{relative}")
        os.replace(pending_zip, out)
        print("PACKAGE_OK", out)
        print("SHA256", digest(out))
        print("FILES", len(members))
        return 0
    finally:
        pending_zip.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
