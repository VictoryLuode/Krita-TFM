from unittest.mock import patch
import test_docker as fixture


def test_pinterest_never_enables_a_browser_window_button():
    panel=fixture.MODULE.ImageSearchDocker()
    panel.source.setCurrentIndex(1)
    panel.status.setText('失败：Provider requires verification or login')
    menu = panel.build_status_menu()
    assert len(menu.actions()) == 1  # Profile reset is independent of provider.
    assert not panel.verify_button.isEnabled()
    menu.deleteLater()
    import time
    from qt_test_binding import QTest
    panel.run_job(lambda job: None, lambda result: None)
    deadline=time.monotonic()+2
    while panel.busy and time.monotonic()<deadline:
        QTest.qWait(10)
    assert not panel.busy
    menu = panel.build_status_menu()
    assert len(menu.actions()) == 1
    assert not panel.verify_button.isEnabled()
    menu.deleteLater()
    panel.source.setCurrentIndex(0)
    menu = panel.build_status_menu()
    assert menu.actions()[0].isEnabled()
    menu.deleteLater()
    panel.shutdown()
    panel.deleteLater()


def test_creating_default_backend_does_not_launch_chrome():
    import subprocess
    panel=fixture.MODULE.ImageSearchDocker()
    with patch.object(subprocess,'Popen') as spawn, patch(fixture.MODULE.__package__+'.browser.Browser.start'):
        backend=panel.get_browser()
    spawn.assert_not_called()
    assert type(backend).__name__=='Backend'
    panel.deleteLater()
