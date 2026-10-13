# Isolated second-round Windows size experiment

This is a **read-only build experiment**, not an adopted dependency change or a new release. The ordinary Windows release workflow still uses the official OpenCV wheel and rejects an unexpected distribution version. The final publisher rejects an experimental artifact even if its environment flag is later cleared. Published v0.4.3 and earlier assets remain unchanged.

## Measured starting point

The released v0.4.3 EXE is **116,559,213 bytes** (SHA256 `2dbe5c1a76b8fd13e2758eb1b6ad952da0a89a391890963c71dfe55cb054dc0b`), built from `67361ca90124a8e5dee69d1fa0c560711fe9dac6` in [the successful Windows run](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38383752875). Its actual CArchive stores `cv2/cv2.pyd` in **30,519,497 bytes**, expanded **85,848,064 bytes**. This is the largest remaining member. The three OCR model files are unchanged and are not candidates for compression by quantization or lower-accuracy replacement.

A separate Linux prototype of the same OpenCV source reduced that platform's native library from 31,283,599 to 23,085,439 zlib-compressed bytes (8,198,160 bytes saved). Exact synthetic comparisons passed for 57 image operations, seven full OCR outputs, and eight hero results; a separate 56-output numerical corpus also matched. **These are Linux results, not Windows EXE savings or an accuracy guarantee.** A stricter follow-up diagnostic matched 112 image outputs, 10 full OCR results and eight hero results, but rejected that old Linux prototype because JPEG SIMD was disabled and its PNG library version differed. Timings varied across two corrected runs: OCR ranged from roughly −0.5% to +42.1%, and hero matching from +14.2% to +24.6%. This is not a performance-parity pass. The Windows recipe and gate require the original SIMD/codec settings and disclose every measured timing difference before an adoption decision.

## Candidate design

- Build the official `opencv-python-headless` **5.0.0.93** source distribution, SHA256 `b82f9831daab90b725c7c1ee1b36cb5732c367096ac76d119e64e14eb70d5f3c`, with only the used core/image-processing/image-codec/Python modules and their required OpenCV 5 dependencies.
- Use explicit local distribution version **5.0.0.93+vga1**. This is a downstream build, not the official PyPI binary. Native `cv2.__version__` remains the upstream C++ version 5.0.0.
- Preserve PNG/JPEG/WebP/BMP, SSE3 CPU baseline and runtime dispatch through AVX512, IPP, OpenCL, precise floating-point settings, accurate algorithm hint, and baseline static MSVC CRT linkage. Use the approved Community compiler, not an implicitly selected runner Enterprise installation.
- Hash-pin the original source, Windows IPP input and built-in font; retain bundled codec sources. The four small downstream Python packaging/typing-generation changes do not edit C++ algorithms. Record original/patched file hashes, exact patch, compiler/configuration, wheel/native hashes and complete generated license notices, including current IPP and fonts.
- In this experimental EXE only, exclude Pillow's unused font-rendering and color-management native extensions. Application text is rendered by Qt. Ordinary screenshot decoding is preserved and tested with ICC metadata as well as the four input formats.
- Keep the stock PyInstaller bootloader and compression. No UPX, Zopfli, model changes, browser replacement or first-run model download is introduced.

The experiment also hardens the existing ONNX telemetry opt-out: ORT 1.31.0 documents that the API alone may run after minimal initialization. The launcher, model-inventory and OCR entry paths now set `ORT_DISABLE_TELEMETRY=1` before runtime import and retain the API opt-out. See [the exact upstream privacy documentation](https://github.com/microsoft/onnxruntime/blob/v1.31.0/docs/Privacy.md). This does not claim a general network firewall or prove that every possible third-party network path is blocked.

This adds a maintained source-build recipe and downstream packaging patches. Repeated source/configuration inputs are documented; byte-for-byte rebuild identity across changing GitHub runner/compiler images is **not** claimed.

## Validation and evidence

Dispatch `.github/workflows/test-windows-minimal-opencv.yml` on the public repository's main branch. It is manual, read-only, uses the standard free `windows-2022` runner, and uploads only bounded one-day evidence after the existing storage-budget check. It cannot publish a release.

The workflow runs the official wheel and the custom wheel in separate fresh interpreters on the **same Windows runner**. Exact image-operation/OCR/hero comparisons and repeated warmed timing checks precede freezing. Seven measured samples after two warmups cover image operations, OCR, hero matching and a process-owned synthetic Win32 capture window. The coarse failure screen is both 1.5× and more than 5 ms slower; every raw sample and ratio remains visible below that threshold, and passing it does not authorize adoption of a meaningful slowdown. Build flags, native bytes and truthful metadata are checked. Basic performance evidence is limited to the tested workload and runner, not a guarantee for every computer or real gameplay.

The resulting EXE must then pass every existing acceptance gate: source/unit/JavaScript checks, source DPI matrix, actual bundled OCR and four input formats, browser UI, Qt native capture/overlay at 100/150/200% application scale, automatic hero and owned selection handoff, exact-binary OTA success/concurrency/rollback, model SHA256, Qt/Microsoft/source/license verification. ICC-bearing PNG/JPEG/WebP screenshots are also decoded through the actual isolated EXE. The archived custom OpenCV binary and all supplemental notices must match their build hashes. The experiment has a 115,000,000-byte EXE cap, below the released v0.4.3 baseline.

Evidence uses `reports/windows-opencv-{build,baseline,candidate,parity}.json` plus the existing Windows reports. The verifier recomputes comparisons and rereads the actual CArchive rather than trusting a size claim. The existing limited genuine-screenshot reports remain historical v0.4.3 Linux evidence using the official wheel; they are not relabeled as Windows/custom-wheel evaluations. No final Windows saving is stated until this run succeeds. No real game, Vanguard, clean end-user machine, exhaustive input-domain or universal performance claim follows from these fixtures.

## 中文摘要

这只是第二轮只读验证，还没有把自编译 OpenCV 作为正式依赖。v0.4.3 发布包仍为 116,559,213 字节。Linux 实验约省 7.8 MiB，但 Windows 安装包能省多少，要以新的原生构建实测为准。

候选保留全部离线模型、当前四种截图格式和 CPU 加速方式；只编译实际使用的图像模块，并明确标记 `+vga1`，保存源码、补丁、编译器和许可证证据。代价是后续需要维护这套自编译配方。新包必须先通过同机数值/识别/性能对比和完整 Windows 冻结 EXE 测试，才讨论是否采用；本工作流不发布新版本。
