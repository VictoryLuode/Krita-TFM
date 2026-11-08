#!/usr/bin/env python3
"""Build a versioned TFM zip from the repo and the current native build outputs."""
from __future__ import annotations

import argparse
import hashlib
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
    """Return (absolute path, archive member path) pairs."""
    created: list[Path] = []
    package = ROOT / "pykrita" / "tfm"
    color_range = package / "native" / "tfm_color_range.dll"
    dll = NATIVE_BIN / "kritatfm.dll"
    worker = NATIVE_BIN / "tfm_vulkan_worker.exe"
    required = [
        package / "__init__.py",
        package / "manager.py",
        color_range,
        ROOT / "pykrita" / "tfm.desktop",
        ROOT / "actions" / "tfm.action",
        dll,
        worker,
        ROOT / "README.md",
        ROOT / "LICENSE",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("Missing required files (build native first):\n  " + "\n  ".join(missing))

    docs = ("README.md", "RELEASE_NOTES.md", "SOURCE-NOTES.md", "LICENSE")
    for name in docs:
        source = ROOT / name
        if source.is_file():
            copy_file(source, staging / name, created)

    for source in package.rglob("*"):
        if not source.is_file() or "__pycache__" in source.parts:
            continue
        if source.suffix not in {".py", ".html"} and source != color_range:
            continue
        relative = source.relative_to(package)
        copy_file(source, staging / "resource" / "pykrita" / "tfm" / relative, created)

    copy_file(ROOT / "pykrita" / "tfm.desktop", staging / "resource" / "pykrita" / "tfm.desktop", created)
    copy_file(ROOT / "actions" / "tfm.action", staging / "resource" / "actions" / "tfm.action", created)
    copy_file(dll, staging / "kritaplugins" / "kritatfm.dll", created)
    copy_file(worker, staging / "kritaplugins" / "tfm_vulkan_worker.exe", created)

    install = staging / "INSTALL.txt"
    install.write_text(
        "TFM install\n"
        "===========\n"
        "1. Close Krita.\n"
        "2. Copy everything under resource/ into your Krita resource directory.\n"
        "3. Copy kritaplugins/kritatfm.dll and kritaplugins/tfm_vulkan_worker.exe\n"
        "   into the Krita install lib/kritaplugins/ folder (same directory).\n"
        "4. Start Krita and enable TFM in Python Plugin Manager if needed.\n",
        encoding="utf-8",
    )
    created.append(install)

    members = []
    for path in created:
        members.append((path, path.relative_to(staging).as_posix()))
    return members


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
    staging = ROOT / "build" / "release-staging" / f"TFM-{ver}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    try:
        members = package_files(staging)
        prefix = f"TFM-{ver}"
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, relative in members:
                archive.write(path, f"{prefix}/{relative}")
        print("PACKAGE_OK", out)
        print("SHA256", digest(out))
        print("FILES", len(members))
        return 0
    finally:
        shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
