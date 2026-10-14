# Changelog / 变更日志

## 0.4.6 · 可靠性候选

- 修正已单独重现的头像缓存条带锁碰撞：不同文件使用独立、活动结束即回收的路径锁，同文件有界等待与共享锁恢复保持不变。CI 首次缓存失败和历史用户 WinError 5 的原因仍未确认；失败断言补充本地净化诊断。

- 原创、明确 HWND 的 Windows Graphics Capture 一次性辅助程序；严格客户区 ROI、绑定身份、取消与超时清理。缺失/不支持时才回退，拒绝/保护/空白不绕过。
- 捕获拒绝时补充有界、白名单化的原生阶段/检查及几何诊断，便于定位 Windows 差异；不记录标题、路径或截图，不放宽拒绝条件。
- 修正 Windows 捕获项包含不可见窗口边距时与 DWM 可见边框尺寸不同的假设；仅接受无歧义、精确匹配的原窗口边界，并新增带边框/无边框窗口的三倍率像素门禁。
- 截图与 OCR 移出 Qt 控制线程；处理期间隐藏自己的叠加，回传后复核几何与进程身份。
- 修正中文长标题被短包含词抢先匹配；有界精确索引及 2.5 秒完全相同裁剪复用，首次确认仍需两次独立 OCR。
- 新增源码/最终 EXE 三档 WGC 门禁，保留旧 GDI、OCR、布局、选人及更新事务门禁。验证范围与设计来源见 [本轮说明](REFERENCE_OPTIMIZATION.md)。


## v0.4.5 — Automatic windows and capture reliability / 自动窗口与捕获修复

### 简体中文

- 默认自动发现唯一的英雄联盟客户端/游戏，不需要选择窗口；支持先开助手后开游戏、已在对局、同目录重启与窗口重建，以及国服 LeagueClient 子目录布局。
- 开始后最小化控制台，避免助手遮挡自己的捕获；最小化、切出、遮挡和空白帧为自动重试的等待状态。
- HWND GDI 为空白或复制失败时，仅复制完整可见、前台、已核验游戏客户区；对所有更高窗口做相交检查，捕获前后重核验，不创建整桌面截图。
- 自动绑定核对本机签名与游戏文件身份；无法验证时只提供一次会话内的明确安装目录确认，不静默放宽范围。
- 修复头像缓存被占用/拒绝写入时整批已验证头像不可用的问题；有限重试后可用本次内存模板，不把未完整缓存标成成功。
- 增加元数据/生命周期/遮挡/回退及 Windows 真实共享锁回归。新增 Windows 自动发现测试只使用原创窗口；不代表真实 LoL/Vanguard 兼容性验证。

- [Windows 发布运行 #14](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38447380079)通过全部门禁并发布 [v0.4.5 预览版](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.5)，源码/标签 `1939043c64554868bba3931a214d89946a339b53`。EXE 为 **106,399,997 字节（101.47 MiB）**，SHA-256：`c43d1cd0a7848cad6c7b24ffd13943c653b823c19ed3d1992669943457ad2195`。默认流程无需手动选择窗口；仍需点击开始授权本局监测。
- Windows 源码自动发现/捕获测试全部通过，七项原生缓存锁/诊断测试通过；最终 EXE 的缩放、OCR、选人衔接、更新与源码/许可门禁通过。原创窗口测试含明确的测试文件信任注入，不代表真实 LoL/Vanguard 验证；历史 WinError 5 的占用者/根因仍不确定。

### English

- Default Start discovers a unique verified League client/game and follows one installation through late launch, an existing game, restart and HWND recreation. The helper minimizes to avoid covering capture; expected unavailable frames wait and retry.
- Blank or failed HWND capture uses a guarded client-area-only compositor copy, with full higher-window intersection checks before and after capture. Ambiguous or unverifiable automatic candidates never silently broaden capture.
- Validated portrait templates remain usable in memory when bounded cache retries fail. A local diagnostic records write stage, error codes, attributes and sharing probes without paths or pictures; the historical WinError 5 owner/cause is not established.
- [Windows run #14](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38447380079) passed every gate and published [v0.4.5](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.5) from `1939043c64554868bba3931a214d89946a339b53`: **106,399,997 bytes**, SHA-256 `c43d1cd0a7848cad6c7b24ffd13943c653b823c19ed3d1992669943457ad2195`. The source-only automatic fixture, seven native cache cases and final-EXE scale/OCR/selection/OTA/source/license gates passed. Owned-window fixtures and injected fixture trust do not establish real League/Vanguard compatibility.

## v0.4.4 — Adopt minimal OpenCV / 采用精简 OpenCV

### 简体中文

- Windows 发布构建采用已审查的最小 OpenCV 源码配方，并明确设置 `VGA_RELEASE_PACKAGE_PROFILE=minimal-opencv-v1`。自编译发行元数据为 `5.0.0.93+vga1`，原生版本为 `5.0.0`；不冒充官方 PyPI 二进制。
- [最终 Windows 发布运行 #10](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38417923065)通过全部门禁并发布 [v0.4.4 预览版](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.4)。源码/标签 `96245a849e16e19fec4967c9107ac393e86e5ce8`；最终 EXE 为 **106,343,250 字节（101.42 MiB），比 v0.4.3 小 10,215,963 字节（8.765%），比 v0.4.2 累计小 29.242%**。最终 SHA-256：`e9ca12f1b2d290a7dd68fed61723772ee26f8f8ff281c76637a63e70fd88a35d`。早期实验包保留为[历史记录](WINDOWS_MINIMAL_OPENCV_EXPERIMENT.md)，不可替代本次发布身份。
- 同机官方/自编译 OpenCV 的 112 项图像输出、10 项完整 OCR 输出、8 项英雄结果逐项一致，三份原始 OCR 模型 SHA-256 不变。保留全部离线功能、四种截图格式与现有识别算法、分辨率及阈值。
- 最终发布同机对比每项预热 2 次、测量 7 次：OCR 中位数 343.9889→373.1095 ms（**+8.47%，+29.12 ms**），英雄匹配 40.1646→41.0286 ms（+2.15%），原生捕获 12.4758→12.1400 ms（−2.69%）。OCR 在此 runner 上测得变慢，仍通过同时超过 15% 且超过 5 ms 才停止发布的门禁；不代表所有电脑或真实对局表现。
- 去除未用的 Pillow 字体/CMS 原生扩展，Qt 字体功能不变；最终发布 EXE 已通过四种格式和三种带 ICC 元数据图片的解码/OCR。Qt/Microsoft 许可、对应源码、原生缩放与 OTA 门禁继续保留。
- 在运行时导入前设置 `ORT_DISABLE_TELEMETRY=1`，并保留既有 API 退出设置。[ORT 1.31.0 隐私文档](https://github.com/microsoft/onnxruntime/blob/v1.31.0/docs/Privacy.md)说明 API 调用可能晚于最小初始化；此变更不推断历史传输，也不构成网络防火墙。
- 真实截图小样本已用 v0.4.4 源码重新执行；仍是 Linux 官方 wheel 的有限样本，不是自编译 Windows 证明。所有原有弃权及实战、Vanguard、干净机器验证限制保留。
- 额外维护成本包括固定源码、补丁、Community 编译器配方与完整许可证据。最终发布工作流已重新构建自编译 wheel，并通过同机对比和全部冻结 EXE 门禁。保持预览版、稳定 OTA 排除；v0.4.3 及更早标签/资产不变。无 UPX、自定义引导加载器或模型精度削减。

### English

- Adopts the reviewed minimal OpenCV source recipe for Windows releases under the explicit `VGA_RELEASE_PACKAGE_PROFILE=minimal-opencv-v1` profile. Distribution metadata is truthfully `5.0.0.93+vga1`, with native version `5.0.0`; this is a downstream build, not the official PyPI binary.
- [Final Windows release run #10](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38417923065) passed every gate and published the [v0.4.4 preview](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.4), source/tag `96245a849e16e19fec4967c9107ac393e86e5ce8`. The final EXE is **106,343,250 bytes (101.42 MiB), saving 10,215,963 bytes (8.765%) against v0.4.3 and 29.242% overall against v0.4.2**. Final SHA-256: `e9ca12f1b2d290a7dd68fed61723772ee26f8f8ff281c76637a63e70fd88a35d`. Earlier experimental bytes remain [historical evidence](WINDOWS_MINIMAL_OPENCV_EXPERIMENT.md), not this release identity.
- All 112 image outputs, 10 full OCR outputs and eight hero results matched between official/custom wheels on the same Windows runner. All three original OCR model SHA-256 identities are unchanged. Offline features, four screenshot formats, algorithms, resolution and thresholds are preserved.
- Final-release medians from seven same-runner samples after two warmups: OCR 343.9889→373.1095 ms (**+8.47%, +29.12 ms**), hero matching 40.1646→41.0286 ms (+2.15%), native capture 12.4758→12.1400 ms (−2.69%). OCR was measurably slower on this runner, within the publication gate that stops only when both >15% and >5 ms slower. This does not establish universal or real-game performance.
- Removes unused Pillow font/CMS native extensions without changing Qt fonts. The final release EXE passed decoding/OCR for all four formats and three ICC-bearing images. Qt/Microsoft notices, corresponding source, native scaling and OTA gates remain required.
- Sets `ORT_DISABLE_TELEMETRY=1` before runtime imports and keeps the existing API opt-out. [ORT 1.31.0's privacy documentation](https://github.com/microsoft/onnxruntime/blob/v1.31.0/docs/Privacy.md) explains that the API can run after minimal initialization. This does not establish historical transmission or create a network firewall.
- Genuine screenshot samples were actually rerun with v0.4.4 source. They remain limited Linux official-wheel evaluations, not Windows custom-wheel proof; all abstentions and live-game/Vanguard/clean-machine limits remain.
- Maintaining pinned source, downstream patches, the Community compiler recipe and complete license evidence adds maintenance work. The final publisher freshly built the custom wheel and passed paired comparisons plus every frozen-EXE gate. v0.4.4 remains a prerelease excluded from stable OTA; v0.4.3 and earlier tags/assets are preserved. No UPX, custom bootloader or model-accuracy cuts.

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
