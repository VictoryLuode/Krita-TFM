#!/usr/bin/env python3
"""Fail when __version__ lags the newest X.Y.Z git tag."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def version_from_source() -> str:
    text = (ROOT / "pykrita" / "tfm" / "menus" / "version.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.M)
    if not match:
        raise SystemExit("missing __version__")
    return match.group(1)


def newest_version_tag() -> str | None:
    result = subprocess.run(
        ["git", "tag", "--list", "[0-9]*.[0-9]*.[0-9]*", "--sort=-v:refname"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "git tag failed")
    for line in result.stdout.splitlines():
        tag = line.strip()
        if tag:
            return tag
    return None


def main() -> int:
    version = version_from_source()
    newest = newest_version_tag()
    if newest is None:
        print(f"verify: no version tags yet; __version__={version}")
        return 0
    if version != newest:
        print(f"verify: __version__={version} but newest tag={newest}", file=sys.stderr)
        return 1
    print(f"verify: __version__ matches tag {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
