# Changelog / 变更日志

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
