from i18n import tr
from types import SimpleNamespace
from qt_test_binding import Qt
from qt_test_binding import QImage
from test_search_history_ui import panel, wait, finish


def test_preview_context_import_uses_captured_native_target_without_clipboard_or_research(tmp_path):
    p = panel(tmp_path)
    try:
        p.search_input.setText('cat')
        p.search()
        wait(p)
        p.browser.resolve = lambda entry: {'url': 'https://example.com/original'}
        p.grid.setCurrentRow(0)
        wait(p)
        p.preview()
        calls = []
        target = object()
        p.drop_router = SimpleNamespace(current_import_target=lambda: target,
                                      import_file=lambda path, mode, destination: calls.append((path, mode, destination)))
        menu = p.build_preview_menu()
        assert [a.text() for a in menu.actions()] == [tr('Insert as layer', '插入为图层'), tr('Insert as reference', '插入为参考图')]
        assert all(a.isEnabled() for a in menu.actions())
        menu.actions()[1].trigger()
        assert len(calls) == 1 and calls[0][1:] == ('reference', target)
        assert not p.preview_dialog.isVisible()
        menu.deleteLater()
    finally:
        finish(p)


def test_preview_import_is_disabled_without_document_and_while_loading(tmp_path):
    p = panel(tmp_path)
    try:
        def no_document():
            raise ValueError('请先打开文档')
        p.drop_router = SimpleNamespace(current_import_target=no_document)
        menu = p.build_preview_menu()
        assert all(not a.isEnabled() for a in menu.actions())
        assert all('文档' in a.toolTip() for a in menu.actions())
        menu.deleteLater()
    finally:
        finish(p)
