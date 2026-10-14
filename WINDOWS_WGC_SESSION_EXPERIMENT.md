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
checked on Linux. They do not execute WGC or prove source/frozen Windows behavior.
Controlled Windows run 29 passed 125 regression tests and compiled the native
helper, then failed before capture when the hidden translucent Qt overlay could
not acquire exact `WDA_EXCLUDEFROMCAPTURE` (`0x11`).

Run 30 passed 129 regression tests and again compiled the helper. Its more
specific evidence on Windows build 20348 showed `SetWindowDisplayAffinity`
returning false with WinError 8 both before and after first show/paint. The same
HWND remained self-owned, top-level, layered and style-identical, with DWM
composition enabled. Affinity readback succeeded but remained zero, including
after hiding. First-show realization therefore did not resolve that failure.
The numeric error does not by itself establish actual memory exhaustion, a broad
OS limitation, or a cause inside Qt. No session pixels or frozen result passed in
those runs. Source/frozen acceptance was unproven at that checkpoint; unsupported setups and
static-window freshness timeouts are failures, not skipped passes.

### Explicit rendering-profile comparison after run 30

Microsoft documents an owned top-level HWND and DWM composition for
[SetWindowDisplayAffinity](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowdisplayaffinity),
with exact `0x11` support starting in Windows 10 version 2004.
[GetWindowDisplayAffinity](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowdisplayaffinity)
also requires a layered window. Visibility is not documented as a prerequisite.
The matching upstream [Qt 6.11.2 backing-store source](https://github.com/qt/qtbase/blob/v6.11.2/src/plugins/platforms/windows/qwindowsbackingstore.cpp)
uses the per-pixel layered-window update path for alpha-capable frameless raster
windows. Its [window implementation](https://github.com/qt/qtbase/blob/v6.11.2/src/plugins/platforms/windows/qwindowswindow.cpp)
uses the separate layered-attributes path for non-alpha windows. These sources
motivate a controlled renderer comparison; they do not establish the cause of
WinError 8. No upstream implementation is copied.

The next experiment preselects an **opaque redirected Qt fixture profile** before
attempting either profile. It first records a separate translucent compatibility
probe, including the original hidden call, one same-HWND shown retry, immediate
WinErrors, exact readback and hidden retention. That probe is destroyed and its
native destruction verified before any session or overlay registration. A failed
translucent affinity attempt remains a recorded failure for that profile; it
cannot be represented as passing production-overlay evidence.

The fixed active profile and the later same-process look-alike are non-alpha,
opaque Qt windows. They retain the same required layered, topmost, tool,
nonactivating and click-through native styles. Both must obtain and retain exact
`0x11`; no alternate affinity, style relaxation, OS setting change, capture
fallback or success-dependent renderer switch is allowed. Full actual Qt
alpha/opacity and native style observations are bound into the source/frozen
reports. Wrong owner/root/HWND/style or unavailable DWM fails the comparison,
even for the nonblocking translucent affinity probe.

Any success applies only to the explicitly named opaque fixture profile. The
production translucent overlay is unchanged and its compatibility remains
unproven. All existing pixel, fresh-request, static-window, idle-occlusion,
hidden-only CPU-request, cancellation and lifetime gates still apply unchanged.
The comparison does not prove fullscreen visibility or authorize production
integration. Numeric setup records contain only bounded self-owned metadata,
not screenshots, window titles or external process details.

### Failure-only clock evidence after run 31

Run 31 passed the 143 focused regression checks and native compilation. At source
scale 1, the fixed opaque profile obtained exact affinity `0x11` and retained it
while hidden; the independent translucent probe still returned WinError 8 with
readback zero. The first native request then failed closed at
`frame-wait` / `frame-timestamp` before any ROI pixels were returned. Helper,
pipe, Job and owned-window cleanup completed. No successful pixel/static-frame
or frozen result was established.

The diagnostic used for run 32 preserved every timestamp/freshness predicate and
deadline. Its failure-only optional `clock` object records the raw QPC counter/frequency,
request cutoff, frame timestamp, the exact converted QPC sample used by the
predicate, and the prior accepted frame timestamp. All values have exact signed
64-bit bounds. A nonpositive frame retains zero sample fields because the
original short-circuit predicate never samples QPC in that branch. Phase changes
clear the record. No extra clock sample is substituted after rejection, and no
tolerance, offset correction, frame reuse or changed timeout is introduced.

Only the isolated session parser accepts this exact optional field set at the
two timestamp-failure sites. The production v1 parser remains unchanged. Native
stderr stays capped at 1024 bytes; the always-printed bounded summary retains the
sanitized numeric failure so the next run can distinguish a zero, future, or
scale-inconsistent timestamp. Microsoft documents
[SystemRelativeTime as compositor QPC time](https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.direct3d11captureframe.systemrelativetime?view=winrt-26100);
that alone does not explain the observed failure. Actual numeric Windows evidence
is required before changing the capture predicate. A portable test compiles the
actual serializer and timestamp predicates with deterministic OS-call stubs when
a local `c++` compiler exists; it is explicitly skipped where that tool is absent.
This is arithmetic/serialization evidence, not Windows capture evidence. The
mandatory Windows helper compilation independently evaluates eight native QPC
arithmetic `static_assert` cases.

### Bounded compositor-timestamp readiness after run 32

Run 32 passed focused tests and native compilation. At source scale 1, two ROI
requests returned exact synthetic pixels (mean channel error 0.0) from the same
helper/session. The first request took 719 ms and the second 79 ms on that runner;
two samples followed by a failure are not a product latency benchmark or release
acceptance. The registered opaque overlay remained valid during the intervening
idle display. The third request failed at `frame-timestamp` with these exact
100-nanosecond values:

- Request cutoff: 24076721565
- Frame compositor timestamp: 24077031250
- Observed QPC time: 24076885278 (raw counter identical; frequency 10000000)
- Previous accepted frame: 24071250000

The frame timestamp was 14.5972 ms ahead of the sampled current clock. This does
not identify the operating-system cause. It does justify testing readiness
waiting instead of immediately treating a future-dated GPU frame as usable or
changing the clock origin.

The experimental repair retains at most one checked-out GPU frame while it is
future-dated. It continues the same strict identity/focus/geometry/occlusion and
hidden-overlay checks on the existing scheduled interval, within the original
request deadline. No texture staging, copying or mapping occurs until the frame
has a positive timestamp no later than the current clock, is strictly newer than
the request cutoff and previous accepted frame, and matches the existing exact
content geometry. Zero/negative timestamps still fail. An explicit ready flag
and a still-unexpired deadline are required before proceeding beyond the wait gate; simply
holding a frame at timeout cannot satisfy the success gate.

No tolerance, offset subtraction, timer extension, forced target animation or
old-frame reuse is introduced. Parent cancellation/watchdogs and the mandatory
three-request truly static-window test remain unchanged. The freshness evidence
is the compositor's timestamp, not independent instrumentation proving the wall
clock arrival time of the target's pixels. Full source/frozen Windows acceptance
is still required for this repair, and production remains disabled.

### Source acceptance and frozen packaging failure in run 33

[Run 33](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38623358268)
tested commit `921b8aac620ed0a5034dae3b734a47eb71c98f20`, tree
`89493e66ff030294d6d0e1dc3aec82928a0092eb`. The source diagnostic passed all
39 required checks at each of the three process-local scales. Each scale
returned four repeated ROI requests from one helper/session and three requests
from a separate truly static target session. All 21 recorded pixel comparisons
had mean channel error 0.0, with strictly increasing request/frame identities.
The active renderer was the preselected opaque profile; the separate production-
like translucent probe still could not obtain exclusion. This is not evidence
that the production translucent overlay can retain the session.

On that runner, the first repeated request took 125–500 ms and the following
requests took 62–94 ms. Static requests took 62–125 ms. These small synthetic
acquisition samples exclude OCR, production UI cadence and gameplay. They are
not a same-run comparison against the production one-shot backend. Observed
focus-loss helper exit was 93–94 ms, beyond 50 ms; cancellation cleanup was
203–235 ms, request-deadline cleanup 2109–2140 ms, and idle-lease cleanup
4015–4047 ms. These actual observations preserve the scheduling/teardown limits
described below. All owned helper, pipe, Job and window cleanup checks passed.

The frozen diagnostic did **not** run. PyInstaller completed its EXE, then the
unchanged licensed Microsoft runtime verifier rejected missing required archive
paths. The isolated spec had replaced discovered runtime entries without
explicitly supplying every required root/PySide6 path. The packaging repair
adds those paths from the existing verified licensed runtime source, retaining
the exact-byte verifier and all source/frozen checks. There is no new runtime
source, download, license exception, production integration or release claim.

### Native shutdown failure in run 34

[Run 34](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38625953942)
again passed all three source scales. Its licensed archive verification also
passed, allowing the standalone frozen diagnostic to execute for the first time.
At frozen scale 1, four repeated requests returned exact synthetic ROI pixels
from the same helper/session. Later, the native Stop case exited with
`0xC0000005` (access violation), rather than the required zero exit. Observed
process exit took 328 ms and full helper/pipe/Job cleanup 360 ms. The EOF case,
remaining frozen lifecycle/static checks and later frozen scales were not
reached. The gate remains failed; cleanup does not make a native crash graceful.

The existing failure record did not locate the crash within teardown. An
upstream [WGC cleanup issue](https://github.com/robmikh/Win32CaptureSample/issues/99)
describes internal callback/unload races, but that does not identify this crash's
cause. The next diagnostic writes a bounded, fixed sequence of seven checkpoint
tokens before event revocation, session/pool Close, implicit local destruction,
WinRT uninitialization and return. Only an abnormal exit exposes the validated
sequence and its last-started stage, alongside the original process exit code.
The stage is a localization hint, not proof of the faulting operation, module or
thread. Teardown order, exception behavior, exit requirements, all capture gates
and the 1024-byte stderr budget are unchanged. No exception recovery, arbitrary
sleep, memory dump, pixel data or raw address is introduced.
Instrumentation can change race timing. A passing checkpoint run alone would
mean the crash did not recur in that run, not that its cause was fixed; repeated,
bounded native Stop/EOF stress remains required before production promotion.

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
