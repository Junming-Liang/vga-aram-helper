# Compact local capture diagnostics

This diagnostic build enables the visible local-log toggle by default, as requested.
It can be turned off any time. `LocalDebugLog` itself remains disabled until enabled,
local-only, and disabled after a write
failure. It does not upload anything or collect screenshots, player/account
identity, raw OCR text, paths, titles, credentials, or exception text. Logs rotate
through exactly three owned JSONL files, at most 256 KiB each by default. Export
atomically replaces a single `VGA-debug.zip`; repeated exports do not accumulate
archives. Unknown fields and values are dropped on write **and** export.

## Integration

```python
log = LocalDebugLog(log_dir, version=__version__)
log.register_catalog(augment_names=trusted_augment_names,
                     hero_names=trusted_hero_names)
log.set_enabled(True)  # This user-requested diagnostic build enables it in the UI.
game_scope = log.begin_game()
log.record('overlay', visible=False, reason='capture_proof', generation=3, serial=8)
log.record('inference', inference_stage='ocr', phase='completed',
           inference_ms=36.5, generation=3, serial=8)
log.record('recognition', phase='accepted', slot=0,
           augment_name='Scoped Weapons', hero_name='Ahri', hero_source='hud',
           confidence=.96, threshold=.8, catalog_match=True, tier_present=True,
           generation=3, serial=8)
log.sample('state', state='idle', visible=True, generation=3)
log.flush()
archive = log.export_zip(export_dir, config=config,
                         recent_seconds=120, game_generation=game_scope)
```

Use `record()` for every visibility change, job lifecycle, inference stage,
acceptance/rejection, and invalidation. These remain immediate. Use `sample()`
for repetitive polls/status observations: only adjacent observations with the
same event and identical allowed semantic fields coalesce. Changing visibility,
reason, backend, generation, hero/augment, slot, confidence or any other semantic
field emits a new observation. Any `record()` first flushes pending samples,
therefore hide → capture → recognition → show order is retained.

The first observation is written immediately. `sample_summary.sample_count`
counts **additional repeats only**, with `sampled_event`, first/last monotonic
elapsed milliseconds, first/last serial and per-duration `_min`, `_max`, `_mean`.
A pending summary contains only fixed-size statistics, not a growing event list.
It flushes on the first repeat at least one second after its first repeat, on a
transition, `flush()`, disable, game boundary, or export. There is no background
thread. At abnormal process termination, the final pending repeats may be lost;
the immediate first observation remains. Serial ranges describe endpoints, not a
claim that every intermediate job ran.

Each written event has generated `session`, `sequence`, `elapsed_ms`, and
`game_generation`. Callers cannot overwrite these. Use `inference_ms`, not
`elapsed_ms`, for a measured stage duration. `generation` and `serial` correlate
worker callbacks with capture jobs; the random launch session separates restarts.
`begin_game()` uses only a local counter and never receives a server match ID.
Window/process identities remain launch-salted aliases through `identity()`.

`register_catalog()` accepts only a trusted bundled/imported application
vocabulary. Never construct it from OCR, user text, account names, or arbitrary
worker results. Only exact registered `augment_name` and `hero_name` values are
serialized. Export rechecks against the currently registered catalog; absent or
removed catalog entries disappear. No full catalog is exported. Numeric slot is
restricted to 0–2; confidence and threshold to 0–1.

## Reading a report

`manifest.json` schema 2 includes app version, allowlisted configuration,
selection filters, launch session and counters:

- `dropped_events`: invalid event names, oversized records or failed writes
- `dropped_fields`: rejected input fields/values
- `truncated_events`: complete lines removed from the oldest rotated file
- `rotations`: rotations performed this launch
- `aggregated_samples`: repeated observations represented by summaries

Counters are launch-wide; they are not a count of events in a filtered ZIP.
Sequence gaps and truncation counters make a partial trace explicit. Rotation
retains the most recent bounded window, so even a whole-game export may begin
partway through a game. It cannot recover overwritten data.

With no filters, export includes retained sessions. A recent/game filter selects
only the current launch and optionally the current requested game scope. Recent
filtering uses each record's monotonic emission time; a summary selected near the
cutoff may span slightly earlier observations, explicitly identified by its
first/last timestamps. Configuration is captured at export time, not inferred as
historical configuration. Existing schema-1 JSONL remains readable.

## Validation

Run `python -m unittest discover -s tests -p 'test_local_debug*.py' -v`.
Tests cover bounded rotation and atomic exports, redaction including malicious
values, catalog revalidation, current-session/game/window selection, monotonic
context integrity, timing aggregation, preserved flicker/recognition event order,
disable flushing, concurrency, symlink rejection, corrupt files and I/O failure.

## Long-session summary independent of rotation

The manifest's `summary` is an in-memory, launch-wide aggregate retained when the
JSONL ring rotates. It is not reconstructed from the surviving tail. Fixed enum
budgets bound its keys: event, reason, inference stage, capture/session/one-shot
status, fallback reason, and numeric timing names.
No names, identities, serials, catalog entries, or free text become summary keys.

Each valid original `record()`/`sample()` contributes once, including every
coalesced repeated sample. Synthetic `sample_summary` records do not contribute.
These are accepted observations, even if their eventual disk write fails; loss
counters separately identify dropped writes. For each bucket `observations`
counts inputs, while `latency.count`, `latency.total_ms`, and `latency.max_ms`
count only inputs carrying the selected duration. Duration selection is:

- capture: capture_ms, otherwise inference_ms
- inference: inference_ms
- recognition: inference_ms, otherwise ocr_ms
- job: queue_ms, otherwise dispatch_ms
- other events: settle_ms if supplied

The separate `timings` buckets retain count/total/max for every supplied latency
metric (excluding age_ms and ttl_ms). The same observation appears in several
summary dimensions; do not add dimensions or stage totals to estimate wall time.

Overlay summary counts observed changes in visible state, including the first
known state. Repeated identical visibility does not add a transition. Hidden time
runs from an observed hidden state to show, logging disable/write failure, or the
export snapshot for an open interval. It excludes time before the first observed
hide and time while logging is off. `hidden_total_ms`, `hidden_max_ms`, and
`open_hidden_ms` expose cumulative, longest, and still-open durations.

Summary and counters remain launch-wide even for a recent-window/game-filtered
trace. They survive rotation, not app restart; the exported manifest preserves
them. Counts and totals saturate at 2^53 to keep numeric storage bounded. This
provides long-game evidence while retaining only the recent detailed trace.
