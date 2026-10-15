# Exact-wheel capture crossover diagnostic

This branch is a controlled timing investigation, not a release candidate. Its
manual workflow runs only on the public repository's
`experiment/capture-opencv-crossover` branch, with a false publication input,
read-only repository permission, and no executable-build or release step.
Production main and its strict performance screen remain unchanged.

## Why this experiment exists

Two complete comparisons observed a capture timing regression:

- Run 40: official median 114.529 ms, custom 156.292 ms.
- Run 41: official median 125.031 ms, custom 167.153 ms.

In both comparisons every custom sample exceeded every official sample. The
existing release screen rejects these results. Run 41's diagnostic inventories
bound the same one-shot WGC helper, Pillow, source, fixture and output; the loaded
OpenCV binary differed. Separate GUI-blocked phase observations put the increase
inside the helper-inclusive interval. The comparisons also separated the two
library probes by the custom build, so they do not establish library causation.

## Fixed protocol

1. Save the already-approved official `opencv-python-headless==5.0.0.93` wheel
   from official PyPI and bind its payload to the installed official package.
2. Build the unchanged strict capture helpers and the same source-pinned custom
   `5.0.0.93+vga1` wheel once with the approved Community toolchain.
3. Use offline, no-dependency reinstalls of those exact wheel bytes in the fixed
   order A1, B1, A2, B2. Every block uses a fresh interpreter and the existing full
   parity probe, including its original seven capture samples and six separately
   labelled supplemental phase calls. No fastest block or sample is selected.
4. Preserve all completed and failed evidence. Confirm process ownership cleanup
   before any replacement installation or probe. Attempt final B restoration only
   when earlier processes are confirmed closed, and verify the restored package
   in a fresh interpreter. Restoration failure keeps the diagnostic failed.
5. Print bounded evidence and upload only small JSON/text reports after the
   unchanged repository artifact-budget check. No wheel, EXE or screenshot is
   uploaded by this workflow.

The orchestrator must not import either native package across reinstalls. Wheel,
installed package, loaded native, dependency, source and helper identities are
checked. Existing full-probe OpenCV import inventory and thread/IPP/OpenCL settings
are retained for every block; separate identity-process timing is not presented
as the measured probe's runtime state. Original run 40/41 failures remain historical evidence; this experiment
cannot replace their samples or grant a release verdict. A reversal can establish
an association under the measured conditions, not the exact internal OS cause.

Any later dependency or production change still needs independent review and the
complete actual Windows executable, capture/privacy/lifecycle, source/license,
OTA, size and strict timing gates. Exclusive-fullscreen compatibility and the
actual final chosen augment are not evaluated by this experiment.
