# DEFAULT-OFF persistent HWND WGC experiment

This is an isolated investigation on `experiment/persistent-wgc-session`, based on
`666aa890baf04fa05509b0045f2e3eb4f83b9e78` (the reviewed bounded-fixes tree).
It is **not enabled in VGA** and is not included by the production launcher,
helper, build recipe or spec. Only this experiment branch replaces the existing
manual workflow with a read-only, exact-branch-guarded diagnostic. Main keeps its
separate reviewed production workflow. The experiment has no release step and
requires `publish_preview=false`.
Do not merge or ship it merely because portable tests, compilation, or a subset
of Windows checks passed.

## What has and has not been run

The implementation and portable protocol/build/report-validator tests can be
checked on Linux. They do not execute WGC, exercise Windows handles, validate the
SDK compiler, or prove source/frozen Windows behavior. Controlled Windows run 29
passed the 125 regression tests and compiled the native helper, then failed in
source fixture setup before capture: the initial hidden overlay's
`SetWindowDisplayAffinity(hwnd, 0x11)` returned false. That run recorded no WinError,
DWM state or affinity readback, so it does **not** distinguish a platform limitation
from first-show/Qt realization behavior. Native capture and source/frozen acceptance
remain unproven. An unsupported desktop, an offscreen Qt backend, a missing helper,
and a static-window freshness timeout are failures, not skipped passes.

### Overlay setup diagnostics after run 29

Microsoft documents an owned top-level HWND and DWM composition for
[SetWindowDisplayAffinity](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowdisplayaffinity),
with exact `WDA_EXCLUDEFROMCAPTURE` support starting in Windows 10 version 2004.
[GetWindowDisplayAffinity](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowdisplayaffinity)
also requires a layered window. Visibility is not documented as a prerequisite;
first-show behavior is a hypothesis to test, not an explanation established by
the failed run. Qt documents that its Windows translucent QWidget path requires
a frameless top-level window; the fixture already uses that path.

Before any capture, the fixture now preserves the initial hidden call and its
immediate WinError, then shows/paints the **same owned synthetic overlay** once,
performs one bounded same-HWND retry of exact `0x11`, and hides it again. No style
weakening, unlayered replacement, alternate affinity value, OS setting change or
capture bypass is allowed. The shown retry must succeed and read back exact
`0x11`; the hidden window must retain that exact setting. Changed HWND/style,
non-owned/non-root HWND, unavailable DWM, `WDA_MONITOR` readback or another failure
still fails the fixture before capture.

`windows_version` is recorded before setup can fail. At most six bounded
`overlay_setup` records cover the registered overlay and same-process look-alike:
creation-hidden, realized-visible, and verified-hidden. They record immediate
set/get WinErrors, DWM HRESULT/composition, actual/full expected styles, visibility,
valid-root/self-owner observations and whether Qt retained the same HWND. No
window titles, image paths, screenshots or foreign process/window details are
included. This diagnostic sequence has portable regression coverage; actual
Windows results are still required before attributing the original failure.

## Existing approved Windows build environment only

Use a clean committed Windows x64 checkout and the project's existing pinned
Python 3.12 build environment, signed approved Visual Studio **Community**
compiler/runtime provenance, and Windows SDK **10.0.26100.0**. The branch-only
workflow uses the same already-authorized official PyPI requirements and free
Community tooling bootstrap as the main workflow. The experiment build and
acceptance scripts themselves do not install packages, download tools, or change
security/display/DPI settings. Package versions must match the existing pins.
Missing dependencies/toolchain/provenance are blockers; no substitutions are made.

Keep the existing runtime preparation (`scripts/microsoft_runtime.py` provenance)
and pinned build setup from the authorized Windows build environment. Then run:

```powershell
python scripts/build_wgc_session_capture.py
python tests/windows_wgc_session_capture.py
python scripts/build_wgc_session_capture.py --freeze-only
python tests/windows_wgc_session_capture.py --exe dist/wgc-session-diagnostic/WGC-Session-Diagnostic.exe
```

Run the summary step even after failure:

```powershell
python tests/windows_wgc_session_capture.py --summarize
```

`--freeze-only` preserves the exact native helper already tested from source.
`--freeze-diagnostic` is a convenience for building both in one invocation; do
not use it between source and frozen acceptance, because recompiling can change
native bytes. The standalone executable contains the fixture, Python/Qt/Pillow,
and the v2 helper. It does not add this experiment to the production VGA EXE.
There are no game/HWND/screenshot/trust-override command-line inputs.

Both acceptance invocations run independent native Windows processes at 100%,
150%, and 200% **process-local Qt scales**, verifying corresponding physical
client dimensions. They do not change the user's system scale. Frozen runs use
a clean temporary folder, remove external Python/compiler/package paths, and
require the bundled helper and manifest to match the source-tested bytes.

### Outputs and bounded CI collection

- `build/native/vga-wgc-session-capture.exe`
- `build/native/wgc-session-capture-build.json`
- `build/native/wgc-session-build.log`
- `dist/wgc-session-diagnostic/WGC-Session-Diagnostic.exe`
- `reports/windows-wgc-session-build.json`
- `reports/windows-wgc-session-frozen-build.json`
- `reports/windows-wgc-session-source.json` and `-scale100`, `-scale150`, `-scale200`
- `reports/windows-wgc-session-frozen.json` and `-scale100`, `-scale150`, `-scale200`
- `reports/windows-wgc-session-summary.json`

The scale suffixes end in `.json`. Upload only the bounded
`reports/windows-wgc-session*.json` for diagnostic CI; the bounded native build
log is printed in the build step on failure rather than uploaded. Executable/source
publication, release creation and production changes are outside this fixture. Reports contain metadata and in-memory synthetic pixel
comparison statistics, never captured images. The summary prints its entire
bounded JSON, includes all six scale runs and failures, verifies exact helper /
source / standalone EXE correspondence, and exits nonzero when any required
stage or check is missing. Native build diagnostics are capped at 128 KiB,
individual acceptance inputs and the summary at 256 KiB.

The manifest identifies schema 1, protocol **2**, profile
`hwnd-wgc-session-v2`, exact helper bytes, exact native and recipe hashes, the
source commit and source/fixture input inventory, compile/link flags, static
release CRT selection, signed compiler/linker hashes, pinned SDK header hashes,
and an allowlisted x64 system-DLL import graph. Frozen archive verification
requires the same helper bytes and manifest.

## Runtime evidence required

The fixture creates only its own synthetic Qt windows and helper subprocesses:

- Four colored ROI requests reuse the exact helper PID, creation time and session
  generation; request IDs and frame timestamps increase. A changing corner
  **outside** the ROI forces fresh frames without changing the tested region.
- A separate three-request sequence stops **all** repainting/animation. Every
  successful static-window response must still have a strictly post-request
  timestamp and use the same exact helper. Timeout is fail-closed but fails the
  enablement gate; animated success cannot mask this static-window failure.
- Exact registered, excluded, layered/noactivate/tool/topmost/transparent overlay
  can remain visible only during idle. The overlay must be hidden for every CPU
  request, even when it is wholly outside the client. Another same-process
  occluder, including an excluded layered look-alike, is rejected.
- Foreground loss, client geometry change, hidden/destroyed target, expected
  process identity mismatch, attempted HWND retargeting, and changed overlay
  style/affinity/registration/destroyed HWND retire authorization.
- Invalid native ROI, generation, duplicate request ID, and pipelined bytes are
  rejected without returning a usable image.
- Prelaunch cancellation, cancellation during a controlled suspended launch,
  Stop, native Stop, pipe EOF, four-second idle lease, the independent two-second
  request deadline, direct Job close, and abrupt exact owner-process death are
  checked. The owner-death test binds creation times on opened handles and
  verifies the owner is the exact Popen process (source) or live direct child of
  its exact bootloader (frozen), and that the helper is the owner’s child.
  Parent death proves eventual cleanup; target destruction and native lifetime
  guards may also contribute. A separate never-resumed suspended helper proves
  the Job-close kernel mechanism without running native capture code.
- Each retirement records observed revocation, exact process exit and completed
  pipe/thread/Job cleanup. GUI-facing Stop/close is checked separately from
  asynchronous teardown. Final cleanup enumerates owned reader/watchdog threads
  and verifies all owned diagnostic windows are destroyed.

## Deliberate limits and remaining enablement blockers

1. **No atomic focus guarantee.** Foreground/identity guards run before and after
   readback and changed results are discarded. Focus can change concurrently
   with a GPU copy, so this is not a promise of zero CPU activity after the exact
   instant focus is lost. OS/GPU scheduling and termination may be delayed.
2. **25 ms is a scheduled polling interval.** Every transition reports its actual
   observed elapsed time and whether process exit happened within 50 ms. The
   contract does not claim a 50 ms OS teardown guarantee. Slower measured exits
   remain visible rather than being rewritten as a scheduling estimate.
3. **Idle pixels are GPU-side.** Windows owns a full target-window GPU frame-pool
   surface while the session is alive. The reviewed native control flow only
   stages/maps the requested client ROI during a validated request. Quiet stdout
   and process CPU usage are not instrumentation proving zero idle readback;
   the report explicitly marks that runtime claim unproven. No telemetry or
   protocol counters were added to pretend otherwise.
4. **Race/driver coverage remains bounded.** A controlled suspended helper proves
   the independent parent deadline/cancel path, not all possible driver Close or
   GPU stalls. Actual numeric HWND reuse is not guaranteed by destroying a
   window; destruction/property-token tests and portable generation tests do
   not prove every Windows handle-reuse scenario. A separately controlled reuse
   and stalled-cleanup investigation remains necessary before enabling.
5. **No broader product claim.** Owned synthetic windows do not establish real
   game, anti-cheat, protected content, exclusive-fullscreen, OCR or production
   reliability. No fallback capture is considered a passing WGC result.

These limitations are mandatory report fields, and validators reject reports
that remove them or claim production enablement / proven zero idle CPU readback /
a guaranteed 50 ms teardown.
