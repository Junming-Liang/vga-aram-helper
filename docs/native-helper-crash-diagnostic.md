# Bounded, owned-helper crash diagnostic

This is a diagnostic, not a product fix or Windows acceptance gate. It does not
change production code, helper build flags, capture/idle deadlines, teardown,
release versions, or the existing acceptance workflow. A newly built helper is
bound to its source and build hashes; it is not described as the unavailable
binary from run 91.

## Scope and stopping rule

The manually dispatched workflow is restricted to a disposable GitHub-hosted
`windows-2022` runner, the public repository's exact `main` dispatch commit, and
`github.run_attempt == 1`. Permissions are `contents: read` and `actions: read`;
checkout credentials are not persisted. There is one owned fast-fail canary and,
only after that succeeds, one source-native duty-lifecycle attempt at app scale
1.0. The job limit is 45 minutes. It does not access a user
computer, attach to a game, enumerate processes by name, rerun a failed attempt,
publish a release, or build a release EXE.

An earlier native-smoke failure blocks the targeted observation. A clean helper
exit, absent crash, changed owner, exhausted deadline, malformed evidence, or
incomplete cleanup stops the attempt. Non-reproduction is not a fix. A diagnostic
artifact can be useful while the original native smoke remains failed; it never
turns that failure into product acceptance.

## The exact reproduction route

The launcher observes the existing persistent capture owner immediately before
the owned mock's `changed_title` paint, after the existing independent captures
have returned guarded-idle evidence. It retains the actual owner, session,
transport, process handle, PID, creation time, executable identity/hash,
generation, strict-hidden mode, and owned Job membership. CDB attaches only to
that already-running child, never to a name match or a replacement process.

Attachment is capped by the lesser of 1.5 seconds and the actual remaining idle
lease. The production idle deadline starts at submit, not at frame return. The
probe must not renew it. The assertion-only capture-entry observer checks the
retained identity again after Qt event pumping. If production has retired or
replaced the owner, the diagnostic stops rather than redirecting the request or
preventing retirement.

After the unchanged capture call, the diagnostic also verifies that the same
retained session/transport/process/generation handled exactly the next request.
A successful return must have a matching fresh receipt. A replacement inside
production capture cannot be attributed to the already-attached helper. The
original capture exception is preserved, rather than replaced by a diagnostic
exception or successful status.

The normal two-second request deadline and four-second idle lease stay active.
Stack collection may lose the race against the independent watchdog, which is
an inconclusive diagnostic rather than permission to extend a deadline.

## Debugger preparation and canary

`scripts/prepare_windows_debugger.ps1` first checks the standard installed x64
CDB. It validates PE architecture, Microsoft Authenticode signature, version,
size, and SHA-256. If absent, the authorized flow permits at most one official
Windows SDK 26100-family installation of
`OptionId.WindowsDesktopDebuggers`, with a ten-minute limit and no reboot.
The public SDK license must match the approved SHA-256 and size; a changed
license or unsupported/untrusted tool stops preparation. Installation writes
ordinary installation/registry state on the disposable runner. It is not a
claim of zero operating-system writes or of inspecting hidden bootstrapper
terms. No global WER, postmortem-debugger, security, or symbol settings are set.

Tracked checkout inputs and both unchanged helper binaries/manifests are hashed
before preparation and rechecked afterward. The local proof contains paths and
installer metadata but is not an upload artifact. The Python launcher verifies
its required inventory and file bytes again before and after observation.

CDB starts with a fixed local command file, exact `-p` PID, `-G -pd -sins
-noshell -nosqm`, and an empty local symbol directory. Ambient debugger symbol
and extension paths are removed. The command sequence configures second-chance
`0xC0000409`, displays `sx`, emits an exact nonce-bound ready marker, then runs.
On the exception it emits marked `.exr -1`, `k 20` (32-frame maximum), and `lm o`
(loaded modules only), then uses `gn` to leave the exception unhandled. No live
`.ecxr`, dump command, shell, memory write, binary patch, or network symbol
download is used.

The tiny owned C++ canary waits for its parent's trigger, then calls
`__fastfail(7)`. The same attach protocol must capture subtype 7, the original
unhandled fail-fast exit, and complete cleanup before the real probe runs. The
ready marker alone does not prove successful attachment/resumption; the canary
checks the full sequence. A canary or parser failure ends the single attempt.

## Data boundary

The diagnostic writes no screenshots or memory dumps, even locally. Actual
capture and OCR remain in memory and unchanged. The source native smoke normally saves a final
synthetic mock/overlay PNG after the duty probe. The diagnostic stops at the
duty-probe completion callback, before the original `verify_overlay` callback
and its screenshot save can run. It deliberately does not complete the full
native acceptance route and does not fake a successful image write. Existing
failure/cleanup handling still runs after this diagnostic stop.

Debugger output is bounded in memory and is not uploaded raw. Only validated
exception status and fast-fail subtype, module-relative fault/stack locations,
hashes, bounded timing/fixture identity, original failure status, and cleanup
facts may enter the diagnostic artifact. No absolute addresses, arbitrary
exception parameters, local/user paths, arguments, locals, environment values,
screenshots/pixels, helper executables, debugger binaries, or memory dumps are
published. Missing or incomplete exception/stack blocks are not success.

Raw CDB output is capped at 256 KiB in memory. The exported schema is capped at
64 KiB and contains source/fixture hashes, hashes of both built helpers and
their manifests, bounded debugger identity, integer attachment budget/elapsed
microseconds, validated crash records, exact-request/return flags, sanitized
session failure evidence, and cleanup flags. Module names and relative offsets
are retained, never raw stack text. An unknown field, malformed stack, unmapped
or overlapping module range, unloaded-module section, missing/duplicate marker,
or output overflow cannot produce a complete crash record.

Only `build/owned-crash/evidence/reports/windows-wgc-helper-crash.json` is
uploaded. The workflow independently rejects duplicate/nonfinite JSON, symlinks,
extra files of any type, and more than 1 MiB total; it then applies the unchanged
repository artifact-budget gate. Retention is one day. No raw debugger log,
local debugger proof, native report, or executable is uploaded.

## Invocation and results

After authorized preparation and the two existing helper builds, the workflow
calls the launcher exactly once:

```text
python tests/windows_wgc_helper_crash.py --debugger-proof build/owned-crash/debugger.json --reports build/owned-crash/evidence
```

An existing output directory stops the launcher before it starts another canary.
There is no scale matrix or automatic rerun.

- `crash_recorded`: complete bounded evidence, successful canary, exact next
  request attribution, original fail-fast exit, and cleanup were verified. The
  launcher still exits nonzero; this is not a passing product gate.
- `not_reproduced`: the two duty passes completed, the target request returned,
  the observed helper exited cleanly, and all diagnostic prerequisites passed.
  The launcher may exit zero, but the source smoke was deliberately stopped
  before its screenshot/full-acceptance stage. This does not mean fixed.
- `inconclusive`: an earlier failure, unsupported tool, owner change, deadline,
  incomplete parser output, or cleanup problem prevented a conclusive result.
  The launcher exits nonzero and does not retry.

## Interpretation and local checks

`0xC0000409` is a fast-fail status, not sufficient evidence of stack corruption,
a particular WGC defect, or causation by a recent product change. Its first
validated exception parameter may identify a fast-fail subtype. With no PDBs or
network symbol acquisition, module-plus-relative-offset frames may have no
function names or source lines.

The portable tests use synthetic process/OS objects and the unchanged production
Python transport. Passing them does not verify Windows debugger attachment,
actual helper cleanup, native capture, or live-game behavior. Those observations
require the separately authorized, single Windows diagnostic attempt. Existing
formal Windows/source/frozen-EXE acceptance remains required for delivery.

Portable regression command:

```text
python -m unittest tests.test_windows_wgc_helper_crash -v
```

Coverage includes the real production Python transport's signed/unsigned
fail-fast EOF behavior (no decode, retry, parent kill, or status promotion),
exact-owner/receipt/lease races, the actual launcher hook around a synthetic
event-pump boundary, one-canary/one-probe budgets, screenshot-route exclusion,
CDB parser/launch bounds, tool-proof validation, artifact schema, and the real
inline upload gate. PowerShell checks in this suite are static contracts, not
Windows or installer execution tests.

Local verification on Linux, 2026-10-22: the 56 diagnostic tests plus the 20
existing session/native-smoke failure-evidence tests passed, 76 total, with
`QT_QPA_PLATFORM=offscreen` and the available PySide6-enabled Python environment.
Python compilation and whitespace checks also passed. No Windows helper,
debugger, installer, CI run, or native acceptance was executed by those checks.

## References

- [Microsoft fast-fail intrinsic](https://learn.microsoft.com/en-us/cpp/intrinsics/fastfail?view=msvc-170)
- [CDB command-line options](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/cdb-command-line-options)
- [Debugger exception filters](https://learn.microsoft.com/en-us/windows-hardware/drivers/debuggercmds/sx--sxd--sxe--sxi--sxn--sxr--sx---set-exceptions-)
- [Exception record display](https://learn.microsoft.com/en-us/windows-hardware/drivers/debuggercmds/-exr--display-exception-record-)
- [Propagate an unhandled exception](https://learn.microsoft.com/en-us/windows-hardware/drivers/debuggercmds/gn--gn--go-with-exception-not-handled-)
- [List loaded modules](https://learn.microsoft.com/en-us/windows-hardware/drivers/debuggercmds/lm--list-loaded-modules-)
- [Official debugging tools download](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/debugger-download-tools)
- [Windows SDK license](https://aka.ms/WinSDKLicenseURL)
