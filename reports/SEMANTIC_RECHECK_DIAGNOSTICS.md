# Semantic recheck diagnostic candidate (v0.4.13)

Baseline release: v0.4.12, source `966f79ea7305d716d6ae854432cf20a08344e985`.

## Contract

- Raw title-band pixel variation is not proof of a changed title. Fresh same-frame ordered-title OCR, literal confidence, geometry, identity scope, generation, capture serial and expiry govern presentation.
- Pending semantics does not renew the accepted observation. Historical grades can remain only until their original four-second deadline; changed or uncertain semantics revoke them as soon as available. A real reroll is not detected instantaneously. Known geometry, identity and scope contradictions revoke immediately.
- Partial displays have separate scoped per-slot authority: fresh same-frame evidence preserves independently confirmed known slots, and uncertain or changed slots lose their old counts without borrowing another slot’s proof. Unknown slots expose no old grade or accessible identity. Manual/unscoped partials remain conservative.
- Neutral checking presentation does not show an old grade, hint or accessible identity. Unchanged valid semantic titles must not alternate grades with checking text merely because non-text pixels varied.
- Logs retain critical transitions and bounded contextual traces separately from routine sampling. Total on-disk diagnostic files remain at most 768 KiB; no screenshots, raw OCR, credentials or player identity are recorded or uploaded.
- Selection eligibility diagnostics explain discovery and routing gates without changing authorization or claiming an unobserved real-client fix.

## Verification in progress

- Synthetic 45-minute, roughly 25-observations/second log replay retains early selection gates and late slow-inference/stale-drop/visibility causes in the exported ZIP after routine rotation. Independent privacy and export-causality review passed.
- Windows visible-overlay fixture now changes original non-text pixels inside an accepted title hash band. Actual local OCR independently returns the same three ordered titles, while the exact pixel hash fails. The Windows gate requires unchanged names, no native hide/show churn and no grade/checking text transitions. This is not yet a Windows pass.
- Existing source/frozen capture, native OCR, selection handoff, geometry, exact-source, package and OTA gates remain required. Actual-game results remain unverified.

- Independent offscreen real-OCR check: 12 partial animation cycles and all 48 capture/title/final phases retained two known grades, HWND and region geometry, with zero hide or checking transitions. A formal regression additionally executes four uncached real-OCR animation cycles. These are synthetic, not actual-game or Windows-compositor proof.

- Final Linux checkpoint: 1,709 Python tests passed (14 platform skips), plus 35 JavaScript checks. Original public screenshot fixtures were genuinely rerun: hero 2/3 positive recognized (one abstention), all 3 negatives abstained; selection 1/1 positive recognized, all 3 negatives abstained, zero wrong identities. Reports bind the current implementation hashes.
