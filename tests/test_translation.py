import threading
import time
import io
import json
import types
import urllib.parse
import pytest

import test_docker as fixture
from test_grid_menu import finish
from qt_test_binding import QTest

M = fixture.MODULE


def wait_for(predicate):
    end = time.monotonic() + 3
    while time.monotonic() < end:
        QTest.qWait(10)
        if predicate():
            return
    assert predicate(), 'Translation did not complete'


def test_explicit_translation_replaces_only_query_without_searching(monkeypatch):
    calls = []
    p = M.ImageSearchDocker(browser=types.SimpleNamespace(search=lambda *args, **kwargs: calls.append('unexpected search')))
    try:
        assert hasattr(p, 'translate_button'), 'Missing translation button beside the query'
        monkeypatch.setattr(M, 'translate_to_english', lambda text, proxy='': calls.append(text) or 'worn concrete wall')
        assert not p.translate_button.isEnabled()
        p.search_input.setText('concrete wall')
        assert not p.translate_button.isEnabled()
        p.search_input.setText('破旧的混凝土墙面')
        assert p.translate_button.isEnabled()
        assert not calls, 'Typing must not send keywords to a translation service'
        p.translate_button.click()
        wait_for(lambda: p.search_input.text() == 'worn concrete wall')
        assert calls == ['破旧的混凝土墙面']
        assert p.grid.count() == 0
        assert not p.busy, 'Translation must not occupy image-search busy state'
        p.search_input.undo()
        assert p.search_input.text() == '破旧的混凝土墙面'
    finally:
        finish(p)


def test_translation_request_uses_documented_english_pair_and_decodes_entities(monkeypatch):
    assert hasattr(M, 'translate_to_english'), 'Missing keyword translation client'
    calls = []
    payload = {'responseStatus': 200, 'responseData': {'translatedText': 'worn &amp; cracked wall'}}
    def open_request(request, timeout):
        calls.append((request.full_url, timeout))
        return io.BytesIO(json.dumps(payload).encode('utf-8'))
    monkeypatch.setattr(M.urllib.request, 'build_opener', lambda *handlers: types.SimpleNamespace(open=open_request))
    assert M.translate_to_english('破旧的混凝土墙面') == 'worn & cracked wall'
    url, timeout = calls[0]
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    assert urllib.parse.urlsplit(url).hostname == 'api.mymemory.translated.net'
    assert query['q'] == ['破旧的混凝土墙面']
    assert query['langpair'] == ['zh-CN|en']
    assert 0 < timeout <= 15


def test_query_keeps_readable_width_with_translation_at_minimum_panel_size():
    p = M.ImageSearchDocker(browser=object())
    try:
        p.resize(332, 600)
        p.show()
        fixture.APP.processEvents()
        assert p.search_input.width() >= 100, 'Translation squeezed the query below a readable width'
        for left, right in zip((p.source, p.search_input, p.translate_button),
                               (p.search_input, p.translate_button, p.search_button)):
            assert left.geometry().right() < right.geometry().left()
        assert p.search_button.geometry().right() < p.widget().width()
    finally:
        finish(p)


@pytest.mark.parametrize('revert', [False, True])
def test_delayed_translation_does_not_overwrite_intervening_edits(monkeypatch, revert):
    gate = threading.Event()
    p = M.ImageSearchDocker(browser=object())
    try:
        monkeypatch.setattr(M, 'translate_to_english', lambda *args: gate.wait(2) and 'old English result')
        p.search_input.setText('破旧墙面')
        p.translate_button.click()
        p.search_input.setText('新的关键词')
        if revert:
            p.search_input.setText('破旧墙面')
        expected = p.search_input.text()
        gate.set()
        wait_for(lambda: p._translation_job is None)
        assert p.search_input.text() == expected
        assert p.translate_button.isEnabled()
        assert p.status.isHidden()
    finally:
        gate.set()
        finish(p)


def test_failed_translation_preserves_chinese_and_successful_retry_clears_error(monkeypatch):
    p = M.ImageSearchDocker(browser=object())
    def fail(*args):
        raise TimeoutError('network timeout')
    try:
        monkeypatch.setattr(M, 'translate_to_english', fail)
        p.search_input.setText('墙面')
        p.translate_button.click()
        wait_for(lambda: p._translation_job is None)
        assert p.search_input.text() == '墙面'
        assert p.translate_button.isEnabled()
        assert '翻译失败' in p.status.text()
        monkeypatch.setattr(M, 'translate_to_english', lambda *args: 'wall')
        p.translate_button.click()
        wait_for(lambda: p._translation_job is None)
        assert p.search_input.text() == 'wall'
        assert p.status.isHidden(), 'Old translation failure survived a successful retry'
    finally:
        finish(p)


def test_translation_is_available_while_an_image_job_is_running(monkeypatch):
    gate = threading.Event()
    p = M.ImageSearchDocker(browser=object())
    try:
        monkeypatch.setattr(M, 'translate_to_english', lambda *args: 'wall')
        p.run_job(lambda job: gate.wait(2), lambda result: None, lock_grid=False)
        p.search_input.setText('墙面')
        assert p.translate_button.isEnabled()
        p.translate_button.click()
        wait_for(lambda: p._translation_job is None)
        assert p.search_input.text() == 'wall'
        assert p.busy, 'Translation completion must not unlock an unrelated image job'
        gate.set()
        wait_for(lambda: not p.busy)
    finally:
        gate.set()
        finish(p)


@pytest.mark.parametrize('payload', [b'<html>blocked</html>', b'[]', b'[[[null]]]', b'x' * 65537],
                         ids=['html', 'empty', 'null-segment', 'oversized'])
def test_invalid_translation_responses_are_reported_without_fake_text(monkeypatch, payload):
    monkeypatch.setattr(M.urllib.request, 'build_opener', lambda *handlers: types.SimpleNamespace(open=lambda *args, **kwargs: io.BytesIO(payload)))
    with pytest.raises(ValueError):
        M.translate_to_english('墙面')


def test_non_chinese_and_oversized_input_do_not_send_requests(monkeypatch):
    calls = []
    monkeypatch.setattr(M.urllib.request, 'build_opener', lambda *args: calls.append(True))
    assert M.translate_to_english('concrete wall') == 'concrete wall'
    assert M.translate_to_english('') == ''
    with pytest.raises(ValueError):
        M.translate_to_english('墙' * 200)
    assert not calls


def test_service_quota_message_must_not_be_used_as_a_translation(monkeypatch):
    payload = {'responseStatus': 429, 'quotaFinished': True,
               'responseData': {'translatedText': 'YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY'}}
    monkeypatch.setattr(M.urllib.request, 'build_opener', lambda *handlers: types.SimpleNamespace(open=lambda *args, **kwargs: io.BytesIO(json.dumps(payload).encode())))
    with pytest.raises(ValueError, match='额度'):
        M.translate_to_english('墙面')
