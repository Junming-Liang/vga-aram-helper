<!-- project-header:start -->
<p align="center"><a href="README.md">简体中文</a> | <a href="README.en.md">English</a></p>
<p align="center">
  <img src="assets/branding/vga-icon-128.png" width="112" height="112" alt="VGA乱斗助手图标">
</p>
<h1 align="center">VGA乱斗助手 · 英雄联盟海克斯大乱斗助手</h1>
<p align="center"><strong>海克斯强化符文推荐 · 英雄专属评级 · 本地截图识别</strong></p>
<p align="center">
  <a href="https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/build-native-preview.yml"><img src="https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/build-native-preview.yml/badge.svg?branch=main&amp;event=workflow_dispatch" alt="Windows CI：最近一次手动构建与测试"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-16a34a" alt="License: MIT"></a>
  <a href="app_version.py"><img src="https://img.shields.io/badge/source-v0.4.13-0891b2" alt="源码版本 v0.4.13"></a>
  <a href="https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.12"><img src="https://img.shields.io/badge/status-preview-d97706" alt="v0.4.12 预览版"></a>
</p>
<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="WINDOWS_EXECUTABLE.md">Windows 指南</a> ·
  <a href="DATA.md">推荐与统计</a> ·
  <a href="CONTRIBUTING.md">参与贡献</a> ·
  <a href="https://github.com/Junming-Liang/vga-aram-helper/issues">反馈问题</a>
</p>
<!-- project-header:end -->

VGA ARAM Helper is not endorsed by Riot Games and does not reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games and all associated properties are trademarks or registered trademarks of Riot Games, Inc.

声明依据：[Riot Developer API Policy](https://developer.riotgames.com/docs/lol#developer-api-policy)。

VGA乱斗助手是一款面向《英雄联盟》（League of Legends / LoL）海克斯大乱斗（ARAM: Mayhem）的开源 Windows 辅助工具。通过原生控制面板与游戏叠加层，为海克斯强化符文三选一提供英雄专属评级、机制说明与条件提醒。

v0.4.12 预览版已通过完整 Windows EXE 发布验收；真实对局反馈仍待验证。详见 [发布检查表](PUBLICATION_CHECKLIST.md) 和 [验证范围](reports/VALIDATION.md)。

默认从本人 HUD 头像自动识别英雄；英雄与三个候选连续高置信识别后，自动显示当前英雄资料。不确定时保留人工纠正。

选人衔接：客户端出现后，可点击主界面“开启本机选人识别”，授权本次启动的只读接口；未开启或接口不可用时保留截图回退。截图回退须确认本人高亮行与中央英雄名一致，再接续本局新游戏窗口；局内尚未复核时会明确标注“来自本局选人 · HUD未复核”。

## 海克斯大乱斗辅助功能

- **英雄专属海克斯评级**：展示虎牙公开源的 T1–T4 评级，保留三个候选的原始顺序；缺失数据标为“暂无评级”。
- **自动本人英雄**：默认开启可关闭的本局只读 API 核验，并保留底部本人 HUD 头像匹配；可靠身份经独立确认后可在同一核验游戏会话内跨死亡倒计时保留。不会从记分板或全屏人名猜英雄。
- **本地 OCR**：布局和置信度通过、连续两帧独立确认的候选栏可先显示；未知栏保持无评级，不借用旧结果。不确定时人工修正。
- **卡片上方评级**：三个独立区域保留原候选顺序，显示 T 级、身份来源与可用搭配提示；完整名称和说明可在控制台查阅。当前卡边界无法确认时隐藏，默认鼠标穿透。
- **数据刷新与缓存**：启动时检查公开资料，离线时使用已验证缓存。
- **软件更新**：检查稳定版 GitHub Release，确认后下载并校验安装。

## 快速开始

### Windows

1. 下载 [v0.4.12 Windows x64 EXE](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.4.12/vga-aram-helper-0.4.12-windows-x64.exe)，核对同版 [SHA-256](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.4.12/SHA256SUMS.txt)。
2. 将 EXE 放入有写入权限的文件夹，双击启动。
3. 保持默认“自动识别英雄联盟”，点击“开始本局监测”。默认保持控制台可见，自动等待或接续客户端/游戏，无需选择窗口。首次启动会准备约 5 MB 的公开头像缓存。
4. 如需选人接口识别，在检测到客户端后点击主界面“开启本机选人识别”。该授权仅本次启动有效，重启后仍默认关闭。

单文件 EXE 已集成 QtWidgets、OCR 运行时与模型。安装说明见 [Windows 指南](WINDOWS_EXECUTABLE.md)，许可与使用条款见下方[许可](#许可)。[Release 页面](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.12)提供测试证据和对应源码。

v0.4.12 预览版已发布，需手动下载，稳定 OTA 不自动发现。请核对同版清单与 SHA-256；机制见 [UPDATES.md](UPDATES.md)。

### 从源码运行

使用 Python 3.12 x64，在项目目录的虚拟环境中运行：

```sh
python -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-build.txt
python launcher.py
```

`python launcher.py --demo` 可载入合成演示数据。开发配置和测试命令见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## v0.4.13：标题语义核验诊断候选（待 Windows 验收）

源码候选改用同帧标题语义核验，避免仅因标题带背景像素变化就隐藏或切换评级文字。部分候选按槽位独立核验，未知一张不再要求撤下另外两张已确认评级。原评级只保留原有四秒期限；真正换牌可能等待新 OCR 才撤销，不保证即时检测。日志加入独立关键事件保留和选人门槛，仍不自动上传。下载链接暂保留已发布 v0.4.12；真实对局尚未验证。详见[候选验证记录](reports/SEMANTIC_RECHECK_DIAGNOSTICS.md)。

## v0.4.12：捕获稳定性诊断测试版（已发布）

[v0.4.12 诊断测试版](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.12) 已于 2026-10-17 发布，[完整 Windows 发布运行](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/39037126275) 通过全部既有门禁。发布提交为 `966f79ea7305d716d6ae854432cf20a08344e985`；实际下载 EXE 为 **107,058,338 字节**，SHA-256 为 `cf7564424e5981f0c56004547301acb78cd3f3c2896fe60a91b0c95d5f39aa3b`，与同版清单及校验文件一致。

本版默认开启可关闭的本地日志，总上限 768 KiB（3 × 256 KiB），导出替换同一个本地 ZIP，不自动上传。保持非 latest 预览版，需手动下载；实际对局的闪烁、复核与延迟仍未验证，不能据此宣称问题已解决。详见[诊断说明](BOUNDED_DIAGNOSTICS.md)。

## v0.4.11：捕获切换与选人识别修复

[v0.4.11 预览版](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.11) 已于 2026-10-17 发布，[完整 Windows 发布运行](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/39025025768) 通过全部必需门禁。修复持续截图清理等待时反复切回隐藏模式的问题，避免这一分叉导致重复隐藏和候选反复复核；候选新鲜度与遮挡检查仍生效。

已授权的选人接口读取与截图分离，截图不可用时仍可读取接口；接口失败后独立安排截图回退，并显示具体的固定原因。主界面新增“开启本机选人识别”入口，默认关闭、仅本次启动授权。

同一最终 EXE 已通过三档捕获/浮层、选人衔接和升级回滚检查；真实客户端及用户对局效果仍需验证。历史 v0.4.10 静态截图报告保留原版本，仅在所有被评测模块哈希一致时沿用，不能视为本轮重跑。详见[验证范围](reports/VALIDATION.md)。

## v0.4.10：同局英雄保留与卡片上方评级

[v0.4.10 预览版](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.10) 已于 2026-10-17 发布，[Windows 完整运行 #71](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/39015163655) 通过全部必需门禁，包括源码与同一 EXE 的三档原生捕获/评级、五档布局、逐栏恢复、选人衔接、同二进制 OTA 与最终源码/许可校验。

本局英雄只读核验默认开启，可关闭；可靠身份在同一核验游戏会话中跨死亡倒计时保留，当前候选仍须独立确认并遵守四秒有效期。选人客户端 API 仍默认关闭。三个卡片上方独立区域显示 T 级和可用的公开源搭配文字；开始后自动最小化默认关闭，可自行开启。

这是非 latest 预览版，稳定 `/releases/latest` OTA 不会发现，须手动下载。受控原创窗口通过验收不代表真实 LoL/Vanguard、用户对局或现行客户端 API 已验证；不保证消除所有闪烁或提高原始 OCR 速度。详见[实现与限制](DEATH_IDENTITY_AND_CARD_BADGES.md)。

## v0.4.9：窗口衔接、分栏识别与诊断

[v0.4.9 预览版](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.9) 已于 2026-10-16 发布，[Windows 完整发布运行 #62](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38946465944) 通过全部必需门禁，包括同一 EXE 的 100%/150%/200% 捕获、部分候选栏及恢复、选人衔接、同二进制更新和最终源码/许可校验。

修正可变标题/无标题窗口的连接、补充受身份校验约束的客户端窗口类；复用有界 HUD/OCR 工作线程，逐栏展示独立确认结果，未知栏不借用旧评级。两项本机只读 API 身份辅助需分别主动开启，仅限本次会话。诊断区分窗口、截图、英雄、文字与评级缺失。

实际 EXE 为 **106,971,324 字节（102.02 MiB）**。真实 LoL/Vanguard、用户实际对局与可选 API 的现行客户端兼容性仍未验证；不能据此认定用户的慢识别或闪烁已解决。保持非 latest 预览版，稳定 `/releases/latest` OTA 不会发现，需手动下载。详见[发布身份](WINDOWS_EXECUTABLE.md)与[验证范围](reports/VALIDATION.md)。

## v0.4.8：显示过期与受保护的可见捕获

[v0.4.8](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.8) 已于 2026-10-15 发布；[Windows 发布运行 #55](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38793233284) 通过源码、冻结 EXE、100%/150%/200% 产品捕获/叠加、选人、更新、性能、体积及源码/许可的全部必需门禁。实际发布 EXE 为 **106,925,126 字节（101.97 MiB）**，见[发布身份与限制](WINDOWS_EXECUTABLE.md)。

- 四秒显示过期仍隐藏旧资料，但不会取消授权未变且自身仍新鲜的较新在途推理；失焦、身份/几何/权限变化及停止仍撤销任务。完成一轮后再安排下一轮，按剩余新鲜度缩短通常的 700/200 ms 等待。
- 正常入口默认启用受保护的可见捕获，必须具备精确属于助手的不透明叠加 HWND、令牌/样式、`WDA_EXCLUDEFROMCAPTURE=0x11`、目标身份、前台与 ROI 的运行时证明。旧资料明确标为“上次候选复核中”，新鲜识别完成后报告候选/英雄身份变化或不确定时隐藏，识别身份不变的无害 ROI 动画不要求隐藏；旧有严格隐藏路径及拒绝/清理规则不变。源码与同一冻结 EXE 通过三档正常入口的变化 ROI 和像素排除检查。
- 仪表盘使用已核验缓存中的真实英雄头像及公开源整体 T1–T5。选人身份仍注明“仍可交换，HUD未复核”；强化评级仍为 T1–T4。“上次候选 · 最终选择未知”不会从牌面消失推断最终选择。
- 此诊断版在“设置”默认开启“本地诊断日志”，可随时关闭；“导出调试 ZIP”仅保存到本机，不自动上传。三份 256 KiB 轮转文件记录关联帧号、隐藏原因、各阶段耗时、确认门槛，以及已匹配词典的英雄/强化名称；不含截图、原始 OCR 文字、玩家标识、账号、令牌或私有路径。覆盖量在导出中注明。详见 [诊断说明](BOUNDED_DIAGNOSTICS.md)。
- 正常 Windows 捕获边框、请求 ROI 限定的 CPU 读回、空闲 GPU 表面与异步清理限制保留。用户无边框对局的后续轮次闪现、真实 LoL/Vanguard、真正独占全屏及自动最终选择仍待实战验证。详见[反馈修正与证据边界](PLAY_FEEDBACK_FIXES.md)。

- 主界面显示本局英雄、监测状态和左/中/右三个候选。一个主监测按钮随状态显示“开始监测”或“停止监测”；次级页面在监测期间仍提供停止入口。
- “设置”调整窗口连接、本人英雄纠正和截图范围；“核对资料”提供候选纠正、明确确认及按输入名称查阅完整资料；“关于”提供完整来源日期、数据包和游戏资料版本、更新状态及兼容性说明。“返回”回到仪表盘。查阅不会自动确认或替换当前监测结果。
- 紧凑叠加显示名称与原始评级，并标明“虎牙公开源”或“虚构演示”；保留三项原位置、鼠标穿透和半屏高度上限。可见评级胶囊（例如 `T1`）与可访问来源标签（`虎牙公开源评级：T1` 或 `虚构源评级（演示）：T1`）是分别验证的证据字段。完整来源资料及“并非 Riot 评级或批准”的限制可在“关于”查看。

## 使用方法

- 保持默认自动识别窗口和本局英雄核验，点击开始后切回游戏；游戏未启动、最小化或被遮挡时会等待重试。存在多个候选或无法核验安装身份时会明确提示。
- 独立确认的本局英雄身份与连续新鲜候选证据齐备后自动显示；同局可靠身份可跨死亡倒计时保留。不会自动选择游戏内选项。
- 不确定时可关闭自动英雄、人工纠正英雄及候选。英雄身份冲突或无法可靠确认、候选变化、过期或切出窗口会隐藏旧资料，自动模式重新等待新鲜证据。
- `Ctrl+Alt+O` 切换交互/参考模式设置，候选评级始终鼠标穿透；停止监测或关闭主窗口即可结束捕获。

### 从选人开始

v0.4.8 保持默认“自动识别英雄联盟”，点击“开始本局监测”即可；控制台会最小化并自动接续同目录客户端/游戏，支持已在对局和稍后启动。本人高亮行、中央名称及选人后的皮肤缩略图区域一致，并连续两帧确认后，记录本局当前英雄。初始候选卡、悬停预览和替补席不会直接作为本人选择。换人后重新确认；不是不可撤回的“锁定”。

选人身份只传递给同一安装目录的唯一新游戏进程；已在运行的游戏仍可自动绑定，但需要重新确认本人 HUD。切换接续选项或点击停止会撤销本局捕获。选人记录与局内头像冲突、画面不明或超时会清空；不确定时仍可人工纠正。尚未识别本人头像时，评级会注明选人来源。详见 [选人衔接范围](CHAMPION_SELECTION.md)。

## 数据与隐私

资料来自[虎牙官方公开 wiki](https://gametool.huya.com/league-of-legends/wiki/index.html?embed=1)。评级使用对应英雄的原始记录；完整资料卡标注来源日期、数据包与游戏资料版本；控制台显示来源日期与游戏资料版本。简版叠加保留各项来源评级，日期和游戏资料版本可回到控制台查看。来源日期和获取时间分别记录，便于判断资料时效。格式与字段说明见 [DATA.md](DATA.md)。

自动模式仅绑定核验身份的同一英雄联盟安装目录，采集前台目标窗口的可见客户区；高级手动诊断需要明确指定窗口并点击开始。客户端与游戏接续核对安装路径、窗口身份和进程创建时间。仅处理屏幕像素，不读取游戏进程内存。正常监测截图在本机内存中处理，不保存或上传；显式合成诊断可保存测试图。应用主动联网用于公开数据、Riot Data Dragon 头像缓存与软件更新；截图不发送给这些服务。头像为 Riot 所有，不随源码或 EXE 打包。

v0.4.4 在 ONNX Runtime 导入/初始化前设置 `ORT_DISABLE_TELEMETRY=1`，同时保留 API 退出设置。[官方 ORT 1.31.0 文档](https://github.com/microsoft/onnxruntime/blob/v1.31.0/docs/Privacy.md)说明 API 可能晚于最小初始化。这是退出设置加固，不推断此前是否发生传输，也不是网络防火墙或完整出站审计。

## 预览版与兼容性

[v0.4.12](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.12) 诊断测试版已可下载，保持非 latest 预览版，需手动更新。当前[验证范围](reports/VALIDATION.md)与下述历史发布记录分开。

### v0.4.7 与更早版本的历史记录

[v0.4.7](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.7) 已通过[发布运行 #48](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38707221941)，引入浅色仪表盘与已接受帧捕获复核；原始身份与测量保留在[验证历史](reports/VALIDATION.md)。

[v0.4.6 预览版](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.6)已通过 [Windows 发布运行 #23](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38531070525) 的全部门禁。新版加入明确 HWND 的 Windows Graphics Capture、异步截图、中文精确匹配修正、有界重复 OCR 复用，以及重新设计的原生控制台和紧凑资料卡。详见[实现与测试范围](REFERENCE_OPTIMIZATION.md)。

源码测试通过三档 WGC 和五档叠加布局；同一最终 EXE 另行通过三档冻结包 WGC、100%/150%/200% 原生捕获与叠加、独立 OCR 确认/复用、选人接续、同版本更新/并发/回滚及源码/许可校验。EXE 为 **106,553,042 字节（101.62 MiB）**，SHA-256：`0c2aef8e7759c149d6da90348d2ba065590c7e39b5f1522906d7e658b1b08d3a`。源码/标签为 `f7ce587ee9a93fc509fd4b4e5b6a1cce150b2423`；仅为预览版，稳定 OTA 不自动发现。原创测试窗口通过不等于真实 LoL/Vanguard 兼容性验证。

历史 [v0.4.5 Windows 发布验证](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38447380079)已通过全部门禁并发布预览版。EXE 为 **106,399,997 字节（101.47 MiB）**；保留既有离线模型和最小 OpenCV 构建配方。下载后请核对同版 SHA-256，完整身份见[体积与哈希记录](WINDOWS_PACKAGE_SIZE.md)。

该 v0.4.5 的真实 Windows 源码测试通过自动等待、客户端/游戏接续、已有游戏、重启、窗口重建、最小化恢复、空白回退和遮挡拦截；捕获与原创测试图的平均通道误差均为 0.0。发行商信任仅对测试自产文件注入，不能据此证明真实游戏签名或兼容性。同次构建还通过七项原生缓存共享锁/诊断测试，以及最终 EXE 的 100%/150%/200% 应用缩放、OCR、选人衔接和本地更新事务验收。历史 WinError 5 的具体占用者/原因仍未确定；新增“头像缓存诊断”只提供本机诊断，不自动上传。

测试范围见[验证记录](reports/VALIDATION.md)；历次体积与性能结果保留在[构建配方记录](WINDOWS_MINIMAL_OPENCV_EXPERIMENT.md)和[变更日志](CHANGELOG.md)，不代表真实对局性能。

v0.4.2 修正已确认的 Qt 逻辑坐标与 Win32 物理坐标不一致，以及固定叠加布局造成的小窗口问题：按叠加窗口自身的 Qt 缩放计算物理位置，空间不足时采用紧凑资料卡，保留三个名称、评级和来源。新鲜资料可随同一窗口平移；尺寸变化后等待重新识别。

[Windows EXE 发布测试](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38281910029)在同一 EXE、固定 960×600 像素的原创模拟窗口中通过了 100%、150%、200% 应用进程缩放检查，覆盖捕获/OCR、自动英雄与三候选、资料卡边界与文字布局、状态清除及关闭清理；选人识别与本局接续检查也已通过。同次构建的源码测试通过了 100%–250% 缩放下的 35 个窗口用例，包括过小窗口隐藏与恢复。实际系统 DPI、多显示器切换、4K 完整可见布局及用户报告的具体报错原因仍未确认。

v0.4.12 诊断版源码在 Linux 官方 wheel 上实际重跑的公开截图小样本中，3 个本人英雄样例识别 2 个（莎弥拉、卡特琳娜），米利欧头像未匹配而停止自动判断；3 个死亡/记分板、观战、竖向裁剪负例均停止判断。2026-10-17 已通过原验证脚本重新生成绑定当前模块哈希的报告；这不构成 Windows 安装包的实际对局证据。不能据此宣称总体识别率或自编译 Windows 包的识别表现。详见 [自动识别范围](AUTO_RECOGNITION.md) 和 [逐例结果](reports/hero-recognition-genuine.json)。

以下为 **v0.3.0 历史基线**，不证明新版自动英雄在 Windows 对局中已通过：

- [原生 EXE 测试](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38235785410)：窗口捕获、OCR、评级显示、鼠标穿透与进程生命周期。
- [更新事务测试](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38239627458)：同一 EXE 的本地替换、健康检查、并发锁与失败回滚。

真实 LoL/Vanguard、独占全屏及干净 Windows 10/11 环境尚未验证；v0.4.8 已通过同二进制原生更新成功/并发/回滚测试；跨版本在线升级和应用内确认交接仍待测试。公开快照评级可能与虎牙私有实时模型不同，评级方法与适用游戏政策仍有未核实之处，本项目未获 Riot/腾讯批准。详细范围见 [WINDOWS_TESTING.md](WINDOWS_TESTING.md)。

EXE 尚无 Authenticode 签名，Windows 可能提示未知发布者。请核对文件哈希并保留系统安全防护。

## 开发与贡献

欢迎通过 [Issues](https://github.com/Junming-Liang/vga-aram-helper/issues) 报告问题，或提交改进。

- [开发环境与测试](CONTRIBUTING.md)
- [Windows 构建](WINDOWS_EXECUTABLE.md)
- [数据来源](SOURCE_NOTES.md)与[验证记录](reports/VALIDATION.md)

## 许可

原创代码、图标和合成测试数据采用 [MIT License](LICENSE)。Qt/PySide/Shiboken 使用适用的 LGPLv3 选项；OCR 依赖、模型及其他第三方组件遵循各自许可。Release 附完整许可、对应 Qt 源码和同提交应用源码，详见[第三方声明](THIRD_PARTY_NOTICES.md)。第三方游戏资料不在本项目 MIT 许可范围内。

使用前请阅读并同意 [Release 许可包](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.4.12/third-party-licenses.zip)中的微软运行库条款。这些条款仅适用于所列微软 DLL，不限制 MIT 应用源码或 Qt LGPL 权利。自编译 OpenCV 与 WGC 辅助程序的 `/MT` 还包含微软发行版 CRT 对象代码，适用微软条款独立于 OpenCV/Qt 许可，更新这部分需要重建；详见[运行库范围说明](THIRD_PARTY_NOTICES.md#microsoft-windows-runtime-components)。

本项目为独立实现，与 Riot Games、英雄联盟及虎牙无官方关联。
