"""Compile and run Relight math unit checks (experimental; optional native C++).

Skipped cleanly when `tests/test_relight.cpp` is absent — Relight is research
scaffolding, not a shipped filter. Enable via the experimental test gate.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "tests" / "test_relight.cpp"
OUT = ROOT.parents[1] / "build" / "native-5.3" / "tests" / "test_relight.exe"


def compiler() -> Path:
    found = shutil.which("clang++")
    if found:
        return Path(found)
    for drive in (Path("D:/"), Path("C:/")):
        candidate = drive / "Scoop/apps/llvm-mingw/current/bin/clang++.exe"
        if candidate.is_file():
            return candidate
    return Path("clang++.exe")


def main() -> int:
    if not SRC.is_file():
        print(
            "SKIP: Relight native harness missing "
            f"({SRC.as_posix()}); experimental only, not production coverage.",
            flush=True,
        )
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(compiler()),
        "-std=c++17",
        "-O2",
        str(SRC),
        "-o",
        str(OUT),
    ]
    print(" ".join(cmd), flush=True)
    subprocess.check_call(cmd)
    result = subprocess.run([str(OUT)], check=False)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
