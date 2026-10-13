# Windows package size

This is a package-only candidate. It retains the existing offline OCR models,
native QtWidgets overlay/capture, automatic hero and champion-selection paths,
public-data refresh, browser diagnostics and OTA updater. It does not publish or
replace v0.4.2. A new patch release must use its own version and pass the existing
preview release gates after the candidate has been measured on Windows.

## Verified baseline and current estimate

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

Subtracting those member lengths gives an **estimate of 118,091,838 bytes
(112.62 MiB), about 21.4% smaller**, before changes in the Python import graph
and archive overhead. This is **not a measured candidate Windows build** and is
not a promised final download size. Removing those entries also avoids about
72 MiB of extracted payload. The build has a conservative 125,000,000-byte
(119.21 MiB) size ceiling; exceeding it fails rather than silently regressing.

## Why the removals preserve application features

- OpenCV still-image processing remains unchanged. Native screen capture does
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

Build with the normal `scripts/build_windows.py` workflow on native Windows x64.
`packaging/windows-build-constraints.txt` fixes the baseline's transitive runtime
and build dependency versions to avoid accidental upgrades during comparison.

The manual `test-windows-package-size.yml` workflow uses the standard public
`windows-2022` runner with read-only repository permission. It runs the Python/JS
suite, source geometry matrix, actual EXE browser/OCR checks, native capture and
overlay at 100/150/200% app scale, automatic hero/champion selection, and native
OTA success/concurrency/rollback against the **newly built candidate bytes**.
OTA remains a same-binary local fixture test, not a two-version live upgrade.
The existing source/license release verifier runs without publication.

Only bounded small evidence is uploaded, with the existing storage-budget gate
and one-day retention. No large EXE/source Actions artifact or release is created.

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
