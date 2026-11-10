"""Abortable Qt network transport with a total deadline and bounded response.

Each request lives in its calling worker's event loop. Qt owns DNS/connect/TLS
and aborts the reply; no extra Python network threads survive cancellation.
"""
import time
import urllib.error
import urllib.parse

from qtcompat import PYQT6, QEventLoop, QTimer, QUrl
if PYQT6:
    from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkProxy
else:
    from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkProxy
from quick_image_search.task_runtime import current_token


def request_bytes(request, *, timeout=20, limit=24*1024*1024, proxy='', validate=None):
    token = current_token()
    deadline = min(time.monotonic()+timeout, token.deadline if token else float('inf'))
    manager = QNetworkAccessManager()
    if proxy:
        parsed = urllib.parse.urlsplit(proxy)
        if parsed.scheme not in ('http', 'socks5') or not parsed.hostname:
            raise ValueError('Unsupported search proxy; use http:// or socks5://')
        kind = QNetworkProxy.ProxyType.Socks5Proxy if parsed.scheme == 'socks5' else QNetworkProxy.ProxyType.HttpProxy
        manager.setProxy(QNetworkProxy(kind, parsed.hostname, parsed.port or 8080,
                                       urllib.parse.unquote(parsed.username or ''), urllib.parse.unquote(parsed.password or '')))
    url, method, data = request.full_url, request.get_method(), request.data or b''
    headers = dict(request.header_items())
    for redirect in range(6):
        if token:
            token.check()
        if time.monotonic() >= deadline:
            raise TimeoutError('Network request exceeded its total time limit')
        if validate:
            validate(url)
        query = QNetworkRequest(QUrl(url))
        query.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                           QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        for key, value in headers.items():
            query.setRawHeader(key.encode('ascii'), str(value).encode('latin1'))
        reply = manager.sendCustomRequest(query, method.encode('ascii'), data)
        reply.setReadBufferSize(65536)
        loop, timer, chunks, errors = QEventLoop(), QTimer(), bytearray(), []

        def collect():
            chunks.extend(bytes(reply.readAll()))
            if len(chunks) > limit:
                errors.append(ValueError('Network response exceeds its size limit'))
                reply.abort()

        def poll():
            try:
                if token:
                    token.check()
                if time.monotonic() >= deadline:
                    raise TimeoutError('Network request exceeded its total time limit')
            except Exception as error:
                errors.append(error)
                reply.abort()

        reply.readyRead.connect(collect)
        reply.finished.connect(loop.quit)
        timer.timeout.connect(poll)
        timer.start(25)
        if not reply.isFinished():
            (loop.exec if hasattr(loop, 'exec') else loop.exec_)()
        timer.stop()
        collect()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        redirect_url = reply.attribute(QNetworkRequest.Attribute.RedirectionTargetAttribute)
        error_code, error_text = int(reply.error()), reply.errorString()
        reply.deleteLater()
        if errors:
            raise errors[0]
        if token:
            token.check()
        if time.monotonic() >= deadline:
            raise TimeoutError('Network request exceeded its total time limit')
        if status in (301,302,303,307,308) and redirect_url:
            new_url = urllib.parse.urljoin(url, redirect_url.toString())
            if urllib.parse.urlsplit(new_url).scheme not in ('http','https'):
                raise ValueError('Unsupported network redirect')
            if urllib.parse.urlsplit(url).netloc != urllib.parse.urlsplit(new_url).netloc:
                headers = {k:v for k,v in headers.items() if k.lower() not in ('authorization','cookie')}
            url = new_url
            if status == 303 or (status in (301,302) and method == 'POST'):
                method, data = 'GET', b''
            continue
        if status and status >= 400:
            raise urllib.error.HTTPError(url, status, error_text, {}, None)
        if error_code:
            raise OSError(error_text)
        return bytes(chunks)
    raise ValueError('Too many network redirects')
