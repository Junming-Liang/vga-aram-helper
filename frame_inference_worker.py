"""One reusable, bounded daemon for same-frame independent local inference.

The caller must join each submitted result before accepting a frame or starting
another capture. Closing revokes future submissions; an already-running native
inference is allowed to finish, without blocking the GUI or process exit.
"""
from concurrent.futures import Future
import threading


class FrameInferenceWorker:
    def __init__(self):
        self._condition = threading.Condition()
        self._thread = None
        self._pending = None
        self._busy = False
        self._closed = False

    def submit(self, fn, *args):
        with self._condition:
            if self._closed:
                raise RuntimeError('Frame inference worker is closed')
            if self._busy:
                raise RuntimeError('A frame inference is already in flight')
            future = Future()
            future.set_running_or_notify_cancel()
            self._pending = (future, fn, args)
            self._busy = True
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name='vga-frame-ocr', daemon=True)
                self._thread.start()
            self._condition.notify()
            return future

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._pending is not None or self._closed)
                if self._pending is None:
                    return
                future, fn, args = self._pending
                self._pending = None
            try:
                value = fn(*args)
            except BaseException as exc:
                with self._condition:
                    self._busy = False
                future.set_exception(exc)
            else:
                with self._condition:
                    self._busy = False
                future.set_result(value)
            finally:
                # Do not retain the preceding frame/crop in an idle worker.
                future = fn = args = value = None

    def close(self):
        with self._condition:
            self._closed = True
            self._condition.notify()
