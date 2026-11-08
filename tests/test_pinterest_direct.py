import importlib.util
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

MODULE = Path(__file__).parents[1] / "pykrita" / "quick_image_search" / "pinterest.py"
spec = importlib.util.spec_from_file_location("pinterest_direct", MODULE)
pinterest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pinterest)


def pin(pid, url=None, title="Pin"):
    image = url or f"https://i.pinimg.com/736x/aa/bb/{pid}.jpg"
    return {"id": str(pid), "title": title, "images": {"orig": {"url": image, "width": 735, "height": 1307}}}


def payload(pins, cursor=None):
    return {"resource_response": {"data": {"results": pins}, "bookmark": cursor}}


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, request, timeout, proxy):
        self.calls.append((request, timeout, proxy))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response,bytes):
            return response
        return json.dumps(response).encode()


def instance(responses):
    transport = Transport(responses)
    client = pinterest.Pinterest(transport=transport)
    client.start(proxy="http://proxy.test:8080")
    return client, transport


def test_request_contract_and_limit_retains_pending_entries():
    pins = [pin(i) for i in range(1, 26)]
    client, transport = instance([payload(pins, "next")])
    first = client.search("pinterest", "red fox & snow", 24)
    assert len(first) == 24
    request, timeout, proxy = transport.calls[0]
    assert request.get_header("X-pinterest-pws-handler") == "www/[username]/search/pins.js"
    assert request.get_header("Accept") == "application/json"
    assert request.get_header("Referer") == "https://www.pinterest.com/"
    from urllib.parse import urlparse, parse_qs
    query = parse_qs(urlparse(request.full_url).query)
    assert query["source_url"] == ["/search/pins/?q=red%20fox%20%26%20snow"]
    assert json.loads(query["data"][0]) == {"options": {"query": "red fox & snow", "scope": "pins", "page_size": 25, "bookmarks": []}, "context": {}}
    assert timeout == 20 and proxy == "http://proxy.test:8080"
    assert [x["id"] for x in client.more()] == ["25"]


def test_provider_opaque_ids_are_preserved_not_rejected_or_decoded():
    opaque = 'e1_AfqPShwqRdr2xnKxkI1hRQk9X2m7cp9tGBl-n-VOMO3dmd-6ZyAs'
    client, transport = instance([payload([pin(opaque)], '-end-')])
    result = client.search('pinterest', 'concrete texture', 1)
    assert len(result) == 1 and result[0]['id'] == opaque
    assert result[0]['detail_url'] == 'https://www.pinterest.com/pin/' + opaque + '/'
    for bad in ('e1_../escape', '123/evil', 'e1_?', 'abc'):
        assert client._entry(pin(bad)) is None


def test_seen_paging_reset_cursor_end_and_no_new_ids_bounded():
    client, transport = instance([payload([pin(1)], "a"), payload([pin(1)], "-end-")])
    assert [x["id"] for x in client.search("pinterest", "q", 24)] == ["1"]
    assert not client.has_more()
    assert client.more() == []
    assert len(transport.calls) == 2


def test_cursor_without_cursor_exhausts_and_wrong_source_refused():
    client, _ = instance([payload([pin(2)])])
    assert client.search("pinterest", "q", 24)[0]["id"] == "2"
    assert not client.has_more()
    with pytest.raises(pinterest.PinterestError):
        client.search("google", "q", 24)


def test_malformed_oversized_and_http_forbidden_errors():
    client, _ = instance([b"not-json"])
    with pytest.raises(pinterest.PinterestError):
        client.search("pinterest", "q", 24)
    client, _ = instance([b"x" * (8 * 1024 * 1024 + 1)])
    with pytest.raises(pinterest.PinterestError):
        client.search("pinterest", "q", 24)
    err = HTTPError("https://www.pinterest.com", 403, "Forbidden", {}, None)
    client, _ = instance([err])
    with pytest.raises(pinterest.PinterestVerificationRequired, match="403"):
        client.search("pinterest", "q", 24)


def test_resolve_uses_server_orig_without_network_and_safe_fallback():
    client, transport = instance([])
    entry = {"id": "12345", "title": "x", "source": "pinterest", "detail_url": "https://www.pinterest.com/pin/12345/", "image_url": "https://i.pinimg.com/originals/fake.jpg"}
    result = client.resolve({**entry, "_pin": pin("12345", "https://i.pinimg.com/736x/real.jpg")})
    assert result["url"] == "https://i.pinimg.com/736x/real.jpg"
    assert result["referer"] == "https://www.pinterest.com/"
    assert not transport.calls
    assert client.resolve(entry) is None
    with pytest.raises(pinterest.PinterestError, match="browser"):
        client.show()


def test_repeating_search_restarts_at_first_page_not_next_page():
    client,transport=instance([payload([pin(1)],'next'),payload([pin(1)],'next')])
    assert client.search('pinterest','same',1)[0]['id']=='1'
    assert client.search('pinterest','same',1)[0]['id']=='1'
    assert len(transport.calls)==2


def test_cards_download_small_thumbnail_but_resolve_exact_orig():
    item=pin(1)
    item['images']['236x']={'url':'https://i.pinimg.com/236x/small.jpg','width':236,'height':419}
    client,transport=instance([payload([item])])
    entry=client.search('pinterest','q',1)[0]
    assert entry['thumbnail']=='https://i.pinimg.com/236x/small.jpg'
    assert client.resolve(entry)['url']==item['images']['orig']['url']


def test_invalid_result_shape_uses_backend_error():
    client,_=instance([{'resource_response':{'data':{'results':'invalid'}}}])
    with pytest.raises(pinterest.PinterestError):
        client.search('pinterest','q')
