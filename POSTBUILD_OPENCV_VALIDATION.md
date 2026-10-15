# Post-build OpenCV adoption comparison

## Why the order changed

The first integrated v0.4.7 candidates did **not** pass publication. The unchanged
release timing rule rejects any operation that is both more than 15% and more
than 5 ms slower. Their original seven-sample capture measurements remain failed
historical evidence:

- [Run 40](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38672981092):
  official median 114.529 ms, custom median 156.292 ms; +41.763 ms, 1.364648×.
- [Run 41](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38684255290):
  official median 125.031 ms, custom median 167.153 ms; +42.122 ms, 1.336889×.

Every custom capture sample in each of these runs exceeded every corresponding
run's official sample. These results are not discarded as an outlier or waived.
The old workflow measured the official wheel before a roughly five-minute native
build, then the custom wheel after that build. Library identity and build/time
order were therefore confounded. Phase diagnostics located the GUI-blocking
capture difference within the helper-inclusive interval; they did not establish
its cause.

[Controlled run 44](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38691738822)
completed a fixed, offline, fresh-interpreter official/custom/official/custom
sequence after the same build. All four original seven-sample reports, exact
wheel and installed payload identities, helper/source/output identities, owned
process cleanup and final custom-wheel restoration were retained and verified.
Capture medians were 152.102, 151.161, 160.448 and 147.097 ms respectively. Neither
forward pair reproduced a custom-wheel slowdown. This does not identify the
cause of the earlier shift or establish a universal performance advantage.

## Current release protocol

The release workflow now uses one fixed post-build official-to-custom pair:

1. Save the already-approved official wheel and verify its exact installed
   payload and dependency identities in a fresh process before rebuilding.
2. Build the pinned custom wheel once, using the unchanged recipe and compiler.
3. Verify the initially installed custom payload against that build proof.
4. Install the saved official wheel offline, verify its complete payload, then
   run the original full probe in a fresh interpreter.
5. Install the exact custom wheel offline, verify its complete payload, then run
   the same original full probe in another fresh interpreter.
6. In `finally`, restore that exact custom wheel, independently verify its full
   installed payload and dependencies, and run `pip check`. No reinstall or new
   measurement may begin while an earlier owned child/Job has unresolved cleanup.
7. Export the two original raw reports byte-for-byte to the standard baseline
   and candidate evidence names. Bind their raw hashes and process IDs, exact
   wheels/build/source, complete child cleanup and verified restoration in a
   mandatory sequence receipt before all subsequent product and packaging gates.
   The verifier selects only fixed evidence filenames in its explicit reports
   directory. Recorded absolute producer paths are validated as provenance, never
   opened; relocated files must retain the exact recorded bytes, size and hash.

There are no adaptive repeats, fastest-pair selection, changed sample counts,
changed pixel/OCR expectations, or substitution of supplemental phase timings.
The original two warmups, seven samples and three capture calls per capture
sample remain. The final publication rule remains **both >1.15× and >5 ms**.
A failing new pair stops publication. The final verifier also binds the measured
custom native library to the library actually embedded in the tested EXE.

The complete same-build Windows source/frozen/product/OTA/size/license gates are
still required. This change alone is not a release or a claim that actual
exclusive fullscreen, live-game compatibility, or automatic final-choice
identification has been validated.

## Historical passing full diagnostic #46

[Run #46](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38699532128)
passed the fixed post-build pair and every subsequent source/frozen/product,
OTA, size and source/license gate with publication disabled. It used source
`506c934673d718efe8c24e6f0ef871c332a58988` and tree
`757c44184e41811434da660fce55352013d9e796`. The run #46 diagnostic EXE was
106,858,085 bytes, SHA-256
`c77d04f12e80e5db2d89876efa956977142ba62492dad7336c4572cbefa6269e`.

Its official → custom seven-sample medians were:

| Synthetic workload | Official ms | Custom ms | Change |
| --- | ---: | ---: | ---: |
| Owned-window capture | 146.943 | 146.644 | −0.299 ms (−0.203%) |
| Hero matching, 1080p | 39.331 | 38.727 | −0.603 ms (−1.533%) |
| OCR application demo | 247.762 | 275.552 | **+27.789 ms (+11.216%)** |

All workloads passed the unchanged rule; OCR was slower, but not both more than
15% and more than 5 ms slower. The complete original reports, fixed order,
child cleanup, exact installed identities, byte-for-byte exports and restored
custom library were verified. The custom native library bound to the tested
EXE was 55,959,552 bytes, SHA-256
`33d6d89c08b48b019f4d2aa2eafc165ca76245488b22c649f887232c58587c3c`.

These are run #46 results only. They neither erase runs #40/#41 nor establish
the cause of their shift. Synthetic capture is not real-game latency, product
visible/hidden time or a universal speed advantage. The subsequent [release run #48](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38707221941) rebuilt and repeated every required gate,
including the same fixed post-build pair and unchanged strict rule. It published
source/tag `1046af25d66e12c784554c38351e75ed82afa81b` as [v0.4.7](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.7). The public EXE is 106,858,822 bytes,
SHA-256 `96bc81fcb12dc48c45e210706b358eb5eeccc062574166b440bf1452f4000547`; all 15 public assets match the publishing verifier. The table
above remains run #46's historical measurement, not run #48's timing values.


## Current v0.4.8 release

[Release run #55](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38793233284) passed the same fixed post-build pair, unchanged timing rule and all subsequent gates, publishing [v0.4.8](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.8) from source/tag `00bbf5affc02c32cbd9bf367199047eefdf208f8`, tree `cae3f15c3916f146c26d2d2d966efffe7169f886`. Its EXE is **106,925,126 bytes**, SHA-256 `d682d42478f1489395bd35ed933c1b6eda7fed00ef9d1315f564d5e4cd89958b`; the final verifier binds 60 evidence files and 15 release assets. The run #46 table and run #48 identity above remain historical; no run #55 per-workload timing or live-game speed claim is inferred from them.
