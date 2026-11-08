import test_docker as fixture
from test_grid_menu import finish

M = fixture.MODULE


def test_loading_status_uses_the_existing_button_row_without_moving_grid():
    p = M.ImageSearchDocker(browser=object())
    p.resize(900, 600)
    p.show()
    try:
        fixture.APP.processEvents()
        before = p.grid.geometry()
        p.status.setText('正在搜索…')
        fixture.APP.processEvents()
        assert p.grid.geometry() == before, 'Showing status added a row and moved the image grid'
        assert p.status.geometry().top() > p.grid.geometry().bottom()
        assert p.favorite_tabs.geometry().right() < p.status.geometry().left()
        assert p.status.width() == 22
        p.status.clear()
        fixture.APP.processEvents()
        assert p.grid.geometry() == before
        assert p.status.isHidden()
    finally:
        finish(p)


def test_long_errors_remain_single_line_with_complete_tooltip():
    p = M.ImageSearchDocker(browser=object())
    p.resize(640, 600)
    p.show()
    try:
        fixture.APP.processEvents()
        before = (p.size(), p.grid.geometry())
        text = '失败：' + '服务器暂时无法连接，请稍后重试。' * 80
        p.status.setText(text)
        fixture.APP.processEvents()
        assert (p.size(), p.grid.geometry()) == before, 'Long status resized the panel or grid'
        assert not p.status.wordWrap()
        assert p.status.toolTip() == text
        assert p.status.geometry().right() <= p.widget().width()
    finally:
        finish(p)
