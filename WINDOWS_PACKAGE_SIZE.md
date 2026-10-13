# Windows package size

v0.4.5 retains the reviewed minimal OpenCV source-build recipe adopted in v0.4.4.
Published tags/assets remain immutable. Earlier release and experimental measurements are preserved separately below.

## Measured final v0.4.5 release

[Windows release run #14](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38447380079) passed all acceptance gates and published [v0.4.5](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.5) with the same `minimal-opencv-v1` profile and original offline models.

- Source/tag: `1939043c64554868bba3931a214d89946a339b53`
- Final EXE: **106,399,997 bytes (101.47 MiB)**
- Change from v0.4.4: **+56,747 bytes**
- Final SHA256: `c43d1cd0a7848cad6c7b24ffd13943c653b823c19ed3d1992669943457ad2195`

This release adds automatic-window/capture reliability and portrait-cache handling. The v0.4.4 paired timings below are historical measurements, not new v0.4.5 timing results. Same-run parity, warmed timing, source/license and frozen-EXE gates were rerun for this release.

## Measured final v0.4.4 release

[Final Windows release run #10](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38417923065) succeeded in 16 minutes 9 seconds and
rebuilt the versioned release through every acceptance gate:

- Source/tag: `96245a849e16e19fec4967c9107ac393e86e5ce8`
- Final EXE: **106,343,250 bytes (101.42 MiB)**
- Saving against v0.4.3: **10,215,963 bytes (9.74 MiB), 8.765%**
- Cumulative saving against v0.4.2: **43,948,292 bytes (41.91 MiB), 29.242%**
- Final SHA256: `e9ca12f1b2d290a7dd68fed61723772ee26f8f8ff281c76637a63e70fd88a35d`
- All 112 image outputs, 10 full OCR outputs and eight hero results matched;
  all three original offline model hashes remained unchanged

Final-run paired medians, with seven same-runner samples after two warmups
(official wheel → custom wheel):

| Workload | Baseline ms | Custom ms | Change |
| --- | ---: | ---: | ---: |
| OCR application demo | 343.9889 | 373.1095 | **+8.47%, +29.12 ms** |
| Hero matching, 1080p | 40.1646 | 41.0286 | +2.15% |
| Owned synthetic-window capture | 12.4758 | 12.1400 | −2.69% |

OCR was measurably slower on this runner, within the approved publication gate
below. This is not a no-slowdown claim or a universal/real-game performance
guarantee. Earlier experimental timings are history, not final-release timings.

## Adopted release gates and scope

The publishing workflow explicitly selects
`VGA_RELEASE_PACKAGE_PROFILE=minimal-opencv-v1`, rebuilds the hash-pinned
OpenCV source with the reviewed Community compiler recipe, and records the
truthful custom distribution version `5.0.0.93+vga1` (native `5.0.0`). It must
repeat the official-versus-custom paired Windows comparisons before freezing.
Read-only experiment artifacts remain ineligible for publication, even when an
environment flag is later cleared.

The adopted release has a **110,000,000-byte** regression ceiling against the
immutable v0.4.3 baseline. The separate read-only experiment retains its
115,000,000-byte ceiling. The final release passed these required gates on
its freshly built, exact-version bytes:

- Exact image-operation/full-OCR/hero output comparisons and warmed timing checks;
  adopted publication stops if a workload median, recomputed from seven raw
  samples, is both more than 15% and more than 5 ms slower. The isolated
  experiment retains its coarser 50% + 5 ms screen. A hit pauses automatic
  publication for diagnosis, not blind reruns until a passing sample appears
- Unchanged SHA-256 identities of all three original offline OCR models
- Frozen PNG/JPEG/WebP/BMP OCR and ICC-bearing PNG/JPEG/WebP decoding/OCR
- Native capture/overlay at 100/150/200% application scale, automatic champion,
  owned champion-selection handoff, browser diagnostics and source DPI matrix
- Exact-binary local OTA success/concurrency/rollback, with process cleanup
- Qt/Microsoft Community CRT and custom OpenCV provenance, complete notices,
  corresponding Qt/application source, and final asset identity checks. The
  downloadable supplemental-license ZIP and exact recipe/source/native-binary
  bindings to paired parity evidence are verified before publication

The new build removes only unused OpenCV modules and unused Pillow font/CMS
native extensions. Qt renders application text and keeps its font support.
Offline recognition, native QtWidgets capture/overlay, automatic champion and
selection, public-data refresh, browser diagnostics and OTA are retained. No
model quantization, recognition-resolution/threshold change, UPX, custom
bootloader or first-run model download is introduced. Maintaining pinned source,
downstream packaging patches, compiler settings and complete license evidence
is an explicit additional maintenance cost. Byte-identical rebuilds across
changing hosted runner/compiler images are not promised.

v0.4.4 remains a prerelease excluded from stable OTA; the README links its
manual download and same-version checksum. See the
[recipe and full evidence scope](WINDOWS_MINIMAL_OPENCV_EXPERIMENT.md).

## Successful second-round experiment, not the v0.4.4 release

[Read-only Windows run 38410925432](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38410925432)
succeeded in 14 minutes 5 seconds at source
`db5db2b92c61df179491a432316cdd022466a6e8`:

- Experimental EXE, still application v0.4.3: **106,342,697 bytes (101.42 MiB)**
- Saving against released v0.4.3: **10,216,516 bytes (9.74 MiB), 8.765%**
- Experimental SHA256: `6c718e88b4acd7dc59231ebb7a3867d415290378ee44300e3a70231e78443f2d`
- Exact parity: **112 image outputs, 10 full OCR outputs, eight hero results**
- All four format, three ICC-format, native scale/capture/selection, exact-binary
  OTA, source/Qt/Community CRT/license and unchanged-model gates passed

For the earlier experiment only, seven measured samples after two warmups on
the same Windows runner produced these medians (official → custom):

| Workload | Baseline ms | Custom ms | Change |
| --- | ---: | ---: | ---: |
| OCR application demo | 207.8164 | 211.7380 | +1.89%, +3.92 ms |
| Hero matching, 1080p | 33.4690 | 32.1846 | −3.84% |
| Owned synthetic-window capture | 9.9120 | 9.3513 | −5.66% |

These earlier experimental measurements are not a universal performance
guarantee, general screenshot accuracy measurement, real
LoL/Vanguard validation or a clean Windows 10/11 machine test. The genuine
screenshot reports were separately rerun with v0.4.4 source on Linux using the
**official** wheel and retain their abstentions; they do not evaluate the custom
Windows wheel. Final v0.4.4 metrics are recorded above from its separate build.

## Measured v0.4.3 release

[Final Windows run 38383752875](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38383752875)
passed and published the immutable [v0.4.3 preview](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.3):

- Source/tag: `67361ca90124a8e5dee69d1fa0c560711fe9dac6`
- Final EXE: **116,559,213 bytes (111.16 MiB)**
- Reduction from v0.4.2: **33,732,329 bytes (32.17 MiB), 22.445%**
- Final SHA256: `2dbe5c1a76b8fd13e2758eb1b6ad952da0a89a391890963c71dfe55cb054dc0b`
- All exact-version package/model, supported-format OCR, native scale/capture,
  selection, same-binary OTA, source/license and remote-asset digest gates passed

The final manifest and same-release evidence describe these newly rebuilt bytes.
The prior candidate below is preserved only as measurement history. No existing
v0.4.2 tag or asset was replaced, and stable OTA still excludes this preview.

## Earlier measured Windows candidate

[Read-only Windows run 38381001343](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38381001343)
passed at source `8067fac4f219830694fbdcb52b5dd36de78d4779`:

- EXE: **116,560,469 bytes (111.16 MiB)**
- Reduction from v0.4.2: **33,731,073 bytes (32.17 MiB), 22.444%**
- Candidate SHA256: `6f47c9074d91ef8d9b25390e6a59185580e0a6fb48e45b950fad6ab013a029b1`
- Passed frozen PNG/JPEG/WebP/BMP OCR, browser, native capture/overlay at
  100/150/200% app scale, champion-selection handoff, same-binary native OTA
  success/concurrency/rollback, storage budget and source/license verification

This earlier candidate still had the old application version. The separate
v0.4.3 build above regenerated its version resources and repeated every gate;
its final size/hash differs. Do not substitute this candidate hash for v0.4.3.

## Verified baseline and initial estimate

The immutable [v0.4.2 release](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.2)
EXE is **150,291,542 bytes (143.33 MiB)**. Its SHA256 is
`66e7798b5deb056e182f7a33bbdecf13498eaa62b6bf8ca0c6db3ae01ff48886`.
Its release source is `151bb0a5d0a73946bad5e603c8f07373ed19248e`;
subsequent documentation-only main was `52eee9280a85c7c50d1faaa0ed978c3e52ca3abd`.

The following are actual stored member lengths read from that verified EXE's
PyInstaller CArchive, not installed-wheel directory sizes:

| Removed packaging payload | Stored bytes in v0.4.2 |
| --- | ---: |
| Unused OpenCV FFmpeg video DLL | 12,960,677 |
| Standalone ONNX Runtime C-API DLL | 6,776,613 |
| Unreferenced branding source/extra PNG sizes | 4,447,207 |
| Pillow AVIF decoder outside the supported formats | 4,315,208 |
| Orphaned optional Qt OpenSSL backend dependencies | 2,716,045 |
| Duplicate raw RapidOCR/ORT Python source files | 983,954 |
| Total known stored payload | 32,199,704 |

Before rebuilding, subtracting those member lengths gave an **estimate of 118,091,838 bytes
(112.62 MiB), about 21.4% smaller**, before changes in the Python import graph
and archive overhead. The measured candidate above supersedes that estimate;
the final v0.4.3 measurement is reported separately above. Removing those entries also avoids about
72 MiB of extracted payload. The v0.4.3 build used a conservative 125,000,000-byte
(119.21 MiB) size ceiling; v0.4.4 uses the stricter adopted-profile ceiling above.

## First-round removals retained from v0.4.3

- First-round packaging did not change OpenCV still-image processing. Native screen capture does
  not use video decoding, VideoCapture or VideoWriter.
- ONNX Runtime's Python extension includes the CPU inference implementation;
  the separate C API DLL is not imported by this Python application. The pinned
  [upstream link targets](https://github.com/microsoft/onnxruntime/blob/v1.31.0/cmake/onnxruntime_python.cmake#L199-L215)
  and actual Windows PE imports were inspected. The small provider support DLL
  is retained. Actual frozen OCR tests are still mandatory.
- RapidOCR's lazy Python entry point and CPU backend are explicit hidden imports.
  Normal import analysis replaces indiscriminate collection of conversion,
  training and optional-engine utilities. Its configuration, dictionaries and
  all three original models remain bundled. Both wheel and embedded model bytes
  must match the existing SHA256 identities. There is no quantization,
  resolution/threshold change, online OCR service or runtime model download.
- The program supports PNG, JPEG, WebP and BMP screenshots. AVIF was already
  rejected. The frozen HTTP OCR tests now exercise every supported format.
- The original multi-size Windows icon and the browser's 512-pixel branding image
  remain unchanged. Design originals and all other image sizes remain in the
  repository and corresponding source ZIP, but are not duplicated in the EXE.
- Qt still has its native Windows TLS/certificate backend. The previously omitted
  Qt OpenSSL plugin left an unused pair of suffixed SSL DLLs. Python's distinct
  required `libcrypto-3.dll`/`libssl-3.dll` are retained for HTTPS, data and OTA.
- A fail-closed check inspects imports and delay imports of every retained PE
  DLL/extension. If a retained binary starts depending on a proposed removal,
  the build stops. Dynamic loads are additionally covered by actual-EXE tests.
- No CRT duplicate layout is removed. The existing signed Microsoft runtime
  byte/provenance checks, Qt LGPL notices/corresponding source and all bundled
  third-party licenses are preserved. The same clean source commit is archived.
- PyInstaller's normal lossless zlib compression is unchanged; UPX is disabled.
  No opaque executable packer or antivirus-risk workaround is introduced.

## Reproduce and validate

For v0.4.4, use the publishing workflow’s explicit adopted profile and paired
comparison gates described above. `scripts/build_windows.py` freezes the newly
built custom wheel on native Windows x64; setting a profile alone does not
replace the required source-build provenance or paired evidence.
`packaging/windows-build-constraints.txt` fixes the baseline's transitive runtime
and build dependency versions to avoid accidental upgrades during comparison.

The first-round manual `test-windows-package-size.yml` workflow uses the standard public
`windows-2022` runner with read-only repository permission. It runs the Python/JS
suite, source geometry matrix, actual EXE browser/OCR checks, native capture and
overlay at 100/150/200% app scale, automatic hero/champion selection, and native
OTA success/concurrency/rollback against the **newly built candidate bytes**.
OTA remains a same-binary local fixture test, not a two-version live upgrade.
The existing source/license release verifier runs without publication. The
preview publishing workflow repeats the same gates on its newly versioned EXE,
remeasures the release archive and requires the exact candidate OTA/format
evidence before publishing; the new reports are included in the evidence ZIP.

The workflows upload only bounded small Actions evidence, with the existing
storage-budget gate and one-day retention. The read-only candidate workflow
creates no release. The preview workflow publishes verified release assets
directly, without duplicating large EXE/source files in Actions storage.

`reports/windows-package-size.json` records:

- Exact candidate EXE size/hash and source commit
- Baseline identity, saved bytes/percentage and the regression ceiling
- Stored/unpacked bytes by package and the largest 25 members
- All three verified embedded model identities
- Removed binary inventory and PE-dependency check status

`check_package_candidate.py` remeasures the executable and binds format/OTA
results to that exact hash and source commit. A size reduction alone is never a
functional pass. These tests do not establish real-game accuracy, Vanguard
compatibility, or Windows 10/11 clean-machine coverage.
