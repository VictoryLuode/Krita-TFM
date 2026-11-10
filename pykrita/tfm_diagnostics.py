"""Consistent, bounded diagnostics; callers retain control of user-facing UI."""
from collections import deque
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import tempfile
import threading

_logger = logging.getLogger('tfm')
_lock = threading.RLock()
_recent = deque(maxlen=100)
_configured = False


def record_error(operation, error, *, path=None):
    """Record failures without throwing while handling an earlier failure.

    Do not pass image data, script source, credentials or complete configuration
    objects. Optional capability probes can continue to use normal fallbacks.
    """
    global _configured
    detail = {'operation': str(operation), 'error': str(error), 'path': str(path or '')}
    with _lock:
        _recent.append(detail)
        if not _configured:
            _configured = True
            try:
                directory = Path(os.environ.get('TFM_LOG_DIR') or
                                 Path(os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()) / 'TFM/logs')
                directory.mkdir(parents=True, exist_ok=True)
                handler = RotatingFileHandler(directory / 'errors.log', maxBytes=1024 * 1024,
                                              backupCount=2, encoding='utf-8')
                handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
                _logger.addHandler(handler)
            except OSError:
                # Logging is best effort; the original error is still emitted below.
                pass
        _logger.error('%s%s: %s', detail['operation'],
                      ' [' + detail['path'] + ']' if detail['path'] else '', detail['error'])
    return detail


def recent_errors():
    with _lock:
        return [dict(item) for item in _recent]
