"""Small atomic local UI preference store, independent of cached search pages."""
import json
import os
from pathlib import Path
import tempfile
import uuid


class UIPreferences:
    def __init__(self, path):
        self.path = Path(path)
        self.tile_size = 144
        self.last_error = ''
        self._blocked = False
        self._document = {'schema_version': 1, 'tile_size': 144}
        try:
            with self.path.open('rb') as stream:
                raw = stream.read(16385)
            if len(raw) > 16384:
                raise ValueError('UI preference file is too large')
            document = json.loads(raw.decode('utf-8'))
            size = document.get('tile_size') if isinstance(document, dict) else None
            if not isinstance(document, dict) or document.get('schema_version') != 1 or type(size) is not int or not 80 <= size <= 320:
                raise ValueError('Invalid grid size preference')
            self._document = document
            self.tile_size = size
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as error:
            self.last_error = str(error)
            try:
                os.replace(self.path, self.path.with_name(self.path.name + '.corrupt-' + uuid.uuid4().hex))
            except OSError as backup_error:
                self._blocked = True
                self.last_error += '; 原文件无法备份，禁止覆盖：' + str(backup_error)

    def save(self, size):
        if type(size) is not int or not 80 <= size <= 320:
            raise ValueError('Grid size must be between 80 and 320')
        if self._blocked:
            raise OSError('Existing UI preference file cannot be safely replaced')
        document = dict(self._document, tile_size=size)
        raw = json.dumps(document, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.' + self.path.name + '.', suffix='.tmp', dir=str(self.path.parent))
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        self._document = document
        self.tile_size = size
        self.last_error = ''
