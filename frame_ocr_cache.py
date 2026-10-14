"""Short-lived reuse of OCR for byte-identical, newly captured title crops.

This is an inference cache, never a frame source. The caller must capture and
validate a new target-window frame on every observation, run fresh hero/scene
checks, and attach that frame's timestamp outside the cached result. No image
bytes are retained, written, or sent anywhere. Perceptual similarity is never
sufficient to reuse a title because a one-character change can alter its name.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import threading
import time


class FrameOCRCache:
    def __init__(self, *, max_age=2.5, clock=time.monotonic):
        if not 0 < max_age <= 3:
            raise ValueError('OCR reuse must expire within three seconds')
        self.max_age = float(max_age)
        self.clock = clock
        self._lock = threading.Lock()
        self._epoch = 0
        self._entry = None
        self.hits = 0
        self.misses = 0

    def clear(self):
        """Revoke both existing entries and any in-flight worker's later store."""
        with self._lock:
            self._epoch += 1
            self._entry = None

    def scoped(self, engine, scope, *, allow_reuse=False):
        with self._lock:
            epoch = self._epoch
        return _ScopedOCR(self, engine, scope, epoch, allow_reuse)

    def _recognize(self, engine, scope, epoch, image_bytes, vocabulary, allow_reuse):
        # Preserve vocabulary order/content as well as exact compressed pixels.
        # Capture's PNG encoding is deterministic; different encodings simply
        # miss the cache, rather than risking a false unchanged-frame decision.
        names = tuple(vocabulary)
        key = (id(engine), scope, names, hashlib.sha256(image_bytes).digest())
        started = self.clock()
        with self._lock:
            entry = self._entry
            if allow_reuse and epoch == self._epoch and entry is not None:
                old_key, observed_at, result = entry
                if old_key == key and 0 <= started - observed_at <= self.max_age:
                    self.hits += 1
                    copied = deepcopy(result)
                    copied['ocr_reused'] = True
                    return copied
            self.misses += 1
        result = engine.recognize(image_bytes, names)
        # Never cache an exception or let an invalidated worker repopulate it.
        with self._lock:
            if epoch == self._epoch:
                self._entry = (key, started, deepcopy(result))
        result['ocr_reused'] = False
        return result


class _ScopedOCR:
    def __init__(self, cache, engine, scope, epoch, allow_reuse):
        self.cache, self.engine, self.scope, self.epoch = cache, engine, scope, epoch
        self.allow_reuse = allow_reuse

    def recognize(self, image_bytes, vocabulary):
        return self.cache._recognize(self.engine, self.scope, self.epoch,
                                     image_bytes, vocabulary, self.allow_reuse)
