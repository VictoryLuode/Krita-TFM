"""Source routing: Pinterest HTTP, Google explicitly headless by default."""
from pathlib import Path


class Backend:
    def __init__(self, google=None, pinterest=None):
        self._google = google
        self._pinterest = pinterest
        self._profile_dir = None
        self._proxy = ''
        self._verification_open = False

    def start(self, profile_dir, proxy=''):
        # Configuration alone must not start either provider or create a window.
        self._profile_dir = str(profile_dir)
        self._proxy = proxy

    def _driver(self, source):
        if source == 'google':
            if self._verification_open:
                raise ValueError('请先完成 Google 验证，再点击搜索恢复后台运行。')
            if self._profile_dir is None:
                raise ValueError('The search backend has not been configured')
            if self._google is None:
                from .browser import Browser
                self._google = Browser(port=9236, headless=True)
            profile = Path(self._profile_dir)
            self._google.start(str(profile.with_name(profile.name + '-background')), proxy=self._proxy, headless=True)
            return self._google
        if source == 'pinterest':
            if self._pinterest is None:
                from .pinterest import Pinterest
                self._pinterest = Pinterest()
            self._pinterest.start(self._profile_dir, proxy=self._proxy)
            return self._pinterest
        raise ValueError('Unsupported image source')

    def search(self, source, query, limit=24):
        if source == 'google':
            self._verification_open = False
        return self._driver(source).search(source, query, limit=limit)

    def resolve(self, entry):
        return self._driver(entry.get('source')).resolve(entry)

    def similar(self, image_bytes, limit=24):
        return self._driver('pinterest').similar(image_bytes, limit=limit)

    def more(self, source, limit=24):
        return self._driver(source).more(source, limit=limit)

    def has_more(self, source):
        driver = self._google if source == 'google' else self._pinterest if source == 'pinterest' else None
        return bool(driver is not None and driver.has_more(source))

    def show(self):
        # This is called solely by the explicit Google verification button.
        driver = self._google if self._google is not None else self._driver('google')
        result = driver.show()
        self._verification_open = True
        return result

    def close(self):
        for driver in (self._google, self._pinterest):
            if driver is not None:
                driver.close()
