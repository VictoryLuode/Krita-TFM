from unittest.mock import patch
from unittest.mock import Mock
import pytest
import test_browser as fixture


def test_background_browser_launch_has_no_visible_window():
    module = fixture._BROWSER
    browser = module.Browser(port=9236, headless=True)
    with patch.object(browser, '_endpoint_ready', side_effect=[False, True]), patch.object(module, '_chrome_executable', return_value='chrome.exe'), patch.object(module.subprocess, 'Popen') as spawn, patch.object(module.Path, 'mkdir'):
        browser.start('C:/isolated-background', proxy='http://127.0.0.1:7890')
    args = spawn.call_args.args[0]
    assert '--headless=new' in args
    assert '--remote-debugging-port=9236' in args
    assert '--window-size=1280,1000' in args
    if module.os.name == 'nt':
        assert spawn.call_args.kwargs['startupinfo'].wShowWindow == 0


def test_headless_refuses_to_reuse_a_visible_browser():
    module = fixture._BROWSER
    browser = module.Browser(port=9236, headless=True)
    browser._is_headless_endpoint = lambda: False
    with patch.object(browser, '_endpoint_ready', return_value=True), patch.object(module.subprocess, 'Popen') as spawn:
        with pytest.raises(module.BrowserUnavailable):
            browser.start('C:/isolated-background')
    spawn.assert_not_called()


def test_close_stops_only_the_process_this_backend_started():
    browser = fixture._BROWSER.Browser(port=9236, headless=True)
    process = Mock()
    browser._process = process
    calls = []
    browser._command = lambda method, *args, **kwargs: calls.append(method) or {}
    browser.close()
    assert 'Browser.close' in calls
    process.wait.assert_called()
    assert browser._process is None


def test_only_explicit_show_switches_background_to_visible_verification():
    browser = fixture._BROWSER.Browser(port=9236, headless=True)
    browser._profile_dir = 'C:/isolated-background'
    browser._proxy = ''
    browser._paging = {'google': {'query': 'concrete texture'}}
    browser._targets = {'google': 'target'}
    browser._ensure_tab = lambda source: 'session'
    browser._navigate = Mock()
    browser._command = lambda method, *args, **kwargs: {'windowId': 7}
    def start(profile, proxy='', headless=None):
        browser.headless = headless
        browser._targets['google'] = 'target'
    with patch.object(browser, 'start', side_effect=start) as spawn:
        browser.show()
    spawn.assert_called_once_with('C:/isolated-background', '', headless=False)
    assert browser._navigate.call_args.args[1].startswith('https://www.google.com/search?')


def test_switching_mode_closes_only_owned_browser_before_restart():
    module = fixture._BROWSER
    browser = module.Browser(port=9236, headless=True)
    browser._process = Mock()
    with patch.object(browser, '_endpoint_ready', side_effect=[True, True]), patch.object(browser, 'close') as close, patch.object(module, '_chrome_executable', return_value='chrome.exe'), patch.object(module.subprocess, 'Popen') as spawn, patch.object(module.Path, 'mkdir'):
        browser.start('C:/isolated-background', headless=False)
    close.assert_called_once()
    assert '--headless=new' not in spawn.call_args.args[0]


def test_verification_keeps_query_and_never_automatically_shows_window():
    module=fixture._BROWSER
    browser=module.Browser(port=9236,headless=True)
    browser._ensure_tab=lambda source:'session'
    browser._navigate=Mock()
    browser._evaluate=lambda *args:{'challenge':True,'href':'https://www.google.com/sorry/index'}
    with patch.object(browser,'show') as show:
        with pytest.raises(module.VerificationRequired):
            browser.search('google','concrete texture')
    show.assert_not_called()
    assert browser._paging['google']['query']=='concrete texture'
