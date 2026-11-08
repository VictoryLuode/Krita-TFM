import importlib.util
import pathlib
import unittest

_MODULE = pathlib.Path(__file__).parents[1] / "pykrita" / "quick_image_search" / "browser.py"
_SPEC = importlib.util.spec_from_file_location("browser_under_test", _MODULE)
_BROWSER = importlib.util.module_from_spec(_SPEC)
import sys
sys.modules[_SPEC.name] = _BROWSER
_SPEC.loader.exec_module(_BROWSER)

Browser = _BROWSER.Browser
BrowserUnavailable = _BROWSER.BrowserUnavailable
SearchError = _BROWSER.SearchError
VerificationRequired = _BROWSER.VerificationRequired
_validate_cdp_url = _BROWSER._validate_cdp_url
_WebSocket = _BROWSER._WebSocket


class BrowserUnitTests(unittest.TestCase):
    def test_start_reuses_existing_local_browser(self):
        from unittest.mock import patch
        b = Browser()
        with patch.object(b, '_endpoint_ready', return_value=True), patch.object(_BROWSER.subprocess, 'Popen') as spawn:
            b.start('C:/isolated-profile')
            spawn.assert_not_called()

    def test_start_uses_dedicated_profile_and_explicit_proxy(self):
        from unittest.mock import patch
        b = Browser()
        with patch.object(b, '_endpoint_ready', side_effect=[False, True]), patch.object(_BROWSER, '_chrome_executable', return_value='C:/Chrome/chrome.exe'), patch.object(_BROWSER.subprocess, 'Popen') as spawn, patch.object(_BROWSER.Path, 'mkdir'):
            b.start('C:/isolated-profile', proxy='http://127.0.0.1:7890')
            command = spawn.call_args.args[0]
            self.assertIn('--user-data-dir=C:/isolated-profile', command)
            self.assertIn('--proxy-server=http://127.0.0.1:7890', command)
            self.assertIn('--remote-debugging-port=9235', command)

    def test_show_restores_browser_window(self):
        b = Browser()
        b._targets = {'google': 'target'}
        b._sessions = {'google': 'session'}
        calls = []
        def command(method, params=None, session=None):
            calls.append((method, params))
            return {'windowId': 7} if method == 'Browser.getWindowForTarget' else {}
        b._command = command
        b.show()
        self.assertIn(('Browser.setWindowBounds', {'windowId': 7, 'bounds': {'windowState': 'normal'}}), calls)

    def test_rejects_non_local_cdp_websocket_urls(self):
        for url in ("ws://example.com/devtools/browser/x", "ws://127.0.0.2/x", "wss://127.0.0.1/x"):
            with self.subTest(url=url), self.assertRaises(BrowserUnavailable):
                _validate_cdp_url(url)

    def test_websocket_masked_frame_roundtrip_with_local_socket(self):
        import socket, threading
        server, client = socket.socketpair()
        def peer():
            first, second = server.recv(2)
            self.assertEqual(first & 0x0F, 1)
            self.assertTrue(second & 0x80)
            n = second & 0x7F
            if n == 126:
                n = int.from_bytes(server.recv(2), "big")
            elif n == 127:
                n = int.from_bytes(server.recv(8), "big")
            mask = server.recv(4)
            data = bytearray()
            while len(data) < n:
                data.extend(server.recv(n - len(data)))
            self.assertEqual(bytes(b ^ mask[i % 4] for i, b in enumerate(data)), b"hello")
            server.sendall(bytes([0x81, 5]) + b"world")
        t = threading.Thread(target=peer)
        t.start()
        ws = _WebSocket(client, timeout=1, max_frame=1024)
        ws.send("hello")
        self.assertEqual(ws.recv(), "world")
        ws.close(); t.join(); server.close()

    def test_search_rejects_unknown_source(self):
        b = Browser()
        with self.assertRaises(SearchError):
            b.search("other", "x")

    def test_result_ids_and_limit_are_stable_and_bounded(self):
        b = Browser()
        b._ensure_tab = lambda *_: "mock-session"
        b._evaluate = lambda *_: {"href": "https://www.google.com/search?tbm=isch&q=x", "title": "", "body": "", "items": [
            {"title": f"t{i}", "thumbnail": f"https://img.test/{i}.jpg", "detail_url": f"https://site.test/{i}"} for i in range(4)]}
        b._navigate = lambda *_: None
        out = b.search("google", "x", limit=2)
        self.assertEqual(len(out), 2)
        self.assertEqual(set(out[0]), {"id", "title", "thumbnail", "detail_url", "source"})
        self.assertEqual(out[0]["source"], "google")
        self.assertNotEqual(out[0]["id"], out[1]["id"])

    def test_verification_page_raises(self):
        b = Browser()
        b._ensure_tab = lambda *_: "mock-session"
        b._evaluate = lambda *_: {"href": "https://www.google.com/sorry/index", "title": "Unusual traffic", "body": "unusual traffic", "challenge": True}
        b._navigate = lambda *_: None
        with self.assertRaises(VerificationRequired):
            b.search("google", "x")

    def test_resolve_returns_contract(self):
        b = Browser()
        b._ensure_tab = lambda *_: "mock-session"
        b._navigate = lambda *_: None
        b._command = lambda *args, **kwargs: {}
        b._evaluate = lambda _, expr: {'x': 40, 'y': 50} if 'scrollIntoView' in expr else {"href": "https://www.google.com/search?udm=2&q=x", "title": "large", "url": "https://cdn.test/full.jpg"}
        entry = {"source": "google", "detail_url": "https://www.google.com/search?udm=2&q=x", "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=x", "title": "x"}
        self.assertEqual(b.resolve(entry), {"url": "https://cdn.test/full.jpg", "referer": "https://www.google.com/search?udm=2&q=x", "title": "x"})

    def test_google_resolve_uses_real_pointer_events(self):
        b = Browser()
        b._ensure_tab = lambda *_: 'session'
        b._navigate = lambda *_: None
        calls = []
        b._command = lambda method, params=None, session=None: calls.append((method, params)) or {}
        b._evaluate = lambda _, expr: {'x': 80, 'y': 90} if 'scrollIntoView' in expr else {'href': 'https://www.google.com/search?q=x', 'url': 'https://cdn.test/full.png'}
        entry = {'source': 'google', 'detail_url': 'https://www.google.com/search?q=x', 'thumbnail': 'https://encrypted-tbn0.gstatic.com/images?q=x', 'title': 'Concrete'}
        b.resolve(entry)
        self.assertEqual([params['type'] for method, params in calls if method == 'Input.dispatchMouseEvent'], ['mousePressed', 'mouseReleased'])

    def test_pinterest_rejects_disguised_external_detail_url(self):
        b = Browser()
        with self.assertRaises(SearchError):
            b.resolve({'source': 'pinterest', 'detail_url': 'https://evil.test/pinterest.com/pin/123/', 'thumbnail': 'https://i.pinimg.com/a.jpg'})


if __name__ == "__main__":
    unittest.main()
