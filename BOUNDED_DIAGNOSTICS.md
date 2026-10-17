# Bounded local capture diagnostics

This diagnostic build enables its visible local-log toggle by default. Users can
turn it off at any time. `LocalDebugLog` itself starts disabled and stops after an
I/O failure. Everything stays local: no network, screenshots, player/account IDs,
raw OCR, window titles, paths, credentials, or raw exception messages. Unknown
fields and values are removed on both write and export. Only exact names from an
explicitly registered, trusted application catalog are permitted.

## Three independent retention lanes, one 768 KiB budget

Schema 3 reserves the existing total JSONL budget instead of increasing it:

- Routine detail: three rotating `events*.jsonl` files, 128 KiB each (384 KiB total)
- Critical history: `critical.jsonl`, 256 KiB
- Incident context: `context.jsonl`, 128 KiB

Custom `max_bytes` limits scale these allocations proportionally. All five owned
files together stay at or below `3 * max_bytes` (768 KiB by default). The ZIP has
four members: `manifest.json`, `events.jsonl`, `critical.jsonl`, and `context.jsonl`.
Its event payload remains within 768 KiB, with a separate 64 KiB manifest/ZIP
allowance. Export atomically replaces one fixed local `VGA-debug.zip`; repeated
exports do not accumulate archives. No neighboring files are read or attached.
Symlink directories and owned log files are rejected.

This separation matters: frequent capture/inference lifecycle traffic cannot
rotate away the early selection gate or historical setting that explains a
later problem. The routine tail is deliberately incomplete; critical history,
incident examples, and the launch-wide summary have independent budgets.

## Integration

```python
log = LocalDebugLog(log_dir, version=__version__)
log.register_catalog(augment_names=trusted_augment_names,
                     hero_names=trusted_hero_names)
log.set_enabled(True)
log.record_config(config)  # At enable and every relevant settings change.
game_scope = log.begin_game()  # Seeds the latest safe config in this game scope.
log.record('selection_gate', selection_gate='client_pixels_ready',
           selection_route='selection_pixels', target_role='client',
           lcu_selection=False, hero_auto=True, pixel_fallback=False,
           target_present=True, target_foreground=True, generation=3, serial=8)
log.record('capture', phase='requested', capture_mode='backend_unavailable',
           reason='backend_unavailable', generation=3, serial=9)
log.record('overlay', phase='hidden', visible=False,
           reason='capture_pending', generation=3, serial=9)
log.record('inference', inference_stage='ocr', phase='completed',
           inference_ms=36.5, generation=3, serial=9)
log.record('recognition', phase='accepted', slot=0,
           augment_name='Scoped Weapons', hero_name='Ahri', hero_source='hud',
           confidence=.96, threshold=.8, catalog_match=True, tier_present=True,
           generation=3, serial=9)
log.sample('capture', capture_mode='eligible', generation=3, serial=10)
archive = log.export_zip(export_dir, config=config, game_generation=game_scope)
```

Use `record()` for lifecycle observations and decisions. It counts every original
observation, regardless of whether the disk tail later samples it. Routine
capture queued/started/acquired/completed, job queued/started/completed, and
inference started/completed records use independent five-second sample streams.
`sample()` uses a one-second stream. Other records do not flush or reset these
streams. Event, phase, job kind, inference stage, and slot identify a stream;
semantic changes emit immediately. Up to 64 streams are kept in memory.

The first observation is immediate. A `sample_summary` counts **additional
repeats only**, with `sampled_event`, `sample_count`, first/last elapsed times and
serials. Duration `_min`, `_max`, `_mean`, and `_count` fields describe only the
repeats actually carrying that metric. Interleaved lifecycle callbacks therefore
no longer defeat sampling. Summaries may be emitted after unrelated events;
their explicit time ranges, rather than physical line adjacency, describe them.
Flush occurs at the first repeat beyond the interval, explicit `flush()`, game
boundary, disable, close, or export. There is no background thread.

Every accepted original and emitted sample summary receives generated `session`,
`sequence`, `elapsed_ms`, and `game_generation`. Caller values cannot override
these. Sequence gaps in the routine lane include sampled observations, not just
rotation. Join exact originals by `(session, sequence)` and correlate frames by
`(session, game_generation, generation, serial)`. Use `inference_ms`, not
`elapsed_ms`, for a measured duration. Game scopes are local counters, never
server match IDs. Native window/process identities are per-launch salted aliases.

## Critical history

Critical history includes configuration, game/phase/state changes, selection
gates, recognition outcomes, capture routes, visibility/recheck reasons,
discovery counts, cancellation, invalidation, expiry, and errors/discards.
`title_recheck` means title pixels require semantic verification; it does not
claim the recognized title changed. `title_changed` is a separate reason.

Configuration and explicit session boundaries remain exact individual records.
Other critical records aggregate recurring equivalent states into initially
60-second buckets. If the independent budget fills, buckets widen (up to one
hour) and compatible entries combine. The following are always explicit:

- `occurrences`: number of original observations represented
- `first_elapsed_ms`, `last_elapsed_ms`: first/last occurrence boundaries
- `first_sequence`, `last_sequence`, and available first/last serials
- Per-timing `_min`, `_max`, `_mean`, `_count`

The base record is the first representative, not the last observation. Counts,
confidence, latency, and stable-frame counters do not create a different critical
state by themselves. Other events can occur between two recurrences. A combined
hide row followed by a show row does **not** prove they were adjacent, nor that
all intervening serials ran. The manifest explicitly labels this noncontiguous
aggregation. Use the exact context lane for individual causal chains.

A bounded file cannot retain unlimited distinct states. If widening cannot fit
all entries, a small beginning segment and recent evidence survive, and
`critical_truncated_observations` reports the number actually lost. Zero loss
means all critical observations are represented, not that every one has an
individual timestamp or complete frame. `critical_bucket_ms` states the achieved
time resolution. `record_config()` saves only approved booleans and four ROI
percentages; `begin_game()` seeds the latest setting snapshot so a game-filtered
export includes its starting configuration.

## Exact incident context

Every original observation enters a bounded pre-incident buffer **before** routine
sampling. A real overlay show/hide, error/discard, expiry, invalidation, or cancel
retains relevant pre-incident originals and subsequent observations. Up to 64 KiB
of pre-context is available; the same frame is included even if it started more
than two seconds ago. Nearby observations cover two seconds before and five
seconds after the trigger. Up to eight active frame keys retain later callbacks
from slow frames beyond that five-second window.

Context is evicted by whole frame groups rather than individual stages. It keeps
an initial frame and recent frames, with at most 16 latest-cause pins, so routine
hide/show chatter cannot crowd out the latest distinct stale/error frame's
queue, acquire, inference, dispatch, and rejection evidence. Pins are bounded and
can be evicted if their own combined frames exceed the context budget. A single
oversized frame is also dropped explicitly. `context_truncated_events` and
`context_truncated_frames` count removals, not unique launch observations.

Context records are exact originals and can overlap the routine lane. Deduplicate
by `(session, sequence)` before reconstructing their order. Do not add context,
critical, and routine counts together. Neither context retention nor a summary
claims to retain every frame of an arbitrarily long session.

Critical/context snapshots are persisted at most once per second of incoming
activity, plus explicit flush/disable/close/export. No periodic timer is needed.
An abnormal termination may lose pending samples and the last unflushed history
updates. Export ignores incomplete JSON records; it reports invalid rows or
oversized files in `coverage.export_validation`. This is not a crash-proof
forensic recorder.

## Selection and discovery evidence

`selection_gate`, `selection_route`, and `target_role` are strict fixed enums
shared by tests with the `automatic_windows` producer. Gates distinguish closed,
stopped, inference busy, capture pending, missing target, foreground rejection,
client LCU, client pixels, game pixels, manual pixels, and unknown routing.
Booleans record LCU opt-in, auto-hero, pixel fallback, target presence and focus.
No LCU endpoint, lockfile, password, player slot, account ID, or client title is
logged. Discovery adds only bounded numeric counts of eligible/rejected windows;
metadata-eligible counts precede preferred-candidate signature verification.

## Reading a report and its coverage

The manifest retains app version, schema/profile, current launch, export filters,
export-time safe config, counters, coverage, and the launch-wide summary.
Historical settings come from critical `config` records, not export-time config.
Coverage gives per-lane retained/current-launch/prior-launch record counts,
represented observations, first/last elapsed boundaries, critical aggregation
resolution/loss, and export validation failures. These ranges do not assert
continuous detail between their endpoints.

Important counters:

- `dropped_events`: invalid original events, oversized detail rows, or failed writes
- `dropped_fields`: rejected event input fields/values
- `aggregated_samples`: originals represented by routine sample summaries
- `truncated_events`: lines removed from detail files
- `truncated_current_launch_records`, `truncated_prior_launch_records`: valid
  session-tagged removed rows, split by launch (corrupt rows may not classify)
- `rotations`: detail rotations this launch
- `critical_observations`, `critical_compactions`, `critical_truncated_observations`
- `context_triggers`, `context_truncated_events`, `context_truncated_frames`

Counters and summary are launch-wide even for a filtered export. Routine files
can retain prior launches; history snapshots are written for the current launch.
A recent/game filter includes only the current launch and requested scope. A
recent filter uses the last represented timestamp for aggregates; a selected
row can span earlier observations, explicitly shown by its first/last bounds.
Catalogs are revalidated on export; unregistered or removed names disappear from
all lanes. Oversized or corrupt files cannot cause unbounded export reads.

## Launch-wide summary independent of all rotation

The summary counts each valid original once, including sampled observations and
observations whose eventual disk write fails. Synthetic sample summaries do not
contribute. Keys are bounded by fixed event/reason/stage/capture-status/selection-
gate/route/role vocabularies and timing names; no free text, names, identities, or
serials become keys. This summary survives rotation, not application restart.

Each bucket has `observations` and optional `latency.count`, `latency.total_ms`,
`latency.max_ms`. Preferred duration: capture uses capture_ms then inference_ms;
inference uses inference_ms; recognition uses inference_ms then ocr_ms; job uses
queue_ms then dispatch_ms; other events use settle_ms when supplied. Stage-start
notifications do not count as measured zero-duration inference. Separate timing
buckets count every supplied metric except age_ms and ttl_ms. Do not add summary
dimensions or stage totals to estimate wall time. Numeric totals/counts saturate
at 2^53.

Overlay summary counts actual observed visible-state changes, including the first
known state. `phase=rechecking` snapshots are not visibility transitions. Hidden
time ends on show, disable, write failure, or the export snapshot for an open
interval. `hidden_total_ms`, `hidden_max_ms`, and `open_hidden_ms` exclude time
before the first hide and while diagnostics are disabled.

## Validation

Run:

```sh
python -m unittest discover -s tests -p 'test_local_debug*.py' -v
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -p 'test_debug_ui.py' -v
```

The synthetic 45-minute replay emits approximately 25 original observations per
second with real interleaving. From exported data alone it reconstructs an early
client-pixel gate with LCU off, the initial and later config, game-phase handoff,
repeated semantic rechecks, and a late 6.5-second OCR frame's queue/acquire/stages/
stale discard/hide/fresh show after its routine tail has rotated away. It asserts
zero critical loss, correct full-launch counts and latency, and the combined
768 KiB bound. A separate churn test proves hundreds of later routine hide/show
cycles do not evict a distinct error's exact frame. Other tests cover bounded
critical overflow with explicit loss, sparse timing denominators, enum drift,
privacy in all lanes, catalog removal, filtering, malformed/oversized input,
symlinks, I/O failures, concurrency, and actual offscreen Qt controls.
