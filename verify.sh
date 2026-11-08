#!/usr/bin/env bash
# Fail when pykrita/tfm/menus/version.py lags the newest X.Y.Z git tag.
set -euo pipefail
root="$(cd "$(dirname "$0")" && pwd)"
version="$(python - <<'PY'
from pathlib import Path
text = Path("pykrita/tfm/menus/version.py").read_text(encoding="utf-8")
for line in text.splitlines():
    if line.startswith("__version__"):
        print(line.split("=", 1)[1].strip().strip("\"'"))
        break
else:
    raise SystemExit("missing __version__")
PY
)"
cd "$root"
newest="$(git tag --list '[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | head -n1 || true)"
if [[ -z "$newest" ]]; then
  echo "verify: no version tags yet; __version__=$version"
  exit 0
fi
if [[ "$version" != "$newest" ]]; then
  echo "verify: __version__=$version but newest tag=$newest" >&2
  exit 1
fi
echo "verify: __version__ matches tag $version"
