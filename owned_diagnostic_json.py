"""Bounded live publication polling shared by owned Windows diagnostics."""
from __future__ import annotations
import errno
import sys


def poll_owned_json(path, reader):
    """One attempt at an owned live fixture publication, never a final artifact.

    The caller retains its original deadline, liveness and full payload checks.
    No cached/partial payload is returned. Windows replacement can briefly deny
    a reader; CRT opens may expose EACCES without a native winerror attribute.
    """
    try:
        value = reader(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        code = getattr(exc, 'winerror', None)
        if sys.platform == 'win32' and (
                (type(code) is int and code in (5, 32, 33)) or
                (code is None and isinstance(exc, PermissionError) and exc.errno == errno.EACCES)):
            return None
        raise
    if type(value) is not dict:
        raise AssertionError('Owned live JSON publication is not an object')
    return value

