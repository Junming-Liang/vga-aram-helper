# Minimal OpenCV: Windows experiment and v0.4.4 adoption

The reviewed recipe is adopted under `VGA_RELEASE_PACKAGE_PROFILE=minimal-opencv-v1` and the [v0.4.4 preview](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.4) is published. The [final Windows release run #10](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38417923065) rebuilt the custom wheel/versioned EXE and passed every gate. Read-only experimental artifacts remain ineligible for publication even if their environment flag is cleared. Published v0.4.3 and earlier assets remain unchanged.

## Final v0.4.4 release

Run #10 succeeded in 16m09s at source/tag `96245a849e16e19fec4967c9107ac393e86e5ce8`. Its final EXE is **106,343,250 bytes (101.42 MiB)**, SHA256 `e9ca12f1b2d290a7dd68fed61723772ee26f8f8ff281c76637a63e70fd88a35d`: **10,215,963 bytes (8.765%)** smaller than v0.4.3 and **29.242%** smaller than v0.4.2.

Final same-runner medians (seven measurements after two warmups, official → custom) were OCR **343.9889 → 373.1095 ms (+8.47%, +29.12 ms)**, hero matching **40.1646 → 41.0286 ms (+2.15%)**, and owned synthetic-window capture **12.4758 → 12.1400 ms (−2.69%)**. OCR was measurably slower on this runner, within the approved **>15% AND >5 ms** publication gate. These samples do not establish universal or real-game performance. All 112 image outputs, 10 full OCR outputs and eight hero results matched; model hashes and the full frozen-EXE gates passed.

The next section preserves the earlier experiment, whose EXE was still v0.4.3. Its +1.89% OCR timing is historical and must not be substituted for the final release's +8.47% measurement.

## Successful Windows experiment

[Run 38410925432](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38410925432) succeeded in 14m05s at source `db5db2b92c61df179491a432316cdd022466a6e8`. Its EXE still reports **v0.4.3**: **106,342,697 bytes (101.42 MiB)**, SHA256 `6c718e88b4acd7dc59231ebb7a3867d415290378ee44300e3a70231e78443f2d`. That saves **10,216,516 bytes (8.765%)** against the released v0.4.3 baseline below. These are not final v0.4.4 bytes or its hash.

All **112 image outputs, 10 full OCR outputs and eight hero results** matched the official wheel exactly in the selected same-runner corpus, and all three OCR model identities remained unchanged. The resulting frozen EXE passed all four input formats, three ICC-bearing formats, native 100/150/200% application scaling/capture/selection, same-binary OTA success/concurrency/rollback, and source/Qt/Community CRT/license gates.

Seven measured samples after two warmups gave median times in milliseconds (official → custom): OCR **207.8164 → 211.7380** (+1.89%, +3.92 ms), hero matching **33.4690 → 32.1846**, and owned synthetic-window capture **9.9120 → 9.3513**. These are earlier experimental measurements only. The raw timings and coarse failure screen are described below; they do not supersede the final-release slowdown reported above or establish universal performance.

## Measured starting point

The released v0.4.3 EXE is **116,559,213 bytes** (SHA256 `2dbe5c1a76b8fd13e2758eb1b6ad952da0a89a391890963c71dfe55cb054dc0b`), built from `67361ca90124a8e5dee69d1fa0c560711fe9dac6` in [the successful Windows run](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38383752875). Its actual CArchive stores `cv2/cv2.pyd` in **30,519,497 bytes**, expanded **85,848,064 bytes**. This is the largest remaining member. The three OCR model files are unchanged and are not candidates for compression by quantization or lower-accuracy replacement.

A separate Linux prototype of the same OpenCV source reduced that platform's native library from 31,283,599 to 23,085,439 zlib-compressed bytes (8,198,160 bytes saved). Exact synthetic comparisons passed for 57 image operations, seven full OCR outputs, and eight hero results; a separate 56-output numerical corpus also matched. **These are Linux results, not Windows EXE savings or an accuracy guarantee.** A stricter follow-up diagnostic matched 112 image outputs, 10 full OCR results and eight hero results, but rejected that old Linux prototype because JPEG SIMD was disabled and its PNG library version differed. Timings varied across two corrected runs: OCR ranged from roughly −0.5% to +42.1%, and hero matching from +14.2% to +24.6%. This is not a performance-parity pass. The Windows recipe and gate required the original SIMD/codec settings and disclosed every measured timing difference before the adoption decision recorded above.

## Adopted recipe and maintenance cost

- Build the official `opencv-python-headless` **5.0.0.93** source distribution, SHA256 `b82f9831daab90b725c7c1ee1b36cb5732c367096ac76d119e64e14eb70d5f3c`, with only the used core/image-processing/image-codec/Python modules and their required OpenCV 5 dependencies.
- Use explicit local distribution version **5.0.0.93+vga1**. This is a downstream build, not the official PyPI binary. Native `cv2.__version__` remains the upstream C++ version 5.0.0.
- Preserve PNG/JPEG/WebP/BMP, SSE3 CPU baseline and runtime dispatch through AVX512, IPP, OpenCL, precise floating-point settings, accurate algorithm hint, and baseline static MSVC CRT linkage. Use the approved Community compiler, not an implicitly selected runner Enterprise installation.
- Hash-pin the original source, Windows IPP input and built-in font; retain bundled codec sources. The four downstream Python packaging/typing-generation changes do not edit C++ algorithms. The wheel frontend explicitly selects one approved Visual Studio generator and passes CMake arguments as a list, avoiding scikit-build’s conflicting toolset/default-instance discovery and space-splitting behavior. It also mirrors the official Windows wheel recipe’s empty generic `CMAKE_ASM_COMPILER` setting, preventing GNU assembler discovery from changing MSVC library naming; the separately pinned NASM assembler remains enabled for JPEG SIMD. Record original/patched file hashes, exact patch, compiler/configuration, wheel/native hashes and complete generated license notices, including current IPP and fonts.
- In both the tested experimental EXE and the adopted release profile, exclude Pillow's unused font-rendering and color-management native extensions. Application text is rendered by Qt. Ordinary screenshot decoding is preserved and tested with ICC metadata as well as the four input formats.
- Keep the stock PyInstaller bootloader and compression. No UPX, Zopfli, model changes, browser replacement or first-run model download is introduced.

v0.4.4 also carries the experiment’s hardening of the existing ONNX telemetry opt-out: ORT 1.31.0 documents that the API alone may run after minimal initialization. The launcher, model-inventory and OCR entry paths now set `ORT_DISABLE_TELEMETRY=1` before runtime import and retain the API opt-out. See [the exact upstream privacy documentation](https://github.com/microsoft/onnxruntime/blob/v1.31.0/docs/Privacy.md). This does not establish historical data transmission, claim a general network firewall or prove that every possible third-party network path is blocked.

The `/MT` build also embeds Microsoft release CRT object code; servicing that code requires rebuilding the affected binary and distributing a new application release. Its applicable Microsoft terms are separate from OpenCV/Qt licenses; see the [runtime scope clarification and official references](THIRD_PARTY_NOTICES.md#microsoft-windows-runtime-components).

This adds a maintained source-build recipe and downstream packaging patches. Repeated source/configuration inputs are documented; byte-for-byte rebuild identity across changing GitHub runner/compiler images is **not** claimed.

## Validation and evidence

The v0.4.4 publishing workflow explicitly selects the adopted profile, freshly rebuilds the pinned source/custom wheel, reruns official-versus-custom comparisons and every exact-version EXE gate, and applies a 110,000,000-byte ceiling against released v0.4.3. The adopted publication gate also recomputes medians from the seven raw samples and stops when a workload is **both more than 15% and more than 5 ms slower** than baseline. A hit pauses automatic publication for diagnosis, rather than blindly rerunning until a passing sample appears. This is stricter than the isolated experiment’s 50% + 5 ms coarse screen below; neither threshold is a universal performance guarantee. It must verify the new final size/hash and same-release source/license evidence before publishing a prerelease excluded from stable OTA.

To repeat the isolated non-publishing experiment, dispatch `.github/workflows/test-windows-minimal-opencv.yml` on the public repository's main branch. It is manual, read-only, uses the standard free `windows-2022` runner, and uploads only bounded one-day evidence after the existing storage-budget check. It cannot publish a release.

The workflow runs the official wheel and the custom wheel in separate fresh interpreters on the **same Windows runner**. Exact image-operation/OCR/hero comparisons and repeated warmed timing checks precede freezing. Seven measured samples after two warmups cover image operations, OCR, hero matching and a process-owned synthetic Win32 capture window. The coarse failure screen is both 1.5× and more than 5 ms slower; every raw sample and ratio remains visible below that threshold, and passing it does not authorize adoption of a meaningful slowdown. Build flags, native bytes and truthful metadata are checked. Basic performance evidence is limited to the tested workload and runner, not a guarantee for every computer or real gameplay.

Each newly built EXE must then pass every existing acceptance gate: source/unit/JavaScript checks, source DPI matrix, actual bundled OCR and four input formats, browser UI, Qt native capture/overlay at 100/150/200% application scale, automatic hero and owned selection handoff, exact-binary OTA success/concurrency/rollback, model SHA256, Qt/Microsoft/source/license verification. ICC-bearing PNG/JPEG/WebP screenshots are also decoded through the actual isolated EXE. The archived custom OpenCV binary and all supplemental notices must match their build hashes. The publisher also verifies the final downloadable supplemental-license ZIP and binds the exact source/build recipe and compiled native identity to both sides of the paired comparison; stale or unrelated parity evidence cannot authorize publication. The experiment has a 115,000,000-byte EXE cap, below the released v0.4.3 baseline.

Evidence uses `reports/windows-opencv-{build,baseline,candidate,parity}.json` plus the existing Windows reports. The verifier recomputes comparisons and rereads the actual CArchive rather than trusting a size claim. The limited genuine-screenshot reports were freshly rerun with v0.4.4 source on Linux using the official wheel; their old safety abstentions and limited sample scope remain. They are not Windows/custom-wheel evaluations. The experiment and final v0.4.4 release each have their separate measured identities above. No real game, Vanguard, clean end-user machine, exhaustive input-domain or universal performance claim follows from these fixtures.

## 中文摘要

最终 v0.4.4 已在[发布运行 #10](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38417923065)完成重新构建、通过全部门禁并发布预览版：EXE **106,343,250 字节**，比 v0.4.3 小 **8.765%**，比 v0.4.2 累计小 **29.242%**；最终哈希见上方。早期只读实验为 106,342,697 字节，内部仍为 v0.4.3，只保留为历史，不能混用。

v0.4.4 已采用审查后的自编译配方，并明确使用 `VGA_RELEASE_PACKAGE_PROFILE=minimal-opencv-v1`。自编译版本标为 `5.0.0.93+vga1`，保留全部离线模型、当前四种截图格式和 CPU 加速方式；未使用的 Pillow 字体/CMS 扩展被去除，Qt 字体不变。固定源码、补丁、Community 编译器与许可证据需要持续维护，不承诺不同 runner/compiler 镜像间逐字节复现。

最终同机 112 项图像输出、10 项完整 OCR 输出及 8 项英雄结果一致，模型 SHA-256 不变。每项预热 2 次后测量 7 次，OCR 中位数 343.9889→373.1095 ms（**+8.47%，+29.12 ms**），英雄匹配 +2.15%，捕获 −2.69%。OCR 在该 runner 上测得变慢，仍通过已批准门限；不宣称没有减速，也不推及所有电脑或真实对局。早期实验的 +1.89% 仅为历史数据。四种格式及三种 ICC 格式、原生缩放、OTA、源码及许可门禁也已通过。

最终 v0.4.4 已重新构建并通过全部门禁，采用 110,000,000 字节上限；发布门还会从七次原始样本重算中位数，任何测试项同时慢于基线 15% 且超过 5 ms 时停止自动发布并诊断，不靠反复重跑碰到通过值。发布门还核对最终可下载的补充许可证 ZIP，并严格绑定配方、源码、原生二进制与同机对比证据。实验仍保留 115,000,000 字节上限与 50% + 5 ms 的粗筛，且不能发布。v0.4.4 仍为预览版，稳定 OTA 排除；已发布标签和资产不变。真实截图报告已按 v0.4.4 实际重跑，但仅代表 Linux 官方 wheel 小样本。真实 LoL/Vanguard、干净机器和所有输入范围仍未验证。
