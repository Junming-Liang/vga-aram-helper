# Capture stability diagnostic changes (v0.4.12 prerelease)

Baseline: `fcf6ed1c87c11ad18fddd5c793d1ad06fd5ab4ed` (v0.4.11).
This report records source, controlled local, and Windows synthetic-window validation;
it does not establish live-game compatibility. Public-image reports were regenerated only by actually
running the original validation scripts on the unchanged original image bytes.

## Changes

- Keep the same badge window, region and placement when only the same hero/card
  identities' provenance, source text, or tiers change. Real identity, slot,
  pending-state and geometry changes still hide/rebuild. Two new regressions
  reproduce the old unnecessary-hide behavior on baseline; eight alternating
  provenance cycles no longer hide or reinstall a mask.
- Avoid mathematically impossible fuzzy comparisons. The upper bounds preserve
  the original .78 acceptance and .10 ambiguity requirements. Six hundred
  seeded differential cases compare against the unpruned algorithm. A synthetic
  matching-only sample (25 description rows × 500 names, seven runs) measured
  297.56 → 2.86 ms median. This is not an OCR-engine/live-game speed claim.
- Enable this diagnostic build's local log by default, with an obvious Settings
  toggle. Maximum on-disk JSONL is 3 × 256 KiB; one local ZIP is replaced on
  export. Nothing uploads. Only matched catalog hero/augment names are allowed;
  raw OCR, player/account identity, screenshots and credentials are excluded.
- Correlate launch/session/frame sequence with queue, hidden settling, capture
  acquisition, backend compatibility/fallback causes, preprocessing, HUD,
  identity resolution, OCR, title geometry, GUI dispatch, confirmation gates,
  stale drops and actual visibility changes. Rechecking snapshots are explicitly
  distinct from hide/show events. Cold OCR initialization is marked.
- Retain fixed-size per-stage/reason/fallback counts and timing totals/maxima,
  overlay hidden duration, and explicit dropped/rotated/truncated counts even
  after detailed events rotate. Export reports its diagnostic profile and config.

## Verification

- Initial full discovery: 1650 tests, 14 platform/dependency skips, one expected
  stale genuine-image source-hash failure. The original fixtures were then
  genuinely reevaluated, rather than changing hashes by hand. Final full-suite
  rerun after real reevaluation passed: 1651 tests, 14 platform/dependency skips.
  Final frozen-source repeat, including the independent-review regression:
  **1652 tests passed, 14 platform/dependency skips, zero failures/errors**
  (136.925 seconds, Linux/offscreen).
- Final affected-code run: 252 tests passed under Linux with Qt offscreen and
  local OCR dependencies. This includes capture safety/routing, badge identity,
  partial candidates, independent confirmation, structured log privacy/rotation,
  and failure-path tests.
- Diagnostic fault injection: a real controlled OCR worker delay of 4.05 seconds
  produced a ZIP trace linking queue/acquisition/OCR/dispatch to the same frame's
  >4000 ms stale rejection. No TTL was raised.
- Hidden-backend fault injection: exported request reason `backend_unavailable`
  and actual `capture_pending` hide share frame and generation, followed by the
  measured hidden settling delay.
- Confirmation reconstruction: exported traces show independent frames one and
  two with automatic confirmation counters 1 → 2, rather than reused OCR being
  counted as new evidence.
- Logs test rotation and catalog redaction on write and export; a worst-case
  fixed-enum launch summary stays below 64 KiB.
- JavaScript syntax checks passed for app.js, choices.js, ocr-ui.js; 19 UI logic
  and 16 three-choice logic checks passed (DOM stubs, not browser screenshots).

## Genuine-image reevaluation and remaining limits

On 2026-10-17, original bytes were checked against the source manifests (six
hero images and four selection images), then the unchanged existing runners
were executed against this source and the local official OCR model package:

- scripts/validate_hero_screenshots.py: templates v16.20.1, original fixture
  manifest, existing public data snapshot, output hero-recognition-genuine.json.
- scripts/validate_champion_select_screenshots.py: same rosters, original
  selection fixture manifest, output champion-select-genuine.json.

All original image hashes and every non-timing case observation match the prior
reports. Current evaluated module hashes were checked after both runs. Hero
results remain 2/3 positives recognized, one conservative Milio abstention,
3/3 negatives abstained, zero wrong heroes. Selection remains 1/1 positive and
3/3 negatives (two distinct negative scenes), zero wrong heroes. The still-frame
selection-title pipeline result is unchanged. Reports carry the current source
version from the actual runner; no release gate was weakened and no third-party
image was copied into the repository.

An independent review checked bounded-log privacy/export, badge paint-only
safety and fuzzy pruning (61 tests passed). It identified stage-start zero
values biasing derived timing averages; these are now omitted from duration
fields and excluded defensively from aggregate denominators, with regression
coverage (30 diagnostic tests passed); the reviewer independently confirmed the
fix and found no remaining blocker within that review scope. Rechecking snapshots likewise cannot
create artificial hide/show transitions.

At the initial local-verification checkpoint no commit, push, release, installer
build, or deployment had been performed. The user subsequently authorized
GitHub Windows validation and publication only after its gates pass. The
candidate is now version 0.4.12 with diagnostic_profile=capture-stability-v1;
the original genuine-image runners were executed again for that version.
The published 0.4.11 EXE does not contain this patch. Release claims must bind
to the eventual successful Windows run and its exact asset digests.

The tests do not prove every source of flicker is fixed. Unsupported Windows
capture, title/geometry changes, timeout, focus/occlusion and uncertain hero
identity intentionally withdraw stale badges. Logs distinguish these routes;
they cannot themselves prove unknown driver/fullscreen/compositor behavior.
Actual live-game behavior remains unverified.

## Published Windows verification

- [Windows run 39037126275](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/39037126275) passed all mandatory gates on 2026-10-17.
- [v0.4.12 diagnostic prerelease](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.12) is published, not latest, from exact source `966f79ea7305d716d6ae854432cf20a08344e985`.
- Final prepublication local suite: 1654 tests passed, 14 platform/dependency skips.
- Windows source/frozen WGC, visible-overlay and session tests at three scales, native OCR/overlay, selection handoff, rebuilt-library parity and same-binary OTA success/rollback passed. These are controlled fixtures, not a real LoL match or a genuine two-version OTA upgrade.
- Downloaded EXE: 107,058,338 bytes; SHA256 `cf7564424e5981f0c56004547301acb78cd3f3c2896fe60a91b0c95d5f39aa3b`. Downloaded bytes match release API digest, update manifest, SHA256SUMS and Windows test evidence.
- The local diagnostic ZIP is exported from **设置 → 导出调试 ZIP**; logs default on and can be disabled.
