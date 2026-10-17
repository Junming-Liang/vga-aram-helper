# v0.4.10: published preview — game identity and per-card display

This implementation was released on 2026-10-17 after [Windows run #71](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/39015163655) passed all required source/frozen gates. It remains a non-latest prerelease requiring manual download. Owned-fixture acceptance does not establish live-client or user-game acceptance.

## Current-game identity

The local, read-only Game Client API check is enabled by default and has a visible
Off switch. The separate League Client selection API remains off by default.
Only the existing verified loopback endpoints are used; no game memory, injection,
input automation, or account data is stored. The two preference booleans are saved
locally. Older versions had no saved explicit preference for these controls.

Two independent strong own-HUD/API captures establish a private hero identity.
It can survive supported portrait obstruction, death countdowns, temporary API
unavailability, focus loss and resizing for the same verified game process.
There is no arbitrary 120-second identity expiry. Its scope binds the monitoring
session, HWND/PID/class, executable path and creation time, and exact canonical
champion/source/matcher mapping. Stop, a new binding/client phase, source changes,
positive identity contradictions and known unsupported layout revoke it.

This retained identity is labelled historical. It never changes a raw unknown
portrait result into a confident recognition and never renews strong-proof time.
It is not a detector of every possible spectator/replay transition. Every display
still needs current authorized capture, full three-card title evidence, independent
confirmation, and the existing four-second offer freshness bound. Blank/foreign
scenes cannot display cached offers. Partial-card recovery with historical identity
is intentionally not supported initially.

## Animated cards and display

Exact full-column title-band fingerprints permit an accepted result to remain
visible during fresh OCR when pixels outside the title bands animate. Any changed
title-band pixels revoke this shortcut; no fuzzy image matching or OCR confidence
relaxation is used. Historical-identity recovery runs fresh OCR, including when a
parallel title-cache hit races a newly unknown HUD observation.

Three small grade badges, with optional short source-combo examples, are positioned above detected card rectangles from the
same captured full client image. The implementation uses three disjoint native
window regions on one exact-owned, capture-excluded HWND. Gaps remain unpainted
and noninteractive. Badge width adapts from 104 to 160 DIP with height 52 and an 8 DIP top gap; full hint text remains available in accessible text and the control-window details. Missing, ambiguous, clipped, overlapping or out-of-bounds
geometry hides the badges; titles and descriptions are not covered by a fallback.

Protected visible capture still requires all original exclusion, foreground,
process, geometry and foreign-occlusion guards. Unsupported capture routes may
still hide the overlay for safe capture. The control window now explains that
routing reason instead of implying every machine has a blink-free backend.

## Window preferences and source freshness

Starting monitoring leaves the control window visible by default. Automatic
minimization remains an optional saved setting, including installation confirmation.

The live public catalog audit on 2026-10-17 found Huya package 395 unchanged from
the prior fetch: source date 2026-09-07, declared patch 16.17, 209 augments. This is
not represented as the newest game patch. Missing text, missing catalog entries
and missing hero-specific tiers are separate possibilities.

## Validation limits

Portable tests cover synthetic death/countdown observations, session boundaries,
unknown/changed heroes, fresh OCR, animated title regions, native-region contracts,
and genuine public card geometry. Windows capture/compositor, DPI, handoff, badge
region, executable and update gates must all pass before publication. Public stills
and owned test windows do not establish this user's live-game performance.

Source-combo hints are exact current-hero/current-card ID joins to a public source example. They do not assume earlier selections or prescribe a future selection order. Absent, ambiguous, deleted or unmatched entries produce no hint. Long hints are visibly elided; complete names and provenance remain in the control details.

The same-frame RGB decode is shared only within one inference call for border
verification. It is not retained in accepted proofs or written to disk. A local
nine-sample interleaved benchmark of the same public 2560×1440 modal measured
821.5 ms released versus 826.3 ms candidate with fresh boundary verification.
That small difference is within observed variation, not a live-game speedup.
The intended improvement is avoiding withheld/repeatedly reset results during
supported death or background animation. Windows capture, Qt dispatch and local
API request time are excluded from this benchmark.
