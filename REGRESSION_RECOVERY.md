# Historical v0.4.15 regression recovery investigation (unreleased)

The v0.4.14 diagnostic prerelease is published. The user reported flicker and an
unresolved initial-recognition failure after that publication. The installed
version, game stage and exact field cause were not confirmed by a new diagnostic
ZIP. These fixes address reproducible defects;
controlled tests do not establish that every reported field symptom is solved.

## Proven defects and bounded changes

1. **New in 0.4.14: warm-cache replacement during recognition.** A cached bank
   can establish a confirmed display before a successful background refresh.
   Replacing its matcher during an in-flight capture changes the frame scope,
   correctly discarding that capture but unnecessarily clearing the display.
   Exact decoded pixels and champion-name mappings now identify equivalent
   banks. Different usable banks are staged until Stop or an actual accepted
   window/process transition, after old authority is revoked. A first usable
   bank still enables recovery. If fresh API identity already supplies display
   authority, or recognition is in flight, the first bank is also staged. Once
   idle without display authority it activates, so temporary API failure or
   expiry cannot strand HUD recovery. No frame-scope checks are bypassed.
   Verified decorative portraits can still refresh independently: a matching
   client reference updates its fixed-size image in place without rebuilding
   the strip, changing recognition authority or hiding its window.

2. **Existing in 0.4.13: idle scheduling consumes the refresh deadline.** On an
   owned moving scene with real local OCR and Qt timers, injected acquisition
   and processing produced frames aged about 1.84 seconds on receipt. A fixed
   700ms pause repeatedly crossed the old observation's 4-second deadline.
   Scheduling now reserves measured capture + inference cost and a bounded
   margin. The same scenario selected roughly 125–160ms pauses with no hides.
   There is always at least 50ms idle, explicit error backoffs are unchanged,
   and the 4-second observation/acceptance deadline is unchanged. Unexpected
   long-tail work and work too slow for the budget still hide expired grades.
   Expiry is logged before geometry clearing so the first hide names its cause.

3. **Existing cold-start dependency: API lookup waits for every portrait.** A
   complete validated official roster can arrive while one portrait download
   is blocked. Previously this still left the canonical API dictionary empty.
   A separate immutable roster-ready callback now supplies that lookup before
   image readiness. Version, complete mapping, duplicate IDs/assets, attempt
   lease and cancellation gates are checked. Portrait manifests still publish
   only after all image hashes/decodes succeed. Fresh API self-join, repeated
   reads, process scope, HUD contradictions and source-name gates remain intact.

## Reproduction and acceptance

- `tests/test_capture_cadence_dynamic.py`: real Qt event loop and local OCR on
  owned moving pixels; fixed-delay failure, measured-delay recovery, sustained
  impossible budget and an unexpected over-age tail. Prints monotonic capture,
  completion, receipt, scheduling, deadline and hide timelines.
- `tests/test_portrait_refresh_boundaries.py`: repeated copied banks and changed
  banks during real OCR, model identity, Stop/new-process boundaries, first
  usable bank and stale roster callbacks.
- `tests/test_roster_ready_publication.py`: block a portrait after the complete
  public-format roster and verify the unchanged API's four reads can identify
  the hero before the image bank exists; malformed/cancelled input fails closed.

No private screenshots or diagnostic archives are included. Windows compositor
and actual-game verification remain separate from these portable regressions.

## Candidate and publication status (updated 2026-10-18 UTC)

- The earlier local-only/no-EXE checkpoint is superseded. [Windows run #81](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/39144535874), source `e7bae299`, built v0.4.15 and passed both 1,977-test Python rounds (5 skips each) and the existing source/frozen runtime gates. An anonymous artifact-budget API HTTP 403 then blocked final verification and publication. No v0.4.15 release was made.
- These fixes are retained in the current v0.4.16 candidate alongside the [window-routing and budget corrections](WINDOW_ROUTING_RECOVERY.md). No v0.4.16 EXE or complete final-candidate Windows pass is established here. See [current validation](reports/VALIDATION.md).
- Normal manual validation remains `publish_preview=false`. Publication requires a separate explicit choice and every existing source, package, license, same-EXE, update/rollback and evidence gate on the final candidate. Historical runtime passes cannot substitute for that final run.
- The historical promotion script/workflow remains fixed to the original v0.4.14 Run 78 artifact and its unchanged original verifier. It is not a release path for v0.4.15 or v0.4.16.
- Genuine still-image reports must be regenerated by their runners after the version or evaluated source changes. Their versions/hashes cannot be hand-updated to claim a fresh evaluation.
