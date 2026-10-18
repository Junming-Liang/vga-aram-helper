# v0.4.16 selection-window routing recovery candidate

Status: local candidate, 2026-10-18 UTC. No v0.4.16 Windows EXE has been built or
published. The public download remains v0.4.14. The final-source and exact-EXE
Windows gates remain mandatory; see [current validation](reports/VALIDATION.md).

## Reproduced defects

1. **Automatic game priority can block a foreground client.** The previous
   policy preferred any eligible game over a client. A background or minimized
   game could therefore bind the game role while the actual foreground window
   was the selection client. The independent foreground guard correctly denied
   capture, but selection recognition never received the client.
2. **Manual client selection depended on handoff consent.** Turning off
   automatic client-to-game following also prevented creation of the client
   selection policy. An explicitly selected client then went through the
   generic game/augment OCR path instead of selection recognition. Identifying
   the current client's role must not itself grant permission to follow another
   window.

These are controlled reproductions, not a confirmed diagnosis of the user's
reported selection, first-recognition or flicker symptoms. No new incident ZIP
establishes the installed version, game stage, HWND tree or exact field cause.

## Bounded correction

- Discovery preserves the complete eligible identity set, including minimized
  windows, for same-role and installation ambiguity checks. A separate
  availability set and the current foreground root select a role. Neither
  availability nor focus removes another same-role candidate from ambiguity
  evidence. Foreground status never grants identity or signature trust.
- The GUI obtains fresh snapshots for discovery, adoption, installation
  confirmation and capture permission. Stable HWND/PID/class, executable path,
  process creation identity, installation scope, existing trust requirements and
  exact-target foreground checks remain enforced. Opening the helper or another
  app does not silently move an existing binding to a background game.
- Manual client classification uses the accepted client classes together with
  fresh executable/process metadata. It is independent of the follow toggle.
  Following remains separately controlled; unrelated manually selected windows
  are not reclassified from a matching caption or class alone.
- Failed or malformed supported snapshots cannot fall back to a less-specific
  query. Query failure revokes current target, selection and GUI evidence and
  allows safe recovery after a valid query. Fixed `query_failed` and
  `window_unavailable` codes distinguish query failure from an unavailable
  target without recording window titles, paths, screenshots or exception text.
- Existing four-second expiry, independent confirmations, stale-result
  rejection, HUD contradictions, Stop/cancellation, capture cleanup and separate
  default-off/current-launch LCU selection consent remain unchanged.

No new window-title matching, accepted window class, renderer-process targeting,
LCU endpoint or LCU consent expansion is introduced. No proprietary Huya code or
assets are included.

## External static comparison: limited supporting evidence

The inspected [official Huya archive](https://download.huya.com/lolhexguide/00.00.45.05/lolhexguide_00.00.00.45.7z)
identifies archive version `00.00.00.45`, SHA-256
`fab88232f04a4d0e86c01dcd371065d38400780a5d01ab5991d02de5e84a1777`.
It was inspected statically, not executed, and is not asserted to be the latest
build. Native lobby tracking references `LeagueClientUx.exe` and the lobby title
`League of Legends`; game overlay code separately selects
`League of Legends (TM) Client`. Champion selection and game phases use LCU
state separately from window identity.

The explicit `RCLIENT` class check was observed in a sharing-window anchor,
not established as a universal native lobby selector. The inspected paths do
not justify authorizing `LeagueClientUxRender.exe`, adding a new window class,
or adopting title-only fallback. The product also has write operations; this
comparison does not describe the whole product as read-only. No credentials
were read and no LCU request was made during that audit. Static evidence cannot
prove the target chosen on the user's computer, current-client compatibility,
or anti-cheat behavior. The VGA fixes above are independently implemented.

## Included recovery work and build-budget correction

The three [unreleased v0.4.15 recovery fixes](REGRESSION_RECOVERY.md) remain:
equivalent warm-cache model preservation, measured capture/inference-aware idle
scheduling with a 50 ms floor and unchanged four-second expiry, and complete
validated roster availability before all portraits are ready.

[Windows run #81](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/39144535874),
source `e7bae29914d08573f93a70fc9f705eea445be606`, built v0.4.15. Both 1,977-test
Python rounds (5 skips each), source/frozen capture and native three-scale
runtime checks, selection handoff, browser and same-binary OTA gates passed.
The run then failed at the anonymous artifact inventory API with HTTP 403,
before final verification or publication. No v0.4.15 release was made; this
candidate combines its changes with the routing and budget corrections.

The budget checker now uses the existing job token only for the fixed GitHub
repository artifact-listing GET endpoint and refuses redirects. It neither
creates credentials nor changes billing. The 500,000,000-byte project budget,
10,000,000-byte reserve, conservative upload accounting and fail-closed behavior
on unknown/incomplete inventory remain unchanged.

The intermittent helper failure in Run 80 remains unexplained. Later source and
frozen diagnostic passes across 32 switches are bounded fixture observations,
not proof of the failure's cause or a field fix.

## Validation boundary

`tests/test_selection_window_routing.py` uses an owned window table and real Qt
controls with injected process/signature metadata; dispatch is intercepted
before pixels or APIs are read. It covers foreground role selection, minimized
ambiguity, identity reuse, stale adoption, manual follow-off routing, independent
consent, failure revocation, recovery and repeated transitions. These tests
cannot stand in for real Win32 windows or the frozen application.

The current genuine still-image reports were actually regenerated for v0.4.16
and their evaluated-module hashes checked. Hero: 2 of 3 positives recognized,
1 abstained; all 3 negatives abstained. Selection: 1 positive recognized and
all 3 negatives abstained across 2 distinct negative scenes. Neither sample
produced a wrong hero; neither establishes current stock-client or live-game
accuracy. The images are not redistributed.

The final portable suite passed 2,043 tests with 15 platform-dependent skips
in 244.431 seconds. The final Windows run remains pending. Owned source/frozen
Windows fixtures, including manual
follow-off selection evidence, must pass with the final exact EXE. Final
verification must bind the source SHA, run, digest, size and full evidence
bundle. Historical runs cannot substitute. Publication remains an explicit
separate choice after the gates, with `prerelease=true`, `make_latest=false`
and normal manual validation defaulting to `publish_preview=false`.
