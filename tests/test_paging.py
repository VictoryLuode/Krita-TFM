import importlib.util
import pathlib
import sys

_MODULE = pathlib.Path(__file__).parents[1] / "pykrita" / "quick_image_search" / "browser.py"
_SPEC = importlib.util.spec_from_file_location("browser_paging_test", _MODULE)
_BROWSER = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _BROWSER
_SPEC.loader.exec_module(_BROWSER)
Browser = _BROWSER.Browser


def entry(n, source="pinterest"):
    return {"title": str(n), "thumbnail": f"https://i.pinimg.com/236x/{n}.jpg",
            "detail_url": f"https://www.pinterest.com/pin/{n}/", "source": source, "id": str(n)}


def test_search_and_more_deduplicate_successive_batches():
    b = Browser()
    b._ensure_tab = lambda source: "session"
    b._navigate = lambda *args: None
    b._evaluate = lambda *args: {"items": [entry(1), entry(2), entry(1)]}
    first = b.search("pinterest", "cats", 1)
    assert len(first) == 1 and first[0]["title"] == "1"
    b._evaluate = lambda *args: {"items": [entry(1), entry(2), entry(3)]}
    batch = b.more("pinterest", 2)
    assert [x["title"] for x in batch] == ["2", "3"]


def test_new_query_resets_seen_and_paginates_dom_without_navigation():
    b = Browser()
    b._ensure_tab = lambda source: "session"
    navigations = []
    b._navigate = lambda *args: navigations.append(args)
    b._evaluate = lambda *args: {"items": [entry(1), entry(2)]}
    assert len(b.search("pinterest", "cats", 1)) == 1
    assert len(b.more("pinterest", 1)) == 1
    assert len(navigations) == 1
    assert len(b.search("pinterest", "dogs", 1)) == 1


def test_resolve_pinterest_uses_separate_detail_tab():
    b = Browser()
    b._targets["pinterest"] = "search-target"
    b._sessions["pinterest"] = "search-session"
    made = []
    def command(method, params=None, session=None):
        if method == "Target.createTarget":
            made.append(params["url"]); return {"targetId": "detail-target"}
        if method == "Target.attachToTarget": return {"sessionId": "detail-session"}
        return {}
    b._command = command
    b._evaluate = lambda *args: {"url": "https://i.pinimg.com/originals/x.jpg", "href": "https://www.pinterest.com/pin/1/"}
    b._navigate = lambda session, url: made.append((session, url))
    result = b.resolve(entry(1))
    assert result["url"].endswith("originals/x.jpg")
    assert b._targets["pinterest"] == "search-target"
    assert made[0] == "about:blank"


def test_exhaustion_and_unsupported_source():
    b = Browser()
    assert b.has_more("unknown") is False
    b._ensure_tab = lambda source: "session"
    b._navigate = lambda *args: None
    b._evaluate = lambda *args: {"items": [entry(1)]}
    assert len(b.search("pinterest", "cats", 24)) == 1
    assert b.has_more("pinterest") is True
    b._evaluate = lambda *args: {"items": [], "end": True}
    assert b.more("pinterest") == []
    assert b.has_more("pinterest") is False


def test_sparse_first_batch_does_not_disable_scrolling():
    b = Browser()
    b._ensure_tab = lambda source: 'session'
    b._navigate = lambda *args: None
    b._evaluate = lambda *args: {'items': [entry(1)]}
    assert len(b.search('pinterest', 'concrete', 24)) == 1
    assert b.has_more('pinterest')
    b._evaluate = lambda *args: {'items': [entry(1), entry(2)], 'end': False}
    assert [e['title'] for e in b.more('pinterest', 24)] == ['2']


def test_pinterest_thumbnail_size_change_is_not_a_new_image():
    b = Browser()
    b._ensure_tab = lambda source: 'session'
    b._navigate = lambda *args: None
    b._evaluate = lambda *args: {'items': [entry(1)]}
    b.search('pinterest', 'concrete', 1)
    resized = entry(1)
    resized['thumbnail'] = resized['thumbnail'].replace('/236x/', '/474x/')
    b._evaluate = lambda *args: {'items': [resized, entry(2)]}
    assert [e['title'] for e in b.more('pinterest', 1)] == ['2']


def test_google_preview_restores_search_scroll_position():
    b = Browser()
    b._ensure_tab = lambda source: 'session'
    b._command = lambda *args, **kwargs: {}
    restored = []
    def evaluate(session, script):
        if 'scrollIntoView' in script: return {'x': 30, 'y': 40}
        if 'scrollTo' in script:
            restored.append(script)
            return True
        if 'scrollX' in script: return {'x': 0, 'y': 1500}
        return {'href': 'https://www.google.com/search?q=concrete', 'url': 'https://cdn.test/image.png'}
    b._evaluate = evaluate
    b.resolve({'source':'google','title':'Concrete','thumbnail':'https://encrypted-tbn0.gstatic.com/images?q=x','detail_url':'https://www.google.com/search?q=concrete'})
    assert restored and '1500' in restored[0]
