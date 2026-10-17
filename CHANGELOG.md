# Changelog / 变更日志

## v0.4.13 · 标题语义核验与整局诊断 / Semantic recheck diagnostic candidate

候选版本，仍须通过全部 Windows 发布门禁。标题带的像素变化不再被直接当作标题变化；同帧新 OCR 核验有序名称、置信度、几何与英雄范围。仅等待语义时，原评级仍受原四秒期限约束，不因像素变化刷新年龄；真正换牌可能在新 OCR 返回前短暂保留原评级，并非即时检测。明确矛盾、不确定语义或过期时撤销评级；核验中的中性卡片不含旧评级或提示。

部分候选栏按槽位独立保留已确认卡片；同帧新语义证据只能保留对应槽位，改变或不确定的槽位撤销旧计数，未知卡片不带旧评级。

关键阶段/设置/隐藏原因与常规采样分开保存，全部日志文件总计仍限 768 KiB。新增选人发现与阻断门槛诊断，不改变 LCU 同意或窗口资格规则，也不宣称真实客户端选人问题已解决。仅合成回归进入仓库，不包含用户日志或截图。

English: Candidate pending all Windows gates. Fresh same-frame semantic title verification replaces pixel-hash-only revocation; historical grades retain only their original four-second deadline. Real rerolls can remain displayed until fresh OCR returns, never an instantaneous-detection claim. Separate bounded critical/context lanes retain causes across routine rotation, and selection gate diagnostics explain routing without relaxing permissions. Actual-game behavior remains unverified.

## v0.4.12 · 捕获稳定性诊断测试版 / Capture stability diagnostic prerelease

2026-10-17 已通过完整 Windows 发布门禁并发布为非 latest 预发布；不代表实际对局验证通过。
默认开启可关闭的本地诊断日志，三份 256 KiB 文件合计最多 768 KiB；本地 ZIP 导出替换同一文件，不自动上传。记录关联帧、隐藏原因、阶段耗时、确认门槛及已匹配的目录英雄/强化名称，不记录截图、原始 OCR、玩家账号、凭据或私有路径。重复采样合并，导出说明轮转与截断。

同一英雄/卡片仅来源或评级文字变化时减少不必要的隐藏；模糊匹配跳过数学上不可能满足原有门槛的比较，不放宽接受或歧义检查。Windows 受控测试、Linux 小样本静态截图与实际对局验收分别记录，不能据此宣称闪烁或延迟已在游戏中解决。

English: Published non-latest prerelease after every Windows release gate passed on 2026-10-17. Default-on, switchable local logs are bounded to 768 KiB (3 × 256 KiB); export replaces one local ZIP and nothing uploads automatically. Same-card badge stability and conservative fuzzy-matching pruning retain freshness and fail-closed behavior. Actual-game flashing/rechecking and latency remain unverified. Publication must remain a non-latest prerelease; stable OTA will not discover it. See [diagnostic scope](BOUNDED_DIAGNOSTICS.md).

## v0.4.10 · 同局英雄保留与独立卡片评级

2026-10-17 已发布预览版，[Windows 完整运行 #71](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/39015163655) 通过全部门禁；仍需手动下载，真实对局待验证。默认开启可关闭的本局英雄只读核验；同一核验游戏进程中的可靠英雄身份可跨死亡倒计时保留，评级仍需当前候选和四秒新鲜度。开始后自动最小化改为默认关闭、保留可选设置。

卡片上方使用三个独立区域的小型评级标记，基于当前卡边界；准确标题区域不变时允许背景动画，变更候选/英雄立即撤销旧建议。附带有来源的英雄专属强化搭配文字，不转换胜率或宣称实时最优。捕获诊断说明何时仍必须隐藏截图。

English: Published preview on 2026-10-17 after all Windows release gates passed. Manual download is required; live-client acceptance remains unverified. Verified same-game hero continuity survives death/countdown obstruction; offers retain fresh-frame and four-second expiry guards. Current-game read-only identity is on by default, automatic minimization is off by default, and both have saved controls. Three separately bounded above-card badges include source-backed combo hints. Windows/native release gates and live-client limitations remain explicit. See [implementation scope](DEATH_IDENTITY_AND_CARD_BADGES.md).

## v0.4.9：窗口衔接、分栏识别与诊断

[v0.4.9 预览版](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.9) 已于 2026-10-16 发布，[Windows 完整发布运行 #62](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38946465944) 通过全部必需门禁，包括同一 EXE 的 100%/150%/200% 捕获、部分候选栏及恢复、选人衔接、同二进制更新和最终源码/许可校验。

修正可变标题/无标题窗口的连接、补充受身份校验约束的客户端窗口类；复用有界 HUD/OCR 工作线程，逐栏展示独立确认结果，未知栏不借用旧评级。两项本机只读 API 身份辅助需分别主动开启，仅限本次会话。诊断区分窗口、截图、英雄、文字与评级缺失。

实际 EXE 为 **106,971,324 字节（102.02 MiB）**。真实 LoL/Vanguard、用户实际对局与可选 API 的现行客户端兼容性仍未验证；不能据此认定用户的慢识别或闪烁已解决。保持非 latest 预览版，稳定 `/releases/latest` OTA 不会发现，需手动下载。详见[发布身份](WINDOWS_EXECUTABLE.md)与[验证范围](reports/VALIDATION.md)。

English: [v0.4.9](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.9) was published on 2026-10-16 after [Windows release run #62](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38946465944) passed every required gate, including the same EXE at 100%/150%/200%, partial-slot display/recovery, selection handoff, same-binary OTA and final source/license checks.

Stable window identity now survives caption changes and untitled windows under existing executable/signature guards. A bounded HUD/OCR worker is reused, independently confirmed slots can appear while unknown slots stay ungraded, and diagnostic reasons distinguish window/capture/hero/title/tier failures. Two optional read-only local API identity helpers require separate, default-off, current-session consent.

The EXE is **106,971,324 bytes (102.02 MiB)**. Real LoL/Vanguard, the user's match, and current-client compatibility of the optional APIs remain unverified; passing owned fixtures does not establish that the reported latency/flicker is resolved. This is a non-latest prerelease: stable `/releases/latest` OTA does not discover it, so download manually. See [release identity](WINDOWS_EXECUTABLE.md) and [validation scope](reports/VALIDATION.md).


## v0.4.8 · 显示过期与可见捕获修正 / Display expiry and guarded visible capture

**2026-10-15 已发布预览版 / Prerelease published.** [完整发布运行 #55](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38793233284) 通过全部必需门禁并发布 [v0.4.8](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.8)；源码/标签 `00bbf5affc02c32cbd9bf367199047eefdf208f8`，源码树 `cae3f15c3916f146c26d2d2d966efffe7169f886`。EXE **106,925,126 字节（101.97 MiB）**，SHA-256 `d682d42478f1489395bd35ed933c1b6eda7fed00ef9d1315f564d5e4cd89958b`。发布校验绑定 15 项资产与 60 项证据，保持非 latest，稳定 OTA 不自动发现。

- 四秒显示过期仍隐藏旧资料，但不再取消授权未变且自身仍新鲜的在途推理；失焦、身份/几何/权限变化和停止仍立即撤销。完成驱动的间隔会按剩余新鲜度缩短，不延长旧观察有效期。
- 正常入口默认启用受保护的可见叠加捕获：只有精确属于助手的不透明 HWND、令牌/样式、`WDA_EXCLUDEFROMCAPTURE=0x11` 与运行时身份/前台/ROI 证明均成立时，才保留标注的旧资料；原有严格隐藏路径及拒绝边界不变。源码与同一冻结 EXE 的三档正常入口、变化 ROI 和像素排除检查通过。
- 仪表盘按规范英雄 ID 显示已核验缓存中的真实英雄头像及公开源评级；头像呈现不等于新的自动识别证明。
- 设置新增默认关闭、每次启动重新授权的“本地调试日志（仅本次启动）”和“导出调试 ZIP”。三份 256 KiB 轮转文件只记录白名单状态/计数/耗时，排除截图、识别文字、名称、账号、令牌与私有路径；导出仅在本机，不自动上传。
- v0.4.8 公开静态截图小样本已重跑，结果仍为本人 HUD 正例 2/3、1 次弃权、反例 3/3 弃权；选人正例 1/1、反例 3/3（两个场景）。这是 Linux 官方 wheel 小样本。用户无边框模式下的后续轮次闪现、实际 LoL/Vanguard、真正独占全屏及自动最终已选强化仍待实战验证。
- Separates presentation expiry from valid same-authority inference, enables exact-owned guarded visible capture after source/frozen acceptance, displays cached champion portraits/tiers, and adds per-launch opt-in bounded local debug ZIP export. Run #55 passes all release gates; controlled Windows and public still-image evidence do not establish that the reported live-game issue is resolved.

## v0.4.7 · 浅色仪表盘与捕获复核 / Light dashboard and capture rechecks

**2026-10-15 已发布预览版 / Prerelease published.** [完整发布运行 #48](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38707221941) 通过全部必需门禁并发布 [v0.4.7](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.7)；源码/标签 `1046af25d66e12c784554c38351e75ed82afa81b`。EXE **106,858,822 字节**，SHA-256 `96bc81fcb12dc48c45e210706b358eb5eeccc062574166b440bf1452f4000547`。15 项公开资产与校验一致，保持非 latest，稳定 OTA 不自动发现。

- 统一 B 浅色仪表盘与名称+评级的紧凑叠加；设置、核对资料、关于放入次级页面，监测期间仍可停止。公开源/虚构演示标记、三个候选原位置、半屏上限及完整来源/许可入口保留。
- 按完成时间安排下一轮；严格已接受帧证明通过后，推理期间可显示“上次候选复核中”，不刷新过期时间或独立确认计数。持续 HWND 会话复用保留截图前隐藏、ROI/身份/前台校验与 GUI 外清理；正常系统捕获边框保持开启。
- 客户端单独显示公开源英雄整体 T1–T5，明确仍可交换、HUD 未复核。核对页保留“上次候选 · 最终选择未知”，不把候选消失、最高评级或鼠标位置当作已选强化。
- [完整诊断运行 #46](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38699532128) 通过源码、实际应用入口的源码/冻结会话、100%/150%/200% 正常产品两种后端、选人、生命周期、OTA、体积、源码与许可门禁；该次关闭发布。随后运行 #48 重新构建并通过全部发布门禁，最终 EXE 与公开资产身份已核验。产品时序中的目标 350 ms 人工保持不是自然游戏延迟。
- 固定后构建官方/自编译配对保留原始门限（同时超过 15% 且 5 ms 才停止发布）。[运行 40/41 的拒绝结果与运行 44/46 的后续证据](POSTBUILD_OPENCV_VALIDATION.md)完整保留，不宣称已确定早期差异的原因或自编译版本普遍更快。
- v0.4.7 真实公开静态截图小样本实际重跑：本人 HUD 正例 2/3、1 次弃权，反例 3/3 弃权；选人正例 1/1、反例 3/3（两个场景）。仍是 Linux 官方 wheel 小样本，不代表实战识别率或 Windows 游戏兼容性。
- Implements the light B dashboard, secondary Settings/Check reference/About pages and ordered name+tier overlay. Completion-driven cadence and accepted-frame rechecks avoid unnecessary prolonged hiding, while unknown/stale results still fail closed. Champion-select public T1–T5 and a last-candidates record remain separate from augment confirmation and final-choice detection.
- Run #46 passed the full diagnostic with publication disabled. Run #48 subsequently passed all release gates, and the final exact-byte/public-asset audit matches the published download. Controlled holds and synthetic capture timings are not game latency or an overall speed factor. True exclusive fullscreen, live LoL/Vanguard and automatic final-selected-augment recognition remain unverified; idle GPU surfaces and asynchronous cleanup limits remain explicit. Existing tags/assets and prior failed samples are preserved.

## v0.4.6 · 原生界面与截图识别可靠性

- [Windows 发布运行 #23](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38531070525) 通过全部门禁并发布 [v0.4.6 预览版](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.6)。源码/标签 `f7ce587ee9a93fc509fd4b4e5b6a1cce150b2423`；EXE **106,553,042 字节（101.62 MiB）**，SHA-256 `0c2aef8e7759c149d6da90348d2ba065590c7e39b5f1522906d7e658b1b08d3a`。保持 prerelease / 非 latest，稳定 OTA 不自动发现。真实 LoL/Vanguard 仍未验证。

- 原生控制台与资料叠加重新设计：保留 VGA 图标，分层深蓝灰界面、固定主操作、左中右三候选核对和可折叠高级设置。窗口按可用工作区适配；叠加紧凑化并限制在客户区一半高度内，无法清晰放入则隐藏。完整效果可在控制台按名称查阅；人工选定英雄后可查看其来源评级与条件。查阅与监测确认状态分离，过期自动结果仍清空。

- 修正已单独重现的头像缓存条带锁碰撞：不同文件使用独立、活动结束即回收的路径锁，同文件有界等待与共享锁恢复保持不变。CI 首次缓存失败和历史用户 WinError 5 的原因仍未确认；失败断言补充本地净化诊断。

- 原创、明确 HWND 的 Windows Graphics Capture 一次性辅助程序；严格客户区 ROI、绑定身份、取消与超时清理。缺失/不支持时才回退，拒绝/保护/空白不绕过。
- 捕获拒绝时补充有界、白名单化的原生阶段/检查及几何诊断，便于定位 Windows 差异；不记录标题、路径或截图，不放宽拒绝条件。
- 修正 Windows 初始捕获项包含不可见边距、实际帧内容较小时的几何假设；仅接受精确、唯一的原窗口边界，ROI 不得跨入未定义纹理填充，并新增带边框/无边框窗口的三倍率像素门禁。
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
