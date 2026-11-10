def main():
    import os
    import sys
    import types
    from pathlib import Path
    from unittest import mock
    import json
    import tempfile
    from host_runtime import configure
    app = configure()
    module = types.ModuleType('krita')
    class Extension:
        def __init__(self, parent): pass
    class FakeKrita:
        extensions = []
        def addExtension(self, extension): self.extensions.append(extension)
        def actions(self): return []
        def filters(self): return ['tfm_bloom']
        def readSetting(self, group, key, default): return default
    instance = FakeKrita()
    class Krita:
        @staticmethod
        def instance(): return instance
    module.Extension = Extension
    module.Krita = Krita
    module.Palette = type('Palette', (), {})
    sys.modules['krita'] = module
    import tfm
    from tfm.manager import ManagerDialog
    def make_manager():
        window = ManagerDialog()
        window._ensure_tab_page(0)
        window._ensure_tab_page(1)
        return window
    from tfm.menus import config as menu_config
    from tfm.filters import settings as filter_settings
    assert Path(menu_config.CONFIG_FILE) == Path(__file__).resolve().parents[1] / 'TFM' / 'config.json'
    assert Path(menu_config.SCRIPTS_DIR) == Path(__file__).resolve().parents[1] / 'TFM' / 'scripts'
    assert Path(menu_config.bundled_scripts_dir()) / 'luminosity_view.py' == Path(__file__).resolve().parents[1] / 'pykrita' / 'tfm' / 'scripts' / 'luminosity_view.py'
    assert (Path(menu_config.bundled_scripts_dir()) / 'luminosity_view.py').is_file()
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR') or tempfile.gettempdir()) as tmp:
        user_scripts = Path(tmp) / 'user-scripts'
        bundled_scripts = Path(tmp) / 'plugin' / 'scripts'
        bundled_scripts.mkdir(parents=True)
        user_scripts.mkdir(parents=True)
        (bundled_scripts / 'luminosity_view.py').write_text('bundled = True', encoding='utf-8')
        (user_scripts / 'custom.py').write_text('custom = True', encoding='utf-8')
        with mock.patch.object(menu_config, 'SCRIPTS_DIR', str(user_scripts)), \
             mock.patch.object(menu_config, 'PLUGIN_DIR', str(Path(tmp) / 'plugin' / 'menus')):
            names = [name for name, _ in menu_config.list_scripts()]
            assert names == ['custom.py', 'luminosity_view.py']
            assert menu_config.read_script('luminosity_view.py') == 'bundled = True'
            assert menu_config.read_script('custom.py') == 'custom = True'
            assert menu_config.rename_script('custom.py', 'luminosity_view.py') == ''
            assert (user_scripts / 'custom.py').read_text() == 'custom = True'
            assert not menu_config.delete_script('luminosity_view.py')
            assert (bundled_scripts / 'luminosity_view.py').is_file()
            (user_scripts / 'luminosity_view.py').write_text('user = True', encoding='utf-8')
            assert menu_config.read_script('luminosity_view.py') == 'user = True'
    from unittest import mock
    import json
    import tempfile
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR') or tempfile.gettempdir()) as tmp:
        config_file = Path(tmp) / 'config.json'
        original = {'unknown': {'keep': True}, 'overrides': {'A': [{'id': 'x'}]},
                    'last_identity': ['test'], 'lists': [{'name': 'A', 'items': ['old']}]}
        config_file.write_text(json.dumps(original), encoding='utf-8')
        with mock.patch.object(menu_config, 'CONFIG_FILE', str(config_file)):
            for invalid in ('[]', 'null', '{broken'):
                config_file.write_text(invalid, encoding='utf-8')
                assert menu_config.load_last_identity() is None
                if invalid != '{broken':
                    assert isinstance(menu_config.load_config()[1], list)
                assert not menu_config.save_config('', [])
                assert not menu_config.save_last_identity(('x',))
                assert not menu_config.add_overrides('A', [])
                assert menu_config.pop_overrides('A') is None
                assert config_file.read_text(encoding='utf-8') == invalid
            config_file.write_text(json.dumps(original), encoding='utf-8')
            with mock.patch.object(menu_config.os, 'replace', side_effect=OSError('identity failure')):
                assert not menu_config.save_last_identity(('x',))
            assert json.loads(config_file.read_text(encoding='utf-8')) == original
            assert menu_config.save_config('', [{'name': 'A', 'items': [{'id': 'new', 'label': ''}]}])
            result = json.loads(config_file.read_text(encoding='utf-8'))
            with mock.patch.object(menu_config.os, 'replace', side_effect=OSError('simulated failure')):
                assert not menu_config.save_config('', [{'name': 'B', 'items': []}])
            assert json.loads(config_file.read_text(encoding='utf-8')) == result
            assert sorted(p.name for p in config_file.parent.iterdir()) == ['config.json']
            assert menu_config.save_config('Ctrl+Q', [])
            assert menu_config.load_config() == ('Ctrl+Q', [])
            with mock.patch('tfm.menus.dialog.load_config', return_value=menu_config.load_config()):
                empty_window = make_manager()
                assert empty_window.menu_page.lists == []
                empty_window.close()
            config_file.write_text('{}', encoding='utf-8')
            assert menu_config.load_config()[1]
        assert result['unknown'] == original['unknown']
        assert result['overrides'] == original['overrides']
        assert result['last_identity'] == original['last_identity']
        assert result['lists'][0]['items'] == ['new']
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR') or tempfile.gettempdir()) as tmp:
        settings_file = Path(tmp) / 'settings.json'
        with mock.patch.object(filter_settings, '_config_path', return_value=str(settings_file)), \
             mock.patch.object(filter_settings, '_legacy_paths', return_value=[]):
            assert filter_settings.save({'managed_filters': ['tfm_bloom'], 'enabled_filters': ['tfm_bloom']})
            saved = filter_settings.load()
            assert saved['managed_filters'] == ['tfm_bloom']
            assert saved['enabled_filters'] == ['tfm_bloom']
            assert 'tfm_background_removal' not in json.loads(settings_file.read_text())['managed_filters']
            for invalid in ('[]', 'null', '{broken', '\ufffd'):
                settings_file.write_text(invalid, encoding='utf-8')
                assert not filter_settings.save({'backend': 'cpu'})
                assert settings_file.read_text(encoding='utf-8') == invalid
            settings_file.write_bytes(b'\xff')
            assert not filter_settings.save({'backend': 'cpu'})
            assert settings_file.read_bytes() == b'\xff'
            settings_file.write_text(json.dumps({'unknown': {'keep': True}, 'backend': 'auto'}), encoding='utf-8')
            with mock.patch('builtins.open', side_effect=PermissionError('unreadable')):
                assert not filter_settings.save({'backend': 'cpu'})
            assert json.loads(settings_file.read_text(encoding='utf-8'))['unknown'] == {'keep': True}
            assert filter_settings.save({'backend': 'cpu'})
            assert json.loads(settings_file.read_text(encoding='utf-8'))['unknown'] == {'keep': True}
    with mock.patch.object(filter_settings, 'resource_directory', return_value='R:/test-resource'):
        assert Path(filter_settings._config_path()).as_posix().endswith('/TFM/settings.json')
    assert len(instance.extensions) == 1
    # The manager action is registered directly under Tools; popup menus remain separate.
    from PyQt5.QtWidgets import QMenu, QAction
    from tfm.menus import menubelt
    extension = instance.extensions[0]
    fake_window = object()
    edit_action = QAction('Configure TFM')
    extension._windows.append({'window': fake_window, 'edit_action': edit_action})
    with mock.patch.object(menubelt, 'load_lists', return_value=[{'name': 'Quick Tool', 'items': []}]):
        extension._rebuild(fake_window)
        assert edit_action.text() == 'Configure TFM'
        assert edit_action.parent() is None
        popup = extension._build_popup_menu(None, {})
        assert any(action.text() == 'Quick Tool' for action in popup.actions())
        popup.deleteLater()
    extension._windows.clear()
    window = make_manager()
    tabs = window.findChild(__import__('PyQt5.QtWidgets', fromlist=['QTabWidget']).QTabWidget)
    assert [tabs.tabText(i) for i in range(tabs.count())] == [__import__('i18n').tr(en, zh) for en, zh in [('Menus', '菜单'), ('Filters', '滤镜'), ('Tools', '工具'), ('Settings', '设置')]]
    assert tabs.widget(0) is window.menu_page and tabs.widget(1) is window.filter_page
    managed_action = QAction('Select from Color Range Plus')
    managed_action.setObjectName('tfm_color_range')
    settings = {}
    with mock.patch.object(instance, 'actions', return_value=[managed_action]), \
         mock.patch.object(instance, 'readSetting', side_effect=lambda group, key, default: settings.get(key, default)), \
         mock.patch.object(instance, 'writeSetting', side_effect=lambda group, key, value: settings.__setitem__(key, value), create=True):
        window.tools_list.item(0).setCheckState(__import__('PyQt5.QtCore', fromlist=['Qt']).Qt.Unchecked)
        assert not managed_action.isVisible() and not managed_action.isEnabled()
        assert settings['color_range_enabled'] == 'false'
        reopened = make_manager()
        assert reopened.tools_list.item(0).checkState() == __import__('PyQt5.QtCore', fromlist=['Qt']).Qt.Unchecked
        assert reopened.tool_pages.count() == reopened.tools_list.count()
        reopened.tools_list.item(0).setCheckState(__import__('PyQt5.QtCore', fromlist=['Qt']).Qt.Checked)
        assert managed_action.isVisible() and managed_action.isEnabled()
        assert settings['color_range_enabled'] == 'true'
        reopened.close()
    assert not window.menu_page.has_unsaved_changes()
    assert not window.filter_page.has_unsaved_changes()
    window.menu_page.lists[0]['name'] += ' changed'
    assert window.menu_page.has_unsaved_changes()
    with mock.patch('tfm.manager.QtWidgets.QMessageBox.question', return_value=__import__('PyQt5.QtWidgets', fromlist=['QMessageBox']).QMessageBox.No):
        assert not window._confirm_close()
    window.menu_page._saved_menu_state = window.menu_page._menu_state()
    with mock.patch.object(filter_settings, 'save', return_value=False):
        window.filter_page._set_default('tfm_bloom', 'threshold', 0.31)
        window.filter_page.save_filters()
        assert window.filter_page.has_unsaved_changes()
    with mock.patch.object(filter_settings, 'save', return_value=True) as save:
        window.filter_page._parameter_controls['threshold'].setValue(0.42)
        tabs.setCurrentIndex(0)
        tabs.setCurrentIndex(1)
        window.filter_page._save.click()
        assert abs(save.call_args.args[0]['filter_defaults']['tfm_bloom']['threshold'] - 0.42) < 1e-6
    with mock.patch.object(instance, 'actions', return_value=[mock.Mock(objectName=lambda: 'action_a', text=lambda: 'Action A')]), \
         mock.patch.object(window.menu_page, '_action_shortcuts', return_value=['Ctrl+E']):
        window.menu_page.lists = [{'name': 'A', 'shortcut': 'Ctrl+E'}]
        window.menu_page._pending_overrides = {}
        assert window.menu_page._check_conflicts()
        window.menu_page._pending_overrides = {'A': [{'id': 'action_a', 'key': 'Ctrl+E'}]}
        assert window.menu_page._check_conflicts() is None
        window.menu_page.lists.append({'name': 'B', 'shortcut': 'Ctrl+E'})
        assert window.menu_page._check_conflicts()
        window.menu_page._pending_overrides = {}
    with mock.patch('tfm.menus.dialog.save_config') as save_menu, \
         mock.patch.object(window.menu_page, '_check_conflicts', return_value='duplicate shortcut'), \
         mock.patch.object(window.menu_page, '_apply_pending_overrides') as apply, \
         mock.patch('tfm.menus.dialog.QMessageBox.warning'):
        window.menu_page.save_menus()
        save_menu.assert_not_called()
        apply.assert_not_called()
    with mock.patch.object(window.menu_page, '_check_conflicts', return_value=None), \
         mock.patch.object(menu_config, '_read_raw', return_value={'lists': [{'name': 'existing'}]}), \
         mock.patch.object(window.menu_page, '_shortcut_file', return_value='test'), \
         mock.patch('tfm.menus.dialog.read_text', return_value=''), \
         mock.patch.object(menu_config, '_write_raw', return_value=False), \
         mock.patch.object(window.menu_page, '_apply_pending_overrides') as apply, \
         mock.patch('tfm.menus.dialog.save_config') as save_menu, \
         mock.patch('tfm.menus.dialog.QMessageBox.warning'):
        window.menu_page._pending_overrides = {'new menu': [{'id': 'example', 'key': 'Ctrl+E'}]}
        window.menu_page.save_menus()
        apply.assert_not_called()
        save_menu.assert_not_called()
        assert window.menu_page._pending_overrides
        window.menu_page._pending_overrides = {}
    with mock.patch.object(window.menu_page, '_check_conflicts', return_value=None), \
         mock.patch.object(window.menu_page, '_shortcut_file', return_value=None), \
         mock.patch('tfm.menus.dialog.save_config') as save_menu, \
         mock.patch('tfm.menus.dialog.QMessageBox.warning'):
        window.menu_page._pending_overrides = {'A': [{'id': 'example', 'key': 'Ctrl+E'}]}
        window.menu_page.save_menus()
        save_menu.assert_not_called()
        assert window.menu_page._pending_overrides
        window.menu_page._pending_overrides = {}
    with mock.patch('tfm.menus.dialog.save_config', return_value=False), \
         mock.patch.object(window.menu_page, '_check_conflicts', return_value=None), \
         mock.patch.object(window.menu_page, '_apply_pending_overrides') as apply, \
         mock.patch('tfm.menus.dialog.QMessageBox.warning'):
        window.menu_page.save_menus()
        apply.assert_called_once()
    with mock.patch.object(window.menu_page, '_check_conflicts', return_value=None), \
         mock.patch.object(window.menu_page, '_apply_pending_overrides', return_value=False), \
         mock.patch('tfm.menus.dialog.save_config') as save_menu, \
         mock.patch('tfm.menus.dialog.QMessageBox.warning'):
        window.menu_page.save_menus()
        save_menu.assert_not_called()
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR') or tempfile.gettempdir()) as tmp:
        path = Path(tmp) / 'kritashortcutsrc'
        path.write_text('[Shortcuts]\nexample=Ctrl+E\n', encoding='utf-8')
        from tfm.menus import shortcuts
        with mock.patch.object(shortcuts.os, 'replace', side_effect=OSError('disk failure')):
            assert not shortcuts.write_text(str(path), '[Shortcuts]\nexample=none\n')
        assert 'example=Ctrl+E' in path.read_text(encoding='utf-8')
        assert sorted(p.name for p in path.parent.iterdir()) == ['kritashortcutsrc']
        window.menu_page._pending_overrides = {'A': [{'id': 'example', 'action': object(), 'prev_runtime': ['Ctrl+E']}]}
        with mock.patch.object(window.menu_page, '_shortcut_file', return_value=None), \
             mock.patch('tfm.menus.dialog.QMessageBox.warning'), \
             mock.patch.object(window.menu_page, '_clear_action_shortcuts') as clear:
            assert not window.menu_page._apply_pending_overrides()
            clear.assert_not_called()
            assert window.menu_page._pending_overrides
        with mock.patch.object(window.menu_page, '_shortcut_file', return_value=str(path)), \
             mock.patch('tfm.menus.dialog.read_text', side_effect=PermissionError('unreadable')), \
             mock.patch('tfm.menus.dialog.QMessageBox.warning'), \
             mock.patch.object(window.menu_page, '_clear_action_shortcuts') as clear:
            assert not window.menu_page._apply_pending_overrides()
            clear.assert_not_called()
            assert 'example=Ctrl+E' in path.read_text(encoding='utf-8')
        with mock.patch('tfm.menus.shortcuts.read_text', side_effect=PermissionError('unreadable')), \
             mock.patch('tfm.menus.shortcuts.write_text') as write:
            assert not shortcuts.restore(str(path), {'example': None})
            write.assert_not_called()
        with mock.patch.object(window.menu_page, '_shortcut_file', return_value=str(path)), \
             mock.patch.object(menu_config, '_read_raw', return_value={}), \
             mock.patch.object(menu_config, '_write_raw', return_value=False), \
             mock.patch.object(window.menu_page, '_clear_action_shortcuts') as clear:
            assert not window.menu_page._apply_pending_overrides()
            clear.assert_not_called()
            assert 'example=Ctrl+E' in path.read_text(encoding='utf-8')
        with mock.patch.object(window.menu_page, '_shortcut_file', return_value=str(path)), \
             mock.patch.object(menu_config, '_read_raw', return_value={}), \
             mock.patch.object(menu_config, '_write_raw', return_value=True) as write, \
             mock.patch('tfm.menus.shortcuts.write_text', return_value=False), \
             mock.patch.object(window.menu_page, '_clear_action_shortcuts') as clear:
            assert not window.menu_page._apply_pending_overrides()
            assert write.call_args.args[0]['overrides']['A'][0]['prev_file'] == 'Ctrl+E'
            clear.assert_not_called()
            assert 'example=Ctrl+E' in path.read_text(encoding='utf-8')
        config_path = Path(tmp) / 'config.json'
        config_path.write_text('{}', encoding='utf-8')
        with mock.patch.object(menu_config, 'CONFIG_FILE', str(config_path)), \
             mock.patch.object(window.menu_page, '_shortcut_file', return_value=str(path)), \
             mock.patch.object(window.menu_page, '_clear_action_shortcuts') as clear:
            with mock.patch('tfm.menus.shortcuts.write_text', return_value=False):
                assert not window.menu_page._apply_pending_overrides()
            first = json.loads(config_path.read_text(encoding='utf-8'))
            assert len(first['overrides']['A']) == 1
            assert window.menu_page._apply_pending_overrides()
            second = json.loads(config_path.read_text(encoding='utf-8'))
            assert len(second['overrides']['A']) == 1
            assert second['overrides']['A'][0]['prev_file'] == 'Ctrl+E'
            assert shortcuts.parse_entries(shortcuts.read_text(str(path)))['example'] == 'none'
            clear.assert_called_once()
            shortcuts.restore(str(path), {'example': second['overrides']['A'][0]['prev_file']})
            assert shortcuts.parse_entries(shortcuts.read_text(str(path)))['example'] == 'Ctrl+E'
    # New menu and shortcut save together, preserving a recovery entry on failure.
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR') or tempfile.gettempdir()) as tmp:
        config_path = Path(tmp) / 'config.json'
        shortcut_path = Path(tmp) / 'kritashortcutsrc'
        config_path.write_text(json.dumps({'lists': [], 'unknown': 7}), encoding='utf-8')
        shortcut_path.write_text('[Shortcuts]\nexample=Ctrl+E\n', encoding='utf-8')
        page = window.menu_page
        page.lists = [{'name': 'new menu', 'shortcut': 'Ctrl+E', 'items': []}]
        page.current = 0
        with mock.patch.object(menu_config, 'CONFIG_FILE', str(config_path)), \
             mock.patch.object(page, '_shortcut_file', return_value=str(shortcut_path)), \
             mock.patch.object(page, '_check_conflicts', return_value=None), \
             mock.patch('tfm.menus.dialog.QMessageBox.warning'), \
             mock.patch('tfm.menus.dialog.notify_refresh'):
            page._pending_overrides = {'new menu': [{'id': 'example', 'key': 'Ctrl+E', 'prev_runtime': ['Ctrl+E']}]}
            with mock.patch('tfm.menus.shortcuts.write_text', return_value=False):
                page.save_menus()
            assert page.undo_sc_btn.isEnabled()
            assert 'example=Ctrl+E' in shortcut_path.read_text(encoding='utf-8')
            assert json.loads(config_path.read_text(encoding='utf-8'))['overrides']['new menu'][0]['prev_file'] == 'Ctrl+E'
            with mock.patch('tfm.menus.dialog.QMessageBox.question', return_value=__import__('PyQt5.QtWidgets', fromlist=['QMessageBox']).QMessageBox.Yes):
                page._restore_overrides()
            assert not page._pending_overrides
            assert 'example=Ctrl+E' in shortcut_path.read_text(encoding='utf-8')
            page.save_menus()
            assert 'example=Ctrl+E' in shortcut_path.read_text(encoding='utf-8')
            page.lists[0]['shortcut'] = 'Ctrl+E'
            page._pending_overrides = {'new menu': [{'id': 'example', 'key': 'Ctrl+E', 'prev_runtime': ['Ctrl+E']}]}
            with mock.patch('tfm.menus.dialog.save_config', return_value=False):
                page.save_menus()
            staged = json.loads(config_path.read_text(encoding='utf-8'))
            assert staged['lists'][0]['shortcut'] == ''
            assert staged['overrides']['new menu'][0]['prev_file'] == 'Ctrl+E'
            assert staged['unknown'] == 7
            page.save_menus()
            saved = json.loads(config_path.read_text(encoding='utf-8'))
            assert saved['lists'][0]['shortcut'] == 'Ctrl+E'
            assert saved['overrides']['new menu'][0]['prev_file'] == 'Ctrl+E'
    # Creating and duplicating menus must not collide with recovery identities.
    page = window.menu_page
    page.lists = [{'name': 'A', 'shortcut': 'Ctrl+E', 'items': []}]
    page.current = 0
    with mock.patch('tfm.menus.dialog.QInputDialog.getText', return_value=(' A ', True)), \
         mock.patch('tfm.menus.dialog.QMessageBox.warning') as warning, \
         mock.patch('tfm.menus.dialog.load_overrides', return_value={}):
        page._new_list()
        assert len(page.lists) == 1
        warning.assert_called_once()
    with mock.patch('tfm.menus.dialog.load_overrides', return_value={'A copy 2': [{'id': 'x'}]}):
        page._duplicate_list()
        assert page.lists[1]['name'] == 'A copy' and page.lists[1]['shortcut'] == ''
        page.current = 0
        page._duplicate_list()
        assert page.lists[1]['name'] == 'A copy 3' and page.lists[1]['shortcut'] == ''
    # Restore must remain recoverable after either configuration write fails.
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR') or tempfile.gettempdir()) as tmp:
        config_path = Path(tmp) / 'config.json'
        shortcut_path = Path(tmp) / 'kritashortcutsrc'
        record = {'id': 'example', 'key': 'Ctrl+E', 'prev_file': 'Ctrl+E', 'prev_runtime': []}
        initial = {'lists': [{'name': 'A', 'shortcut': 'Ctrl+E', 'items': []}],
                   'overrides': {'A': [record]}, 'unknown': 'preserve'}
        for failing_write in (1, 2):
            config_path.write_text(json.dumps(initial), encoding='utf-8')
            shortcut_path.write_text('[Shortcuts]\nexample=none\n', encoding='utf-8')
            page = window.menu_page
            page.current = 0
            page.lists = [{'name': 'A', 'shortcut': 'Ctrl+E', 'items': []}]
            write_original = menu_config._write_raw
            calls = []
            def fail_one_write(data):
                calls.append(1)
                return False if len(calls) == failing_write else write_original(data)
            with mock.patch.object(menu_config, 'CONFIG_FILE', str(config_path)), \
                 mock.patch.object(page, '_shortcut_file', return_value=str(shortcut_path)), \
                 mock.patch.object(page, '_update_left_shortcut'), \
                 mock.patch('tfm.menus.dialog.QMessageBox.question', return_value=__import__('PyQt5.QtWidgets', fromlist=['QMessageBox']).QMessageBox.Yes), \
                 mock.patch('tfm.menus.dialog.QMessageBox.warning') as warning, \
                 mock.patch('tfm.menus.dialog.notify_refresh'):
                with mock.patch.object(menu_config, '_write_raw', side_effect=fail_one_write):
                    page._restore_overrides()
                persisted = json.loads(config_path.read_text(encoding='utf-8'))
                assert persisted['overrides']['A'] == [record]
                assert persisted['lists'][0]['shortcut'] == ('Ctrl+E' if failing_write == 1 else '')
                assert shortcuts.parse_entries(shortcuts.read_text(str(shortcut_path)))['example'] == 'Ctrl+E'
                warning.assert_called_once()
                # Reopen the editor using persisted data before retrying.
                page.popup_shortcut, page.lists = menu_config.load_config()
                page.current = 0
                page._restore_overrides()
                persisted = json.loads(config_path.read_text(encoding='utf-8'))
                assert not persisted['overrides'].get('A')
                assert persisted['lists'][0]['shortcut'] == ''
                assert persisted['unknown'] == 'preserve'
                assert shortcuts.parse_entries(shortcuts.read_text(str(shortcut_path)))['example'] == 'Ctrl+E'

    with mock.patch('tfm.menus.dialog.load_overrides', return_value={'A': [{'id': 'example'}]}), \
         mock.patch('tfm.menus.dialog.QMessageBox.warning') as warning:
        window.menu_page.lists = [{'name': 'A', 'items': []}]
        window.menu_page.current = 0
        window.menu_page._delete_list()
        assert len(window.menu_page.lists) == 1
        warning.assert_called_once()
    print('PASS: three pages, filter save, shortcut recovery and guarded menu deletion')
    with mock.patch('tfm.manager.QtWidgets.QMessageBox.question', return_value=__import__('PyQt5.QtWidgets', fromlist=['QMessageBox']).QMessageBox.Yes) as confirm:
        window._confirm_close = lambda: ManagerDialog._confirm_close(window)
        window.menu_page.lists[0]['name'] += ' pending close'
        window.reject()
        event = __import__('PyQt5.QtGui', fromlist=['QCloseEvent']).QCloseEvent()
        window.closeEvent(event)
        assert confirm.call_count == 1
        assert event.isAccepted()
        window._close_confirmed = False
        window.menu_page.lists[0]['name'] = window.menu_page._saved_menu_state[1][0]['name']



if __name__ == "__main__":
    main()
