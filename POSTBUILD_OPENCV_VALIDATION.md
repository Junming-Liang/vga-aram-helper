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
