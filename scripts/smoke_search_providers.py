#!/usr/bin/env python3
"""Offline smoke harness for Quick Image Search providers.

Does not open browsers or hit the network. Validates Backend routing,
source selection, and stub provider contracts so CI can catch wiring
regressions without live-host Google/Pinterest sessions.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYKRITA = ROOT / "pykrita"
if str(PYKRITA) not in sys.path:
    sys.path.insert(0, str(PYKRITA))


class StubGoogle:
    def __init__(self):
        self.started = False
        self.closed = False
        self.queries = []

    def start(self, profile_dir, proxy="", headless=True):
        self.started = True
        self.profile_dir = profile_dir
        self.proxy = proxy
        self.headless = headless

    def search(self, source, query, limit=24):
        self.queries.append((source, query, limit))
        return [{"source": source, "url": "https://example.test/g", "title": query}]

    def resolve(self, entry):
        return dict(entry, resolved=True)

    def more(self, source, limit=24):
        return [{"source": source, "url": "https://example.test/g-more"}]

    def has_more(self, source):
        return source == "google"

    def show(self):
        return True

    def close(self, deadline=None):
        self.closed = True


class StubPinterest:
    def __init__(self):
        self.started = False
        self.closed = False

    def start(self, profile_dir, proxy=""):
        self.started = True
        self.profile_dir = profile_dir
        self.proxy = proxy

    def search(self, source, query, limit=24):
        return [{"source": source, "url": "https://example.test/p", "title": query}]

    def resolve(self, entry):
        return dict(entry, resolved=True)

    def similar(self, image_bytes, limit=24):
        assert image_bytes == b"png"
        return [{"source": "pinterest", "url": "https://example.test/sim"}]

    def more(self, source, limit=24):
        return [{"source": source, "url": "https://example.test/p-more"}]

    def has_more(self, source):
        return source == "pinterest"

    def close(self):
        self.closed = True


def smoke_offline():
    from quick_image_search.backend import Backend

    google = StubGoogle()
    pinterest = StubPinterest()
    backend = Backend(google=google, pinterest=pinterest)
    with tempfile.TemporaryDirectory(prefix="tfm-search-smoke-") as temporary:
        backend.start(temporary, proxy="socks5://127.0.0.1:1080")
        google_hits = backend.search("google", "cat", limit=3)
        assert google.started and google.headless is True
        assert google_hits and google_hits[0]["title"] == "cat"
        pin_hits = backend.search("pinterest", "fox", limit=2)
        assert pinterest.started and pin_hits[0]["source"] == "pinterest"
        assert backend.resolve(google_hits[0])["resolved"] is True
        assert backend.similar(b"png")[0]["source"] == "pinterest"
        assert backend.has_more("google") and backend.has_more("pinterest")
        assert backend.more("google")
        backend.show()
        try:
            backend.resolve({"source": "google", "url": "https://example.test/g"})
            raise AssertionError("expected verification gate")
        except ValueError as error:
            assert "Google" in str(error) or "验证" in str(error)
        try:
            backend.search("bing", "x")
            raise AssertionError("expected unsupported source")
        except ValueError:
            pass
        # Avoid Backend.close()'s Browser import (needs Qt); stubs close directly.
        google.close()
        pinterest.close()
        assert google.closed and pinterest.closed
    print("smoke_search_providers: offline ok")


def smoke_session_modules():
    """Import real provider modules without opening a browser or network."""
    from quick_image_search import backend as backend_mod
    assert hasattr(backend_mod, "Backend")
    # Pinterest/Browser pull Qt via network helpers; missing Qt is a skip.
    try:
        from quick_image_search import pinterest as pinterest_mod
        assert hasattr(pinterest_mod, "Pinterest")
        from quick_image_search import browser as browser_mod
        assert hasattr(browser_mod, "Browser")
        print("smoke_search_providers: session modules ok")
    except Exception as error:  # noqa: BLE001 — environment may lack Qt
        print(f"smoke_search_providers: session modules partial ({error.__class__.__name__}: {error})")


def smoke_live():
    """Optional live probe. Requires TFM_SEARCH_LIVE=1 and a working Qt+network stack."""
    import os
    if os.environ.get("TFM_SEARCH_LIVE") != "1":
        print("smoke_search_providers: live skipped (set TFM_SEARCH_LIVE=1 to enable)")
        return
    from quick_image_search.backend import Backend
    with tempfile.TemporaryDirectory(prefix="tfm-search-live-") as temporary:
        backend = Backend()
        backend.start(temporary)
        hits = backend.search("pinterest", "red fox", limit=2)
        assert isinstance(hits, list) and hits, "live Pinterest returned no hits"
        print(f"smoke_search_providers: live ok ({len(hits)} hits)")
        for driver in (backend._google, backend._pinterest):
            if driver is not None and hasattr(driver, "close"):
                driver.close()


def main():
    smoke_offline()
    smoke_session_modules()
    smoke_live()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
