"""Owned, bounded search work. Cancellation never terminates Python threads."""
from contextlib import contextmanager
from concurrent.futures import Future
import queue
import threading
import time
import weakref


class Cancelled(Exception):
    pass


class Token:
    def __init__(self, seconds=60):
        self.event = threading.Event()
        self.deadline = time.monotonic() + seconds

    def cancel(self):
        self.event.set()

    def check(self):
        if self.event.is_set():
            raise Cancelled('Search task cancelled')
        if time.monotonic() >= self.deadline:
            raise TimeoutError('Search task exceeded its total time limit')

    def sleep(self, seconds):
        self.check()
        self.event.wait(min(seconds, max(0, self.deadline - time.monotonic())))
        self.check()


_local = threading.local()


def current_token():
    return getattr(_local, 'token', None)


@contextmanager
def task_scope(token):
    previous = current_token()
    _local.token = token
    try:
        token.check()
        yield token
    finally:
        _local.token = previous


def check_cancelled():
    token = current_token()
    if token:
        token.check()


def interruptible_sleep(seconds):
    token = current_token()
    if token:
        token.sleep(seconds)
    else:
        time.sleep(seconds)


class BoundedExecutor:
    """Small daemon pool; no interpreter-exit join on regenerable caches.

    Workers only receive data/file operations, never QWidget updates. Queued
    tasks are cancelled on shutdown; running tasks keep their own token.
    """
    def __init__(self, max_workers=1, max_pending=128, thread_name_prefix='search'):
        self._queue = queue.Queue(max_pending)
        self._lock = threading.Lock()
        self._closed = False
        self._threads = [threading.Thread(target=self._work, name=f'{thread_name_prefix}-{i}', daemon=True)
                         for i in range(max_workers)]
        for thread in self._threads:
            thread.start()

    def submit(self, fn, *args, **kwargs):
        future = Future()
        token = current_token()
        with self._lock:
            if self._closed:
                future.cancel()
                return future
            try:
                self._queue.put_nowait((future, token, fn, args, kwargs))
            except queue.Full:
                future.set_exception(RuntimeError('Search background queue is full'))
        return future

    def _work(self):
        while True:
            try:
                task = self._queue.get(timeout=.1)
            except queue.Empty:
                with self._lock:
                    if self._closed:
                        return
                continue
            future, token, fn, args, kwargs = task
            try:
                if future.set_running_or_notify_cancel():
                    try:
                        with task_scope(token or Token()):
                            result = fn(*args, **kwargs)
                        future.set_result(result)
                    except BaseException as error:
                        future.set_exception(error)
            finally:
                self._queue.task_done()

    def shutdown(self, wait=False, cancel_futures=True, deadline=None):
        with self._lock:
            self._closed = True
            if cancel_futures:
                while True:
                    try:
                        future, *_ = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    future.cancel()
                    self._queue.task_done()
        if wait:
            end = deadline if deadline is not None else time.monotonic()+3
            for thread in self._threads:
                thread.join(max(0, end-time.monotonic()))


_owners = weakref.WeakSet()
_connected_app = None


def register_owner(owner, app):
    global _connected_app
    _owners.add(owner)
    if _connected_app is not app:
        app.aboutToQuit.connect(shutdown_all)
        _connected_app = app


def shutdown_all():
    # One deadline for every search panel, job, cache and owned browser.
    deadline = time.monotonic()+3
    owners = list(_owners)
    for owner in owners:
        owner.shutdown(deadline=deadline)
    for owner in owners:
        owner._shutdown_done.wait(max(0, deadline-time.monotonic()))
