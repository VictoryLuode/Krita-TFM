from tfm_diagnostics import record_error
"""User and bundled script management; compatible path overrides live in config.py."""
import os
import traceback
from . import config as _config

def ensure_scripts_dir():
    """Create the user script library folder if needed; returns its path."""
    try:
        os.makedirs(_config.SCRIPTS_DIR, exist_ok=True)
    except OSError as e:
        record_error("script.create_directory", e, path=_config.SCRIPTS_DIR)
    return _config.SCRIPTS_DIR


def bundled_scripts_dir():
    return os.path.join(os.path.dirname(_config.PLUGIN_DIR), "scripts")


def list_scripts():
    """Return unique [(filename, label)] entries from user and bundled libraries."""
    entries = {}
    for directory in (_config.bundled_scripts_dir(), _config.SCRIPTS_DIR):
        try:
            for fn in os.listdir(directory):
                if fn.lower().endswith(".py") and not fn.startswith("_"):
                    entries[fn] = (fn, fn[:-3])
        except OSError:
            pass
    return sorted(entries.values(), key=lambda pair: pair[1].lower())


def script_filename(name):
    """Normalise a user supplied script name into a library file name."""
    fn = os.path.basename(str(name or "").strip())
    if fn.lower().endswith(".py"):
        fn = fn[:-3].strip() + ".py"
    elif fn:
        fn += ".py"
    return fn


def script_path(name):
    fn = _config.script_filename(name)
    user_path = os.path.join(_config.SCRIPTS_DIR, fn)
    if os.path.isfile(user_path):
        return user_path
    return os.path.join(_config.bundled_scripts_dir(), fn)


def read_script(name):
    try:
        with open(_config.script_path(name), "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def write_script(name, code):
    """Create/overwrite a library script. Returns the stored file name ('' on failure)."""
    fn = _config.script_filename(name)
    if not fn:
        return ""
    _config.ensure_scripts_dir()
    try:
        with open(os.path.join(_config.SCRIPTS_DIR, fn), "w", encoding="utf-8", newline="\n") as f:
            f.write(code if code is not None else "")
        return fn
    except OSError as e:
        record_error("script.write", e, path=fn)
        return ""


def delete_script(name):
    try:
        os.remove(os.path.join(_config.SCRIPTS_DIR, _config.script_filename(name)))
        return True
    except OSError as e:
        record_error("script.delete", e, path=name)
        return False


def rename_script(old, new):
    """Rename a library script. Returns the new file name ('' on failure)."""
    old_fn, new_fn = _config.script_filename(old), _config.script_filename(new)
    if not old_fn or not new_fn or old_fn == new_fn:
        return ""
    if os.path.exists(os.path.join(_config.SCRIPTS_DIR, new_fn)) or os.path.exists(os.path.join(_config.bundled_scripts_dir(), new_fn)):
        return ""
    try:
        os.replace(os.path.join(_config.SCRIPTS_DIR, old_fn), os.path.join(_config.SCRIPTS_DIR, new_fn))
        return new_fn
    except OSError as e:
        record_error("script.rename", e, path=old_fn)
        return ""


def _report(title, text):
    """Show a short error dialog and never fail while doing so."""
    record_error(title, text)
    try:
        from .qtcompat import QMessageBox, exec_
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("TFM")
        box.setText(title)
        box.setInformativeText(text)
        exec_(box)
    except Exception:
        pass


def run_script(name):
    """Run a library script, with Krita handles injected into its namespace."""
    fn = _config.script_filename(name)
    if not fn:
        return
    path = _config.script_path(fn)
    try:
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
    except OSError as e:
        _config._report("Script not found", f"{fn}\n{e}")
        return

    app = _config.Krita.instance()
    doc = app.activeDocument()
    win = app.activeWindow()
    try:
        view = win.activeView() if win is not None else None
    except Exception:
        view = None
    node = doc.activeNode() if doc is not None else None
    namespace = {
        "__name__": "__tfm_script__",
        "__file__": path,
        "Krita": _config.Krita, "krita": app, "app": app,
        "document": doc, "doc": doc,
        "window": win, "view": view,
        "layer": node, "node": node,
    }
    try:
        exec(compile(code, path, "exec"), namespace)
    except Exception:
        traceback.print_exc()
        lines = [ln for ln in traceback.format_exc().strip().splitlines() if ln.strip()]
        _config._report("Script failed", "%s\n\n%s" % (fn, "\n".join(lines[-2:])))


