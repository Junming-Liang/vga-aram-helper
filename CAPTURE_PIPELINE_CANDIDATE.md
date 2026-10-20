# Capture/recognition decoupling candidate

Baseline: `a4d46589f60e2f0958437aa772f28827f7422c43` (main); newest published item observed was diagnostic **pre-release** v0.4.16. This is an uncommitted candidate, not a release or a claim of fixed live gameplay.

## Reproduced code paths

- The persistent WGC helper has a 4-second idle lease. Previously the next actual capture request waited for OCR to finish. Slow OCR can therefore retire the helper; a later request creates another capture session.
- The enrolled visible-overlay route compared the entire standard window style. Hiding an expired recommendation changes `WS_VISIBLE`; the native watchdog treated that presentation change as an identity failure.
- OCR model setup previously happened after pixels had already received their capture timestamp. Cold setup consumed the frame's freshness budget.

These mechanisms are consistent with capture-session border changes and recommendation withdrawal occurring together. The user's observed yellow border has not been identified by an on-device trace.

## Candidate behavior

1. Prepare/verify the existing local OCR models before the first frame is captured. No synthetic observations or cache hits are created.
2. Once a valid visible-overlay capture session is established, a single producer may capture at most once every 750 ms while OCR is busy. One worker, one in-flight request, and one replaceable latest-frame slot are allowed; each frame is capped at 64 MiB. OCR remains serial.
3. A consumer uses buffered pixels only when their original capture timestamp is at most 800 ms old and the generation, discovery scope, full frame scope, and capture-session epoch match. It rechecks that 800 ms age bound both before live guards and after compositor validation, as well as process metadata and live compositor/foreground/overlay guards. Failure never falls back to silently using the buffered image.
4. Stop, cancellation, geometry/target changes, or session retirement revoke the slot and pending producer. Primary acquisition waits for producer drain. Close is nonblocking and cancels the existing bounded capture path.
5. Only the enrolled visible-overlay route ignores the `WS_VISIBLE` bit when comparing standard style. All other style bits, extended style, process/creation identity, ownership, exclusion affinity, overlay lifetime, foreign occlusion and foreground checks remain mandatory. The strict-hidden route remains strict.
6. Structured logs include bounded session-owner counts/states, request age, OCR setup duration, producer acquire/failure events, and whether a consumed frame was prefetched. No image, title, PID, process path, token or raw exception is added.

7. A normally expired OCR result from the still-current, explicitly proved frame scope clears display and confirmation continuity without retiring the healthy capture session or discarding a newer independent frame. Invalid/future timestamps, missing scope, binding changes and the existing 8-second OCR task timeout still fail closed through hard invalidation.

## Freshness and limits

The 4-second recommendation TTL is unchanged. Producer captures do not refresh observations or redisplay expired cards. Buffered images retain their original capture time. If OCR is too slow for fresh output, recommendations still disappear; session stability is not permission to display stale results.

The producer is limited to an already established, explicitly enabled visible-capable session. It does not accelerate unsupported capture routes or initial confirmation, download models early, relax permission, suppress the Windows capture border, read game memory, or inject code.

## Validation

Portable concurrency tests exercise one-slot bounds, stale scope/epoch cancellation, true timestamps, errors, close and size bounds. A real Python capture-wrapper test uses a scaled idle lease: serialized idle work terminates the helper, whereas bounded real frame requests retain the same helper across more than two lease periods. Extracted production GUI tests cover hidden TTL state, process/compositor rejection, drain and cancellation.

The owned Windows visible-overlay smoke candidate separately adds same-HWND hide/show captures, requiring unchanged helper identity and session epoch with exact expected pixels. Existing continuously-visible pixel evidence remains separate. This still needs authorized Windows execution; Linux/shim/synthetic results are not native Windows or live game evidence.

The genuine champion-select still-image report was rerun against the changed OCR initialization implementation: one recognized positive and three correctly abstained negatives, zero wrong heroes. Its existing narrow source/scene limitations still apply.

Real Qt + actual LocalOCR tests on owned synthetic frames verify acquisition continues after a >4-second inference causes legitimate display expiry, original timestamps survive consumption, and Stop clears buffered/late authority. The capture/session/process APIs in those tests are explicit doubles. The genuine HUD report was also rerun against the changed implementation: two of three positive cases recognized, one positive abstained, all three negative cases abstained, zero wrong heroes; the preexisting abstention is retained honestly.
