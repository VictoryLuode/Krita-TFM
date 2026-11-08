import importlib.util
from pathlib import Path
from unittest.mock import Mock


def load_backend():
    path = Path(__file__).parents[1]/'pykrita/quick_image_search/backend.py'
    assert path.exists(), 'Source routing backend is missing'
    spec=importlib.util.spec_from_file_location('routing_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.Backend


def test_pinterest_search_never_starts_google():
    Backend=load_backend()
    google=Mock();pinterest=Mock()
    pinterest.search.return_value=[{'source':'pinterest','id':'1'}]
    backend=Backend(google=google,pinterest=pinterest)
    backend.start('C:/test-profile',proxy='http://127.0.0.1:7890')
    assert backend.search('pinterest','concrete',limit=24)==[{'source':'pinterest','id':'1'}]
    google.start.assert_not_called()
    pinterest.start.assert_called_once()
    backend.resolve({'source':'pinterest','id':'1'})
    google.resolve.assert_not_called()


def test_google_search_and_more_always_request_headless():
    Backend=load_backend()
    google=Mock();pinterest=Mock()
    backend=Backend(google=google,pinterest=pinterest)
    backend.start('C:/test-profile',proxy='http://127.0.0.1:7890')
    google.start.assert_not_called()
    backend.search('google','concrete',limit=24)
    assert google.start.call_args.kwargs['headless'] is True
    assert google.start.call_args.args[0].endswith('test-profile-background')
    backend.more('google',limit=24)
    google.more.assert_called_once_with('google',limit=24)
    google.has_more.return_value=True
    assert backend.has_more('google') is True
    pinterest.start.assert_not_called()


def test_validation_window_requires_explicit_show_and_cleanup_closes_created_drivers():
    Backend=load_backend()
    google=Mock();pinterest=Mock()
    backend=Backend(google=google,pinterest=pinterest)
    backend.start('C:/test-profile')
    backend.search('google','concrete')
    google.show.assert_not_called()
    backend.show()
    google.show.assert_called_once()
    backend.close()
    google.close.assert_called_once()
    pinterest.close.assert_called_once()


def test_scroll_cannot_close_a_manual_verification_window():
    import pytest
    Backend=load_backend()
    google=Mock()
    backend=Backend(google=google)
    backend.start('C:/test-profile')
    backend.search('google','concrete')
    backend.show()
    before=google.start.call_count
    with pytest.raises(ValueError,match='验证'):
        backend.more('google')
    assert google.start.call_count==before
    backend.search('google','concrete')
    assert google.start.call_count==before+1


def test_similar_always_routes_to_pinterest_without_starting_google():
    Backend=load_backend()
    google=Mock();pinterest=Mock()
    backend=Backend(google=google,pinterest=pinterest)
    backend.start('C:/test-profile')
    pinterest.similar.return_value=[{'source':'pinterest','id':'9'}]
    assert backend.similar(b'image',limit=24)==[{'source':'pinterest','id':'9'}]
    pinterest.similar.assert_called_once_with(b'image',limit=24)
    google.start.assert_not_called()
