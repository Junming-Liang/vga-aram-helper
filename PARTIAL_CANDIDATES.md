# Safe partial title integration

`partial_candidates.py` is a pure, UI-independent component. `recognize_frame`
now supplies its evidence and `ControlWindow` maintains separate per-slot state
and fixed-slot partial display. Full-triplet `state.confirmed` semantics and
the existing capture/hero guards remain separate.

## Evidence input

In `recognize_frame`, after local OCR returns, build evidence from **all** its
raw `ocr_lines`, using the already computed crop `top`, full `frame_height`,
OCR crop `image_size`, and the same vocabulary snapshot:

```python
from partial_candidates import title_evidence
result['partial_title_evidence'] = title_evidence(
    result.get('ocr_lines'), result.get('image_size'), vocabulary,
    crop_top=top, frame_height=frame_height)
```

Do not derive this from `candidates` or `automatic_candidates`: both discard
unknown dictionary titles, and the latter already drops low-confidence rows.
Three known candidates are not required, but three explicit title-shaped OCR
rows are. Missing, extra, malformed, overlapping-column, repeated, or unaligned
rows fail closed. The center must be within the current full-frame .32–.55
title band. Existing crop-relative size/column/alignment bounds are preserved.
Validated symbol-only decoration (for example, OCR detecting a dot as `●`) is
not a textual title and is excluded. It can never supply a missing title row;
Unicode letters/digits, including Chinese and fullwidth text, remain textual.

An unknown or low-confidence row can prove the presence of its title-shaped
box; it produces no display name. Known names require unique NFKC/whitespace
literal dictionary equality, preserving punctuation, and raw confidence >=.93.
There is no fuzzy, containment, previous-name, or title-position substitution.

These are OCR geometry checks, not proof of game context or physical cards.
Existing target, foreground, occlusion, HUD, capture-exclusion, and scene guards
remain mandatory; malformed or missing evidence never weakens those guards.

## Per-slot state

Keep one `PartialCandidateState` on the GUI thread. After the existing result
generation, capture provenance, current geometry, foreground, freshness, scene,
and confirmed current-hero checks pass:

```python
names = partial_state.observe(
    value['partial_title_evidence'],
    frame_serial=value['_captureSerial'],
    captured_at=value['_capturedAt'], now=time.monotonic(),
    context=(target_identity, roi, source_identity, confirmed_hero, scene_token),
    guards_passed=True, ocr_reused=value.get('ocr_reused'))
```

The context must bind all frame/hero/data inputs, remain stable through normal
matching captures, and change on true scene lifecycle changes. Do not use an
incidental UI generation that increments on every ordinary triplet change:
that would reset unaffected slots and prevent partial continuity. Existing
worker-generation checks still reject stale work before calling this method.
The first confident hero observation may seed private title continuity, as in
the full-triplet path. Nothing partial is displayed until the same hero has
passed its existing two-observation confirmation; unknown hero evidence clears
the partial state.

Every known slot needs two independently OCR'd matching new captures, with a
capture-to-capture evidence gap <=4 seconds. Both serial and capture timestamp
must increase. `ocr_reused=False` must mean OCR really ran on that capture.
Missing provenance fails closed. Cache hits may sustain already confirmed
matching slots only when the existing cache has proven exact current crop
pixels and the current target/HUD guards passed. They cannot seed or increment
confirmation. If pending slots remain, continue forcing fresh OCR rather than
allowing cache hits to starve their second observation.

The returned tuple always has three entries, in left/middle/right order, with
`''` for every unknown, unsafe, changed, or not-yet-stable title. Never compact
this tuple. Never fill an empty slot from a previous frame or retained tier.

Call `clear()` on Stop, focus loss, occlusion, target/ROI/source change, unknown
or changed hero, manual editing, capture failure, and scene invalidation. A
failed `guards_passed` also clears. Existing caller guards remain authoritative;
this module cannot inspect a window or verify that the caller ran those guards.

For timer refreshes, use `visible(now)` and the same current external guards.
Visibility expires strictly after four seconds from the accepted capture time.
Both module and UI retain private continuity across display-only TTL expiry so
an in-flight, still-fresh independent capture can complete safely. OCR cache
hits cannot reauthorize an expired display. Display code must never read the
module's private retained fields directly.

## Rendering contract

- Resolve each nonempty name against the **current confirmed hero/current
  data** only, keeping its original slot number. Use the existing literal
  `source_tier` rules and do not invent a tier for missing source data.
- Empty slots show a neutral waiting/unknown placeholder with **no old name,
  source tier, details, or notes**. Clear an unsafe slot in the same GUI update
  that processes the observation.
- Existing `RecognitionState.confirm()` is a three-valid-name manual/full
  automatic path. Do not pass partial tuples to it or label them as three-card
  confirmation. A partial renderer needs explicit state and labels.
- Overlay visibility, accepted-frame restoration, history, cache eligibility,
  capture scheduling, and TTL currently key off `state.confirmed`; update those
  deliberately if integrating this feature. In particular, old full-triplet
  history/restore references must never refill a new empty slot.
- Manual confirmation continues to require three distinct known names. Partial
  results must not become input to any selection/click action.

## Verification

Run `python -m unittest discover -s tests -p test_partial_candidates.py -v`.
The pure tests cover three-row geometry, unknown middle slots, exact/confidence
gates, repeated rounds, changing individual slots, cache provenance, replay,
source/hero/window context, invalidation, and the four-second boundary.

With optional local OCR/Qt dependencies, run
`python -m unittest tests.test_partial_candidates_qt -v`. Those tests exercise
the real worker/handler, real OCR on original synthetic artwork, raw unknown
title rows, three rounds and reroll, fixed-column rendering, unsafe-slot
clearing, focus/ROI/source/hero/manual/Stop invalidation, exact 4.0/4.001-second
expiry during inference, and rejection of cached promotion. The low-confidence
and missing-row boundary cases explicitly modify one real OCR result.

The Windows EXE smoke has an additional actual captured-window, real-OCR
unknown-middle test; it must be run on Windows. Portable tests or synthetic OCR
cannot establish live-game accuracy or flicker behavior.
