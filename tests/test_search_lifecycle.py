"""Local network and Qt lifecycle faults; no external service or user profile."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
import time
import urllib.request
import os
import sys
import subprocess

import pytest
from qt_test_binding import QTest, QCoreApplication, QEvent
from test_search_history_ui import panel, finish, wait
import test_docker as fixture
from quick_image_search.network import request_bytes
from quick_image_search.task_runtime import Token, task_scope, Cancelled, current_token, BoundedExecutor
from quick_image_search.browser import _WebSocket, Browser


def test_cancelled_job_resumes_each_pending_operation(tmp_path, monkeypatch):
    p = panel(tmp_path)
    resumed = []
    try:
        names = ('resume_pending_search', 'resume_gallery_back', 'resume_library', 'resume_similarity', 'resume_paging')
        for name in names:
            monkeypatch.setattr(p, name, lambda name=name: resumed.append(name))
        def operation(job):
            while not job.isInterruptionRequested():
                time.sleep(.005)
            current_token().check()
        job = p.run_job(operation, lambda result: pytest.fail('cancelled result delivered'))
        job.requestInterruption()
        wait(p)
        assert set(resumed) == set(names)
    finally:
        finish(p)


@contextlib.contextmanager
def local_server():
    started, stopped = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            started.set()
            try:
                if self.path == '/redirect':
                    stopped.wait(.07)
                    self.send_response(302)
                    self.send_header('Location', '/redirect')
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-Length', '100000')
                self.end_headers()
                if self.path == '/stall':
                    stopped.wait(3)
                else:
                    while not stopped.wait(.025):
                        self.wfile.write(b'x')
                        self.wfile.flush()
            except (OSError, ConnectionError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval':.02}, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', started
    finally:
        stopped.set()
        server.shutdown()
        server.server_close()
        thread.join(1)


@pytest.mark.parametrize('path', ['/stall','/trickle','/redirect'])
def test_network_has_total_deadline_even_when_bytes_keep_arriving(path):
    with local_server() as (url, _):
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            request_bytes(urllib.request.Request(url+path), timeout=.18)
        assert time.monotonic()-start < .8


def test_cancel_aborts_running_qt_network_and_discards_delivery(tmp_path):
    with local_server() as (url, started):
        p = panel(tmp_path)
        delivered = []
        job = p.run_job(lambda _: request_bytes(urllib.request.Request(url+'/stall')), delivered.append)
        assert started.wait(2)
        start = time.monotonic()
        job.requestInterruption()
        assert job.wait(800)
        wait(p)
        assert time.monotonic()-start < .8 and not delivered
        finish(p)


def test_cancel_stops_new_thumbnail_submissions_and_shutdown_is_async(tmp_path):
    gate, started = threading.Event(), threading.Event()
    calls = []
    def download(url, *_):
        calls.append(url)
        started.set()
        token = current_token()
        while not gate.wait(.01):
            token.check()
        return b''
    p = panel(tmp_path, downloader=download)
    p.display_results([dict(source='google', id=str(i), thumbnail=f'https://example.com/{i}') for i in range(100)])
    assert started.wait(1)
    start = time.monotonic()
    p.shutdown()
    assert time.monotonic()-start < .15
    assert p._shutdown_done.wait(1)
    gate.set()
    assert len(calls) <= 4
    p.close()


def test_queued_result_does_not_touch_destroyed_controls(tmp_path):
    gate = threading.Event()
    p = panel(tmp_path)
    delivered = []
    job = p.run_job(lambda _: gate.wait(1), delivered.append)
    p.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gate.set()
    assert job.wait(1000)
    fixture.APP.processEvents()
    assert p._closing and not delivered


def test_websocket_partial_frame_is_cancellable():
    server, client = socket.socketpair()
    token = Token()
    timer = threading.Timer(.08, token.cancel)
    try:
        server.sendall(b'\x81\x7e')  # extended length never arrives
        ws = _WebSocket(client)
        timer.start()
        with task_scope(token), pytest.raises(Cancelled):
            ws.recv()
    finally:
        timer.cancel()
        server.close()
        client.close()


def test_browser_close_never_closes_attached_process():
    browser = Browser()
    browser._targets = {'google':'owned-tab'}
    calls = []
    browser._command = lambda method, *args: calls.append((method,args))
    browser.close()
    assert [method for method,_ in calls] == ['Target.closeTarget']


def test_pool_shutdown_cancels_queued_work_without_joining_running_work():
    entered, release = threading.Event(), threading.Event()
    pool = BoundedExecutor()
    first = pool.submit(lambda: (entered.set(), release.wait(1)))
    assert entered.wait(1)
    second = pool.submit(lambda: pytest.fail('queued work started after shutdown'))
    start = time.monotonic()
    pool.shutdown()
    assert time.monotonic()-start < .1 and second.cancelled()
    release.set()
    first.result(timeout=1)


@pytest.mark.skipif(os.name != 'nt', reason='Windows process ownership')
def test_owned_process_job_reaps_descendants():
    import ctypes
    from ctypes import wintypes
    from quick_image_search.process_owner import ProcessOwner
    script = "import subprocess,sys,time; sys.stdin.readline(); child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); print(child.pid,flush=True); time.sleep(30)"
    process = subprocess.Popen([sys.executable,'-c',script],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                               text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    owner = None
    child_handle = None
    kernel = ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    try:
        owner=ProcessOwner(process)
        process.stdin.write('start\n');process.stdin.flush()
        child=int(process.stdout.readline().strip())
        child_handle=kernel.OpenProcess(0x00100000,False,child)
        assert child_handle
        owner.close()
        process.wait(timeout=2)
        assert kernel.WaitForSingleObject(child_handle,2000)==0
    finally:
        if owner: owner.close()
        if process.poll() is None: process.kill();process.wait(timeout=2)
        if child_handle: kernel.CloseHandle(child_handle)
