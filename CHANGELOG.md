# Changelog / 变更日志

## v0.4.4 — Adopt minimal OpenCV / 采用精简 OpenCV（发布准备中）

### 简体中文

- Windows 发布构建采用已审查的最小 OpenCV 源码配方，并明确设置 `VGA_RELEASE_PACKAGE_PROFILE=minimal-opencv-v1`。自编译发行元数据为 `5.0.0.93+vga1`，原生版本为 `5.0.0`；不冒充官方 PyPI 二进制。
- [只读 Windows 验证 38410925432](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38410925432)在源码 `db5db2b92c61df179491a432316cdd022466a6e8` 全部门禁通过：实验 EXE 为 **106,342,697 字节，比已发布 v0.4.3 小 10,216,516 字节（8.765%）**。该实验 EXE 内部仍为 v0.4.3，**不是 v0.4.4 发布包**；最终 v0.4.4 体积、哈希及通过状态必须以重新构建后的结果为准。
- 同机官方/自编译 OpenCV 的 112 项图像输出、10 项完整 OCR 输出、8 项英雄结果逐项一致，三份原始 OCR 模型 SHA-256 不变。保留全部离线功能、四种截图格式与现有识别算法、分辨率及阈值。
- 每项 2 次预热、7 次测量的中位数：OCR 207.8164→211.738 ms（+1.89%，+3.92 ms），英雄匹配 33.469→32.1846 ms，原生捕获 9.912→9.3513 ms。该样本未显示明显性能退步；不代表所有电脑或真实对局。
- 去除未用的 Pillow 字体/CMS 原生扩展，Qt 字体功能不变；实验已通过四种格式和三种带 ICC 元数据图片的实际 EXE 解码/OCR。Qt/Microsoft 许可、对应源码、原生缩放与 OTA 门禁继续保留。
- 在运行时导入前设置 `ORT_DISABLE_TELEMETRY=1`，并保留既有 API 退出设置。[ORT 1.31.0 隐私文档](https://github.com/microsoft/onnxruntime/blob/v1.31.0/docs/Privacy.md)说明 API 调用可能晚于最小初始化；此变更不推断历史传输，也不构成网络防火墙。
- 真实截图小样本已用 v0.4.4 源码重新执行；仍是 Linux 官方 wheel 的有限样本，不是自编译 Windows 证明。所有原有弃权及实战、Vanguard、干净机器验证限制保留。
- 额外维护成本包括固定源码、补丁、Community 编译器配方与完整许可证据。最终发布工作流必须重新构建自编译 wheel、重新做同机对比和全部冻结 EXE 门禁。保持预览版、稳定 OTA 排除；v0.4.3 及更早标签/资产不变。无 UPX、自定义引导加载器或模型精度削减。

### English

- Adopts the reviewed minimal OpenCV source recipe for Windows releases under the explicit `VGA_RELEASE_PACKAGE_PROFILE=minimal-opencv-v1` profile. Distribution metadata is truthfully `5.0.0.93+vga1`, with native version `5.0.0`; this is a downstream build, not the official PyPI binary.
- [Read-only Windows run 38410925432](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38410925432), source `db5db2b92c61df179491a432316cdd022466a6e8`, passed all gates at **106,342,697 bytes, saving 10,216,516 bytes (8.765%) against released v0.4.3**. That experimental EXE still identifies as v0.4.3 and is **not the v0.4.4 release**. Final v0.4.4 bytes, hash and pass status require a fresh release build.
- All 112 image outputs, 10 full OCR outputs and eight hero results matched between official/custom wheels on the same Windows runner. All three original OCR model SHA-256 identities are unchanged. Offline features, four screenshot formats, algorithms, resolution and thresholds are preserved.
- Medians from seven measured samples after two warmups: OCR 207.8164→211.738 ms (+1.89%, +3.92 ms), hero matching 33.469→32.1846 ms, native capture 9.912→9.3513 ms. No meaningful regression was shown in this sample; these are not universal or live-game performance guarantees.
- Removes unused Pillow font/CMS native extensions without changing Qt fonts. The experiment passed actual-EXE decoding/OCR for all four formats and three ICC-bearing images. Qt/Microsoft notices, corresponding source, native scaling and OTA gates remain required.
- Sets `ORT_DISABLE_TELEMETRY=1` before runtime imports and keeps the existing API opt-out. [ORT 1.31.0's privacy documentation](https://github.com/microsoft/onnxruntime/blob/v1.31.0/docs/Privacy.md) explains that the API can run after minimal initialization. This does not establish historical transmission or create a network firewall.
- Genuine screenshot samples were actually rerun with v0.4.4 source. They remain limited Linux official-wheel evaluations, not Windows custom-wheel proof; all abstentions and live-game/Vanguard/clean-machine limits remain.
- Maintaining pinned source, downstream patches, the Community compiler recipe and complete license evidence adds maintenance work. The final publisher must freshly build the custom wheel and repeat paired comparisons plus every frozen-EXE gate. v0.4.4 remains a prerelease excluded from stable OTA; v0.4.3 and earlier tags/assets are preserved. No UPX, custom bootloader or model-accuracy cuts.

## v0.4.3 — Windows package size / Windows 包体积

### 简体中文

- 清理未使用的视频/AVIF解码库、独立 ONNX C-API DLL、Qt OpenSSL 残留、重复 Python 源码和未引用的设计图片。
- 完整保留三份原始离线 OCR 模型、原生 QtWidgets 叠加与捕获、自动英雄/选人接续、公开数据刷新及 OTA；未调整识别算法、分辨率或置信阈值。
- [最终 Windows 发布构建](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38383752875)通过全部门禁，EXE 为 **116,559,213 字节（111.16 MiB），比原 v0.4.2 小 22.445%**。请核对该版清单和 SHA-256。
- 增加125,000,000字节体积上限、归档内模型SHA-256、PE/TLS依赖保护，锁定基线构建依赖版本。
- 发布门禁增加四种支持格式的实际 EXE OCR、该候选的原生 OTA 成功/并发/回滚，并继续执行多倍率原生捕获、自动英雄/选人、源码与许可验证；对应报告随同版证据提供。
- 小样本 Linux 截图以 v0.4.3 源码重新执行，原有安全弃权与范围限制保持不变；不扩大为实战准确率或反作弊兼容性证明。
- v0.4.2 标签与资产保持不变。v0.4.3 为预览版，稳定 OTA 不自动发现；未使用 UPX，不改动 Microsoft/Qt 许可与对应源码供应。

### English

- Removes unused video/AVIF codecs, the standalone ONNX C-API DLL, orphaned Qt OpenSSL libraries, duplicate Python source and unreferenced design images.
- Preserves all three original offline OCR models, native QtWidgets capture/overlay, automatic champion/selection handoff, public-data refresh and OTA. Recognition algorithms, resolution and confidence thresholds are unchanged.
- The [final Windows release build](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38383752875) passed all gates at **116,559,213 bytes (111.16 MiB), 22.445% smaller than v0.4.2**. Verify its release manifest and SHA-256.
- Adds a 125,000,000-byte size ceiling, embedded-model SHA256 verification, PE/TLS dependency guards and baseline dependency constraints.
- Publishing requires frozen OCR in all four supported formats and that exact EXE's native OTA success/concurrency/rollback, alongside native scale/capture/champion/selection, source and license checks. Evidence accompanies the release.
- The small Linux screenshot sample was rerun with v0.4.3 source; its abstentions and scope limits remain. This is not general real-game accuracy or anti-cheat compatibility proof.
- v0.4.2 remains immutable. v0.4.3 is a preview excluded from stable OTA. No UPX, model replacement or Microsoft/Qt license/source-access change.
