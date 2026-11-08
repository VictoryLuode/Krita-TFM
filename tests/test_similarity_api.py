import importlib.util
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

MODULE = Path(__file__).parents[1] / "pykrita" / "quick_image_search" / "pinterest.py"
spec = importlib.util.spec_from_file_location("pinterest_similarity", MODULE)
pinterest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pinterest)


def pin(pid):
    return {"id": str(pid), "title": "visual", "description": "provided", "link": "https://site.test/item", "domain": "site.test", "image_medium_url": f"https://i.pinimg.com/474x/{pid}.jpg", "image_medium_size_pixels": {"width": 474, "height": 600}, "image_large_url": f"https://i.pinimg.com/originals/{pid}.jpg", "image_large_size_pixels": {"width": 1200, "height": 1600}}


def response(items, bookmark):
    return json.dumps({"status": "success", "data": items, "bookmark": bookmark}).encode()


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, request, timeout, proxy):
        self.calls.append(request)
        return self.responses.pop(0)


def client(responses):
    transport = Transport(responses)
    return pinterest.Pinterest(transport=transport), transport


def test_visual_multipart_contract_and_visual_cursor_paging():
    c, t = client([response([pin(1), pin(2)], "visual-cursor"), response([pin(3)], "-end-")])
    first = c.similar(b"JPEG-IMAGE", 1)
    assert first[0]["id"] == "1"
    request = t.calls[0]
    assert request.get_method() == "PUT"
    assert request.full_url == "https://api.pinterest.com/v3/visual_search/extension/image/"
    body = request.data
    assert b'Content-Disposition: form-data; name="image"; filename="image.jpg"' in body
    assert b"JPEG-IMAGE" in body
    assert b'name="x"\r\n\r\n0' in body and b'name="y"\r\n\r\n0' in body
    assert b'name="w"\r\n\r\n1' in body and b'name="h"\r\n\r\n1' in body
    assert b'name="page_size"\r\n\r\n25' in body
    assert c.more("pinterest", 24)[0]["id"] == "2"
    assert c.more("pinterest", 24)[0]["id"] == "3"
    query = parse_qs(urlparse(t.calls[1].full_url).query)
    assert query == {"bookmark": ["visual-cursor"]}
    assert b"JPEG-IMAGE" in t.calls[1].data


def test_visual_buffer_dedup_and_resolve_large_image_and_metadata():
    c, _ = client([response([pin(1), pin(1), pin(2)], "next")])
    entries = c.similar(b"image", 1)
    assert [x["id"] for x in entries] == ["1"]
    assert c.more("pinterest", 24)[0]["id"] == "2"
    entry = entries[0]
    assert entry["thumbnail"] == "https://i.pinimg.com/474x/1.jpg"
    assert entry["source_url"] == "https://site.test/item"
    assert entry["website_url"] == "https://site.test/item"
    assert entry["description"] == "provided"
    assert c.resolve(entry)["url"] == "https://i.pinimg.com/originals/1.jpg"


def test_similarity_rejects_invalid_image_bytes():
    c, t = client([])
    for invalid in (b"", "image", None, b"x" * (8 * 1024 * 1024 + 1)):
        with pytest.raises(pinterest.PinterestError):
            c.similar(invalid)
    assert not t.calls


def test_switching_visual_to_keyword_resets_mode_and_cursor():
    keyword = {"resource_response": {"data": {"results": [{"id": "9", "title": "keyword", "images": {"orig": {"url": "https://i.pinimg.com/orig.jpg", "width": 1, "height": 1}}}]}, "bookmark": None}}
    c, t = client([response([pin(1)], "visual-cursor"), json.dumps(keyword).encode()])
    assert c.similar(b"image", 1)[0]["id"] == "1"
    assert c.search("pinterest", "cats", 1)[0]["id"] == "9"
    assert "api.pinterest.com/v3/visual_search" in t.calls[0].full_url
    assert "resource/BaseSearchResource/get/" in t.calls[1].full_url
    assert c.more() == []


def test_empty_intermediate_visual_page_can_advance_to_a_new_cursor():
    c,t=client([response([], 'next'),response([pin(2)],'-end-')])
    assert c.similar(b'image',1)[0]['id']=='2'
    assert len(t.calls)==2


def test_keyword_results_keep_real_source_link_and_description():
    item={'id':'1','title':'Concrete','link':'https://site.test/original','description':'Actual description','images':{'orig':{'url':'https://i.pinimg.com/originals/1.jpg','width':800,'height':600}}}
    c,t=client([json.dumps({'resource_response':{'data':{'results':[item]},'bookmark':None}}).encode()])
    result=c.search('pinterest','concrete',1)[0]
    assert result['website_url']=='https://site.test/original'
    assert result['description']=='Actual description'


def test_invalid_size_metadata_does_not_crash_valid_image_results():
    item=pin(1);item['image_large_size_pixels']='unknown'
    c,t=client([response([item],'-end-')])
    assert c.similar(b'image',1)[0]['image_url']==item['image_large_url']


def test_malformed_visual_response_is_reported():
    c, _ = client([b'{"status":"success","data":"bad"}'])
    with pytest.raises(pinterest.PinterestError, match="Malformed"):
        c.similar(b"image")
