"""One bounded latest-frame slot; capture never grants display/recognition authority.

Only a caller-validated, already enrolled visible session may submit work. The
GUI owns routing; this module owns one daemon, one in-flight call and one slot.
Every consumer must revalidate scope and preserve the original captured_at.
"""
from dataclasses import dataclass
import threading
import time

MAX_FRAME_BYTES=64*1024*1024

@dataclass(frozen=True)
class CapturedFrame:
    image:bytes
    rect:object
    captured_at:float
    acquired_at:float

class LatestCaptureFrame:
    def __init__(self,*,clock=time.monotonic):
        self._clock=clock;self._condition=threading.Condition()
        self._epoch=0;self._closed=False;self._busy=False
        self._thread=None;self._pending=None;self._slot=None;self._failure=None
    @property
    def busy(self):
        with self._condition:return self._busy
    def clear(self):
        with self._condition:
            self._epoch+=1;self._slot=None;self._failure=None
    def close(self):
        with self._condition:
            self._closed=True;self._epoch+=1;self._slot=None;self._failure=None
            self._condition.notify_all()
    def _cancelled(self,epoch):
        with self._condition:return self._closed or epoch!=self._epoch
    def submit(self,scope,fn):
        with self._condition:
            if self._closed or self._busy:return False
            self._busy=True;self._pending=(self._epoch,scope,fn)
            if self._thread is None:
                self._thread=threading.Thread(target=self._run,name='vga-latest-capture',daemon=True)
                try:self._thread.start()
                except RuntimeError:
                    self._thread=None;self._busy=False;self._pending=None
                    return False
            self._condition.notify();return True
    def take(self,scope,*,max_age=.8):
        if not 0<max_age<=1:raise ValueError('Prefetched frames require a short bounded age')
        with self._condition:
            if self._busy:return None
            slot,self._slot=self._slot,None
            if self._closed or slot is None:return None
            epoch,saved_scope,frame=slot
            age=self._clock()-frame.captured_at
            return frame if epoch==self._epoch and saved_scope==scope and 0<=age<=max_age else None
    def take_failure(self):
        with self._condition:
            value,self._failure=self._failure,None
            return value
    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda:self._pending is not None or self._closed)
                if self._pending is None:return
                epoch,scope,fn=self._pending;self._pending=None
            frame=None;failed=False
            try:
                if not self._cancelled(epoch):
                    frame=fn(lambda:self._cancelled(epoch))
                    if (not isinstance(frame,CapturedFrame) or type(frame.image) is not bytes
                            or not 0<len(frame.image)<=MAX_FRAME_BYTES
                            or not 0<=frame.captured_at<=frame.acquired_at<=self._clock()):
                        raise ValueError('Invalid bounded capture packet')
            except Exception:
                failed=True
            finally:
                with self._condition:
                    if not self._closed and epoch==self._epoch:
                        if failed:self._slot=None;self._failure=scope
                        elif frame is not None:self._slot=(epoch,scope,frame)
                    self._busy=False;self._condition.notify_all()
                frame=fn=scope=None
