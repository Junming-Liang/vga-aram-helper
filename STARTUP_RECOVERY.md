# Startup recognition recovery audit

This audit addresses reproducible startup failure/recovery behavior after the
v0.4.13 capture-stability changes. It does not identify the cause of an
unrecorded user incident or claim a real-game acceptance pass.

## Reproduced defects and changes

- With no complete cache, one temporary official portrait-download failure
  previously left both HUD templates and the disk-backed canonical API map
  unavailable for the rest of the launch. Automatic monitoring now retries an
  empty bank with 30/60/120/300-second capped backoff and one worker lease.
- A usable complete cache previously waited for the online version check.
  It is now delivered before network refresh. A same-bank final result keeps
  matcher identity, and failed/empty refresh cannot remove the usable bank.
- A completely downloaded bank could remain usable only in memory after a
  cache-write failure, while API mapping stayed unavailable. Its validated
  public token-to-ID reference mapping now has an immutable in-memory fallback.
- Invalid nested roster image types (and malformed cache manifest/hash object
  shapes) could raise AttributeError outside the intended rejection path,
  aborting a frame before independent HUD/card OCR. Explicit shape validation
  now rejects them safely. Duplicate canonical slugs are also rejected.

All complete-bank/hash/TLS checks remain. No cached player identity is added.
API double-read, self-match, process/window scope, HUD contradiction, per-slot
confirmation, and frame freshness thresholds are unchanged. Start/Stop does not
reset network backoff. Manual mode, disabled updates, stopped monitoring,
Close, duplicate terminal callbacks and stale attempts cannot start overlapping
retries or replace current assets.

## Forward fault-injection coverage

The added suites exercise real application handlers and local inference with
owned synthetic pixels, transport and Windows metadata:

- First window absent then bound; discovery and acquisition errors then retry
- First result past the 4-second freshness deadline; 8-second watchdog timeout
- Stop/Start while an old worker is still draining; stale generation/serial
- Initially absent/partial cards and late-arriving identity templates
- Cold network failure then recovery; warm cache with blocked online lookup
- Memory-only complete bank; malformed/incomplete/corrupt/cancelled assets
- Temporary API failure then two fresh identity observations; consecutive games
- Template lifecycle faults, retry gates, capped backoff and matcher failures

The cold/stale-frame cases recover after the required independent fresh
observations. A permanently hung native call is still not forcibly killed;
its acquisition barrier remains until it returns or the process is restarted.

Diagnostics retain fixed template/identity causes, correlation and bounded
history. A synthetic 45-minute two-scope replay including early template failure
and 52 worker errors preserves the causes across rotation within existing
768 KiB source-log / 832 KiB export caps. No screenshots, player payloads or
exception messages are added to the debug ZIP.

Windows capture and packaged-runtime verification must be reported separately
from portable offscreen Qt/synthetic checks. The small public screenshot
benchmark retains its abstention and safety limitations.
