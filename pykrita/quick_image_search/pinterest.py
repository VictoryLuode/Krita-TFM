"""Anonymous, direct Pinterest keyword search backend."""
import json
import re
import uuid
import urllib.error
import urllib.parse
import urllib.request
from quick_image_search.network import request_bytes
from quick_image_search.task_runtime import check_cancelled


class PinterestError(Exception):
    """Pinterest returned an unusable response or a network error."""


class PinterestVerificationRequired(PinterestError):
    """Pinterest denied anonymous access or requires verification."""


class Pinterest:
    API_URL = "https://www.pinterest.com/resource/BaseSearchResource/get/"
    MAX_BYTES = 8 * 1024 * 1024
    TIMEOUT = 20
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

    def __init__(self, transport=None):
        self.proxy = ""
        self._transport = transport
        self._query = None
        self._cursor = None
        self._seen = set()
        self._pending = []
        self._ended = True
        self._retried_cursors = set()
        self._mode = "keyword"
        self._image_bytes = None

    def start(self, profile_dir=None, proxy=""):
        self.proxy = proxy or ""

    def close(self):
        return None

    def show(self):
        raise PinterestError("Pinterest direct search does not use or open a browser.")

    def has_more(self, source="pinterest"):
        return source == "pinterest" and bool(self._pending or not self._ended)

    def search(self, source, query, limit=24):
        if source != "pinterest":
            raise PinterestError("Pinterest backend only supports source='pinterest'.")
        if not isinstance(query,str) or not query.strip():
            raise PinterestError('搜索关键词不能为空。')
        self._query = query.strip()
        self._mode = "keyword"
        self._image_bytes = None
        self._cursor = None
        self._seen.clear()
        self._pending.clear()
        self._ended = False
        self._retried_cursors.clear()
        return self._take(limit)

    def similar(self, image_bytes, limit=24):
        if not isinstance(image_bytes, bytes) or not image_bytes:
            raise PinterestError("Similarity search requires non-empty image bytes.")
        if len(image_bytes) > self.MAX_BYTES:
            raise PinterestError("Similarity image exceeded 8 MiB limit.")
        self._mode, self._image_bytes, self._query = "visual", image_bytes, None
        self._cursor = None
        self._seen.clear()
        self._pending.clear()
        self._ended = False
        self._retried_cursors.clear()
        return self._take(limit)

    def more(self, source="pinterest", limit=24):
        if source != "pinterest":
            raise PinterestError("Pinterest backend only supports source='pinterest'.")
        return self._take(limit)

    def _take(self, limit):
        try:
            count = max(0, int(limit))
        except (TypeError, ValueError):
            count = 24
        if not self._pending:
            self._fill(count)
        result, self._pending = self._pending[:count], self._pending[count:]
        return result

    def _fill(self, count):
        fetches = 0
        while len(self._pending) < count and not self._ended and fetches < 5:
            cursor = self._cursor
            if cursor in self._retried_cursors:
                self._ended = True
                break
            if self._mode == "visual":
                req = self._visual_request(cursor)
            else:
                data = {"options": {"query": self._query, "scope": "pins", "page_size": 25,
                                    "bookmarks": [] if cursor is None else [cursor]}, "context": {}}
                source_url = "/search/pins/?q=" + urllib.parse.quote(str(self._query), safe="")
                params = urllib.parse.urlencode({"source_url": source_url, "data": json.dumps(data, separators=(",", ":"))})
                req = urllib.request.Request(self.API_URL + "?" + params, headers={
                    "X-Pinterest-PWS-Handler": "www/[username]/search/pins.js",
                    "Accept": "application/json", "Referer": "https://www.pinterest.com/",
                    "User-Agent": self.USER_AGENT,
                })
            fetches += 1
            try:
                response = self._request(req)
                obj = json.loads(response.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise PinterestVerificationRequired("Pinterest access denied (HTTP %s); verification/access may be required." % exc.code) from exc
                raise PinterestError("Pinterest request failed (HTTP %s)." % exc.code) from exc
            except PinterestError:
                raise
            except Exception as exc:
                raise PinterestError("Pinterest request failed: %s" % exc) from exc
            try:
                if self._mode == "visual":
                    if obj.get("status") != "success" or not isinstance(obj.get("data"), list):
                        raise ValueError("invalid visual response")
                    pins = obj["data"]
                    next_cursor = obj.get("bookmark")
                    if next_cursor is not None and not isinstance(next_cursor, str):
                        raise ValueError("invalid bookmark")
                else:
                    resource = obj["resource_response"]
                    data_obj = resource["data"]
                    pins = data_obj.get("results", [])
                    next_cursor = resource.get("bookmark")
                if not isinstance(pins, list):
                    raise ValueError("results is not a list")
                if next_cursor is not None and not isinstance(next_cursor, str):
                    raise ValueError('invalid bookmark')
            except (TypeError, KeyError, AttributeError, ValueError) as exc:
                raise PinterestError("Malformed Pinterest response.") from exc
            self._retried_cursors.add(cursor)
            for pin in pins:
                entry = self._visual_entry(pin) if self._mode == "visual" else self._entry(pin)
                if entry and entry["id"] not in self._seen:
                    self._seen.add(entry["id"])
                    if self._mode == "keyword":
                        entry["_pin"] = {'images': pin.get('images', {})}
                    self._pending.append(entry)
            if next_cursor == "-end-" or not next_cursor:
                self._ended = True
                self._cursor = None
            elif next_cursor == cursor:
                self._ended = True
            else:
                self._cursor = next_cursor

    def _request(self, request):
        check_cancelled()
        if self._transport is not None:
            result = self._transport(request, self.TIMEOUT, self.proxy)
            if isinstance(result, bytes):
                if len(result) > self.MAX_BYTES:
                    raise PinterestError("Pinterest response exceeded 8 MiB limit.")
                return result
            if hasattr(result, "read"):
                return self._read_bounded(result)
            raise PinterestError("Invalid Pinterest transport response.")
        return request_bytes(request, timeout=self.TIMEOUT, limit=self.MAX_BYTES, proxy=self.proxy)

    def _visual_request(self, cursor):
        boundary = '----ImageSearch' + uuid.uuid4().hex
        chunks = []
        for name, value in (("x", "0"), ("y", "0"), ("w", "1"), ("h", "1"), ("page_size", "25")):
            chunks.extend((b"--" + boundary.encode() + b"\r\n",
                           ('Content-Disposition: form-data; name="%s"\r\n\r\n' % name).encode(),
                           value.encode(), b"\r\n"))
        chunks.extend((b"--" + boundary.encode() + b"\r\n",
                       b'Content-Disposition: form-data; name="image"; filename="image.jpg"\r\n',
                       b"Content-Type: image/jpeg\r\n\r\n", self._image_bytes, b"\r\n",
                       b"--" + boundary.encode() + b"--\r\n"))
        url = "https://api.pinterest.com/v3/visual_search/extension/image/"
        if cursor is not None:
            url += "?" + urllib.parse.urlencode({"bookmark": cursor})
        return urllib.request.Request(url, data=b"".join(chunks), method="PUT", headers={
            "Content-Type": "multipart/form-data; boundary=" + boundary,
            "Accept": "application/json", "User-Agent": self.USER_AGENT,
        })

    def _visual_entry(self, pin):
        if not isinstance(pin, dict):
            return None
        pid = str(pin.get("id", ""))
        medium, large = pin.get("image_medium_url"), pin.get("image_large_url")
        if not self._safe_id(pid) or not self._safe_image(medium) or not self._safe_image(large):
            return None
        lsize = pin.get('image_large_size_pixels')
        if not isinstance(lsize, dict):
            lsize = {}
        title = self._text(pin.get("title") or pin.get("description") or "")
        entry = {"id": pid, "title": title, "thumbnail": medium,
                 "detail_url": "https://www.pinterest.com/pin/%s/" % pid,
                 "source": "pinterest", "image_url": large,
                 "width": lsize.get("width"), "height": lsize.get("height"),
                 "_pin": {"images": {"orig": {"url": large, "width": lsize.get("width"), "height": lsize.get("height")}}}}
        link = pin.get("link")
        if isinstance(link, str) and link:
            entry["source_url"] = link
            entry["website_url"] = link
        if isinstance(pin.get("description"), str) and pin["description"]:
            entry["description"] = pin["description"]
        return entry

    @staticmethod
    def _safe_id(pid):
        return bool(re.fullmatch(r'(?:[0-9]{1,64}|e1_[A-Za-z0-9_-]{1,1024})', pid))

    @staticmethod
    def _safe_image(url):
        return isinstance(url, str) and url.startswith("https://i.pinimg.com/")

    def _read_bounded(self, response):
        content = response.read(self.MAX_BYTES + 1)
        if len(content) > self.MAX_BYTES:
            raise PinterestError("Pinterest response exceeded 8 MiB limit.")
        return content

    def _entry(self, pin):
        if not isinstance(pin, dict):
            return None
        pid = str(pin.get("id", ""))
        if not self._safe_id(pid):
            return None
        title = self._text(pin.get("title") or pin.get("grid_title") or pin.get("description") or "")
        url, width, height = self._image(pin)
        if not url:
            return None
        thumbnail = url
        for size in ('236x','474x','170x','736x'):
            candidate = pin.get('images',{}).get(size,{})
            small = candidate.get('url') if isinstance(candidate,dict) else None
            if isinstance(small,str) and small.startswith('https://i.pinimg.com/'):
                thumbnail = small
                break
        entry = {"id": pid, "title": title, "thumbnail": thumbnail,
                "detail_url": "https://www.pinterest.com/pin/%s/" % pid,
                "source": "pinterest", "image_url": url, "width": width, "height": height}
        link = pin.get('link')
        if isinstance(link, str) and link:
            entry['website_url'] = link
            entry['source_url'] = link
        description = self._text(pin.get('description'))
        if description:
            entry['description'] = description
        return entry

    @staticmethod
    def _text(value):
        if isinstance(value, dict):
            value = value.get("text", "")
        return str(value or "")

    @staticmethod
    def _image(pin):
        images = pin.get("images") or {}
        if not isinstance(images, dict):
            return None, None, None
        candidates = []
        orig = images.get("orig")
        if isinstance(orig, dict):
            candidates.append(orig)
        for item in images.values():
            if isinstance(item, dict) and item not in candidates:
                candidates.append(item)
        for candidate in candidates:
            url = candidate.get("url")
            if isinstance(url, str) and url.startswith("https://i.pinimg.com/"):
                return url, candidate.get("width"), candidate.get("height")
        return None, None, None

    def resolve(self, entry):
        if not isinstance(entry, dict):
            return None
        pin = entry.get("_pin")
        if not isinstance(pin, dict):
            return None
        url, _, _ = self._image(pin)
        if not url:
            return None
        return {"url": url, "referer": "https://www.pinterest.com/", "title": entry.get("title", "")}
