# 2026-10-23 recognition and Mayhem 4.0 candidate

This records the local candidate investigation before Windows validation, not a release approval.

## Baseline and scope

- Fetched and inspected remote `main` at `6c0073dcf8dd112478b76b50941db6c1bc27422b` before editing. It already contains the v0.4.18 recognition changes; the older recovery checkout and its local changes were preserved separately.
- No game-memory access, injection, hooks, anti-cheat changes, credential access, or third-party inference service was introduced.
- The 4-second display TTL, 1.8-second local hero API limit, 0.8-second prefetch maximum age, two-independent-frame confirmation, and exact session/process/compositor/native-region checks remain intact.

## Confirmed code paths and changes

1. **Full-frame PNG serialization:** all three Windows capture backends previously used Pillow's default PNG compression. Lossless level 1 reduces this in-memory transport cost. Inputs that exceed the existing 16 MiB consumer limit at level 1 fall back to the original level 6, so the optimization does not reject a previously supported image merely because its PNG is larger. Decoded pixels are unchanged.
2. **Repeated exhaustive HUD search:** an unchanged normalized RGB HUD region used to repeat every template and scale search. A one-entry exact-input cache now stores only the exhaustive top-two search results, bound to immutable model identity, thresholds, full RGB ROI and layout/dimensions. Fresh preparation, letterbox, color, saturation, name and confidence checks still run. It does not cache hero observations or timestamps, manufacture frames or extend a TTL. Any input change runs the original exhaustive search.
3. **Age-only prefetch expiration:** an otherwise healthy packet can exceed 0.8 seconds during model preparation or compositor validation. Previously that ordinary age condition raised a capture error and invalidated the healthy session. It now discards those pixels and takes a new fully guarded capture. Session, process, compositor, invalid timestamp and fresh-capture failures still abort.
4. **TTL recovery placement:** expiry must hide stale grades and revoke anchors. Previously it also forgot the installed native layout, so an independently accepted fresh result with the identical physical layout unnecessarily retired the capture session. Expiry now preserves only a non-authoritative physical-layout hint. Fresh accepted data, same HWND/revision/DPI/slots/bounds/regions, actual native-region and target checks are required before reusing it. Repeated soft expiry is idempotent; hard invalidations and layout changes discard it.

The prefetch and placement defects were reproduced against the untouched baseline production code: two age-expiry tests raised capture errors, and identical-layout recovery retired one healthy capture. The candidate passes these tests, including real OCR with an owned Qt fixture. This is evidence of deterministic code-path defects, **not** reproduction of a user's live-game flicker or proof that the historical native helper `0xC0000409` termination is fixed.

## Reproducible stage microbenchmark

Run from the project root with the existing dependencies:

```sh
python scripts/benchmark_recognition_hotpaths.py --baseline 6c0073dcf8dd112478b76b50941db6c1bc27422b --runs 7 --output /tmp/recognition-hotpaths.json
```

An optional `--image` accepts a caller-authorized local still; no images are written into the report. The paired Linux run in `recognition-hotpaths-linux.json` used 173 owned procedural HUD templates and a 3440×1440 public still:

- Identical-input exhaustive HUD search: median 672.33 ms before, 0.69 ms with exact score reuse and fresh final gates. Complete returned observations were equal.
- Full-frame PNG encode: median 860.89 ms at level 6, 346.98 ms at bounded level 1. Decoded pixels were equal; output grew from 5,202,545 to 5,615,682 bytes.

These are isolated warm-path measurements, not total first-recognition or Windows/game FPS figures. Cold-start model loading, genuinely changed HUD input, animated title OCR, the conservative two-frame gate, Windows capture and unavailable local APIs can still dominate latency.

## 4.0 data applicability

The data change adds the reviewed **partial official CN 26.21 announcement delta**, not a fully reconstructed 4.0 pool: 35 additions, 13 removals, source-scoped identities and provenance. Intermediate 16.18–16.20 changes to carried-forward records have not all been revalidated. The new `罪恶快感` must not inherit old Huya ID 1322, its description, grade or combinations.

The Huya bundle 395 checked on October 23 and revalidated on October 25 still reports 16.17 / 2026-09-07 statistical rows. A successful download is not evidence of current 26.21 applicability. Old hero grades, hero–augment grades and recommendations are withheld; no new T tiers or performance metrics are fabricated. See `DATA.md` and `SOURCE_NOTES.md` for exact provenance and limitations.

## Validation status

- Full Python suite: **2,312 tests, 2,297 passed, 15 skipped, zero failures**, 317.948 seconds. Skips: 12 requiring actual Windows filesystem semantics and 3 requiring the exact isolated CMake/scikit-build toolchain. Linux Python 3.12.14 with the installed Qt/OCR runtime.
- Release verifier: 180 unit tests passed. The new module is included in PyInstaller hidden imports and matching producer/verifier source-hash inventories. This is not an EXE build or release approval.
- JavaScript: syntax checks and **38 logic checks passed** (22 application + 16 choices), using Node 24.19.0. Includes stale statistics disclosure, partial catalog warning, escaped provenance, and announcement-only detail records without legacy role/limit fields. The standard Windows CI Node version still needs its own run.
- Local OCR smoke and launcher self-test passed with original synthetic images. These are not live-game recognition evidence.
- Both public-still reports were regenerated by their original validators, not by editing hashes. Hero sample: 2 of 3 positives recognized, 1 safely abstained; 3 of 3 negatives abstained; zero wrong-hero predictions. Selection sample: 1 positive recognized and 3 negatives abstained. The selected stills do not establish temporal accuracy, current stock-client/4.0 coverage, or Windows capture.
- Independent read-only capture review: 166 focused tests passed; expiry/effective-placement tests also passed in separate Qt 125%, 150%, and 200% processes (39 configuration cases). These use owned synthetic boundaries, not real Windows monitor settings.
- Independent data review: 135 focused tests passed. An additional frontend record-shape issue found in review was corrected and regression-tested; the reviewer independently opened all 35 announcement entries from the actual non-demo public projection in a JavaScript DOM fixture.
- The developer-only historical `official_snapshot_validation.py` was adapted to preserve internal 395 audit checks while requiring current abstention and statistics-free public output. Compilation and CLI parsing passed; its full real-395 run was **not performed**, because the complete separately acquired input set was not available here. This standalone script is not included in unittest discovery.
- An optional real Chromium rendering attempt could not start in the cloud sandbox (missing Playwright bundled browser; installed system Chromium rejected by a local socket restriction). No browser-rendering pass is claimed; no system restriction was changed.

Native Windows EXE packaging, persistent WGC lifecycle/visible-overlay tests, and current in-game 4.0 screenshots remain required before release. At the October 23 local freeze, no remote CI, main submission or release had been performed. The October 25 approval and submission status are recorded below.

## October 25 pre-submission check

The approved candidate patch and all 45 original file hashes were verified unchanged; remote `main` was still the exact baseline. An independent preflight found that the Windows source/frozen selection fixtures' full expected reference dictionaries lacked the seven new applicability fields. Their explicit expectations were synchronized and a production-reference portable regression added; full dictionary equality and forged-field rejection are retained. This is test-contract integration, not a relaxed acceptance gate.

Public source checks now distinguish Huya's unchanged 16.17 bundle from aramgg's newly advertised 16.21.2 configuration. The latter's protected business API was not accessed or integrated. See `SOURCE_NOTES.md`; no alternative source grades are invented or silently mapped. Main submission and non-publishing Windows validation are approved for this round; release publication remains unapproved.

Final October 25 portable rerun after the selection-contract correction: **2,314 tests, 2,299 passed, 15 skipped, zero failures**, 298.096 seconds. Focused selection/data/release checks: 253 tests, 251 passed, 2 Windows-only skips. JavaScript syntax and all 38 logic checks passed again. This does not substitute for the separately approved Windows run.
