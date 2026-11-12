"""Asset Library tree/grid widgets and shared helpers.

Helpers live in sibling modules; this file re-exports them so
`panel_context` star-imports (including leading-underscore names) keep working.
"""

from .widget_helpers import *  # noqa: F401,F403
from .folder_tree import *  # noqa: F401,F403
from .image_grid import *  # noqa: F401,F403


class DropPane(QtWidgets.QWidget):
    """Catches a layer drop that lands beside the folder tree and the thumbnails."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if drop_kind(event.mimeData()) in (None, "folder"):
            event.ignore()
            return
        self.panel._remember_status("Release to store a copy.")
        _accept_copy(event)

    def dragMoveEvent(self, event):
        if drop_kind(event.mimeData()) in (None, "folder"):
            event.ignore()
            return
        _accept_copy(event)

    def dragLeaveEvent(self, event):
        self.panel._restore_status()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if drop_kind(event.mimeData()) in (None, "folder"):
            event.ignore()
            return
        _accept_copy(event)
        self.panel._restore_status()
        self.panel._drop_on_folder(self.panel._current_folder(), event.mimeData())


__all__ = [name for name in list(globals()) if not name.startswith("__")]
