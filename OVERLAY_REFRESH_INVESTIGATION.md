# Overlay refresh investigation (unpublished candidate)

Baseline: `d1274e2fc8f2d7f532d8a0e019717529fb36e0f0` (v0.4.17 application
source `6c4ce8e8006e2f8b2fd18927b7204c13c7ff7ac1`). These changes are not a
release, Windows execution result, or confirmation of the reported live-game
failure's cause.

## Reproduced and changed

1. **Cold identity path serializes independent work.** When portrait templates
   are absent, `recognize_frame` previously completed the local identity API
   before starting title OCR. The prepared `PortraitMatcher` path already used
   a bounded parallel OCR worker. The candidate applies that same worker and
   unconditional join to the missing/custom-matcher path. It adds no worker,
   API request, network destination, capture privilege, or cache authority.
   Both computations must finish before any final observation is returned.
2. **No-op placement hides badges.** Updating card height or width while keeping
   the exact rendered badge bounds and regions previously hid the overlay and
   rebuilt its placement. Rebuilding retires the WGC session. The candidate
   compares effective physical placement, while preserving title containment,
   identity checks and native bounds/region verification. A real position,
   slot, identity, DPI or geometry-proof change still takes the conservative
   invalidation path. This is a proven presentation defect, not evidence that
   card-edge jitter occurs in this user's game; normal geometry reuse already
   suppresses some measurement changes.

## Regression coverage

- `tests/test_cold_identity_overlap.py` drives production Qt capture/result
  handling, `recognize_frame`, the actual four-request local API reader and
  reconciliation. Pixels and HTTP transport are owned test doubles. It checks
  overlap, reuse of one OCR worker, two independent identity observations,
  API unavailability/conflict/deadline, process-scope change, OCR failure and Stop while
  a response is held. No completed titles can authorize a missing identity.
- `tests/test_cold_identity_continuous.py` uses actual LocalOCR, the actual
  four-request API parser and autonomous Qt scheduling on owned animated
  pixels, with explicit 1.1-second minimum work in each independent stage.
  The baseline hid in all four refreshes; the candidate kept all four visible.
  This starts with a healthy enrolled capture-session double, not an initial
  native WGC enrollment. CPU-dependent long tails remain possible.
- `tests/test_badge_effective_placement.py` uses real offscreen Qt to check
  no-op geometry updates, preservation of HWND/mask, no capture retirement,
  and immediate withdrawal for real movement, missing geometry, changed names
  or titles no longer contained by a card. Native Windows calls in the owner
  test are explicit doubles, not a compositor test.

## Important remaining limits

The four-second capture-time recommendation deadline and eight-second task
limit are unchanged. A result can be individually younger than four seconds
and still leave a visible gap before the following result arrives. The relevant
steady-state budget is previous result age plus time until its replacement,
not simply whether each inference takes less than four seconds.

The existing prefetch producer only services an already enrolled visible
session. A cold strict-hidden session can still expire during long inference.
Extending that producer requires a hidden-to-visible presentation/drain barrier;
merely removing its visible-session guard is not safe.

A failure from the latest-frame producer currently invalidates the consumer
without comparing its recorded request scope. An older producer failure may
therefore affect a newer accepted result. Simply ignoring old generations is
not safe: the failure might report a current occlusion or identity violation.
A future repair needs a typed own-cancellation cause or fresh independent
current-scope validation. This behavior is unchanged in this candidate.

The normal prepared-HUD path still performs HUD matching then API resolution
on its main inference worker, in parallel with title OCR. This candidate does
not claim to solve every slow-machine budget, animated-title abstention,
exclusive-fullscreen compatibility, unavailable API/HUD, or native WGC issue.
Windows build and controlled EXE tests require separate authorized execution;
real game behavior remains unverified. No injection, process-memory reading,
or capture-protection bypass is introduced.

## Reconstruction and renewed validation

The temporary workspace was lost after the initial local validation. The two
production source files and this document's original content were recovered
from complete recorded diffs/text and matched the original frozen SHA-256
manifest. The three regression test files were reconstructed, not recovered
byte-for-byte. Their new coverage was independently reviewed: seven identity
ordering/error cases, six physical-placement cases, and one sustained refresh
case. The baseline fails the intended ordering/placement/refresh assertions;
the candidate passes them without changing product freshness deadlines.

The genuine screenshot report was regenerated with the original validation
script, the same six public images and hash-verified official roster/data.
It retains two recognized positives, one abstained positive, three abstained
negatives, and zero wrong-hero predictions. Report timing bytes are new.
Historical test totals are not evidence for this reconstructed candidate; it
requires a fresh full-suite run and separately authorized Windows validation.
