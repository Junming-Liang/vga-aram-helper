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
  <a href="app_version.py"><img src="https://img.shields.io/badge/source-v0.4.5-0891b2" alt="源码版本 v0.4.5"></a>
  <a href="https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.5"><img src="https://img.shields.io/badge/status-preview-d97706" alt="v0.4.5 预览版"></a>
</p>
<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="WINDOWS_EXECUTABLE.md">Windows 指南</a> ·
  <a href="DATA.md">推荐与统计</a> ·
  <a href="CONTRIBUTING.md">参与贡献</a> ·
  <a href="https://github.com/Junming-Liang/vga-aram-helper/issues">反馈问题</a>
</p>
<!-- project-header:end -->

VGA乱斗助手是一款面向《英雄联盟》（League of Legends / LoL）海克斯大乱斗（ARAM: Mayhem）的开源 Windows 辅助工具。通过原生控制面板与游戏叠加层，为海克斯强化符文三选一提供英雄专属评级、机制说明与条件提醒。

默认从本人 HUD 头像自动识别英雄；英雄与三个候选连续高置信识别后，自动显示当前英雄资料。不确定时保留人工纠正。

选人衔接：从客户端本人高亮行与中央英雄名的一致画面确认当前分配，再接续本局新游戏窗口；局内尚未复核时会明确标注“来自本局选人 · HUD未复核”。

## 海克斯大乱斗辅助功能

- **英雄专属海克斯评级**：展示虎牙公开源的 T1–T4 评级，保留三个候选的原始顺序；缺失数据标为“暂无评级”。
- **自动本人英雄**：只在底部本人 HUD 区域匹配 Riot Data Dragon 头像，连续两帧一致后使用；不会从记分板或全屏人名猜英雄。
- **本地 OCR**：三个不同候选名称精确匹配、布局和置信度通过且连续两帧一致时自动显示；不确定时人工修正。
- **透明叠加层**：置顶显示资料卡，支持鼠标穿透和 `Ctrl+Alt+O` 快捷切换。
- **数据刷新与缓存**：启动时检查公开资料，离线时使用已验证缓存。
- **软件更新**：检查稳定版 GitHub Release，确认后下载并校验安装。

## 快速开始

### Windows

1. 下载 [v0.4.5 Windows x64 EXE](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.4.5/vga-aram-helper-0.4.5-windows-x64.exe)，核对同版 [SHA-256](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.4.5/SHA256SUMS.txt)。
2. 将 EXE 放入有写入权限的文件夹，双击启动。
3. 保持默认“自动识别英雄联盟”，点击“开始本局监测”。助手会最小化，自动等待或接续客户端/游戏，无需选择窗口。首次启动会准备约 5 MB 的公开头像缓存。

单文件 EXE 已集成 QtWidgets、OCR 运行时与模型。安装说明见 [Windows 指南](WINDOWS_EXECUTABLE.md)，许可与使用条款见下方[许可](#许可)。[Release 页面](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.5)提供测试证据和对应源码。

v0.4.5 预览版已发布，需手动下载，稳定 OTA 不自动发现。请核对同版清单与 SHA-256；机制见 [UPDATES.md](UPDATES.md)。

### 从源码运行

使用 Python 3.12 x64，在项目目录的虚拟环境中运行：

```sh
python -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-build.txt
python launcher.py
```

`python launcher.py --demo` 可载入合成演示数据。开发配置和测试命令见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 使用方法

- 保持默认自动识别窗口和本人 HUD 头像，点击开始后切回游戏；游戏未启动、最小化或被遮挡时会等待重试。存在多个候选或无法核验安装身份时会明确提示。
- 高置信本人头像和三个牌面标题连续两帧一致后自动显示。不会自动选择游戏内选项。
- 不确定时可关闭自动英雄、人工纠正英雄及候选。更换/未知英雄、候选变化、过期或切出窗口会隐藏旧资料，自动模式重新等待稳定画面。
- `Ctrl+Alt+O` 切换鼠标穿透；停止监测或关闭主窗口即可结束捕获。

### 从选人开始

v0.4.5 保持默认“自动识别英雄联盟”，点击“开始本局监测”即可；控制台会最小化并自动接续同目录客户端/游戏，支持已在对局和稍后启动。本人高亮行、中央名称及选人后的皮肤缩略图区域一致，并连续两帧确认后，记录本局当前英雄。初始候选卡、悬停预览和替补席不会直接作为本人选择。换人后重新确认；不是不可撤回的“锁定”。

选人身份只传递给同一安装目录的唯一新游戏进程；已在运行的游戏仍可自动绑定，但需要重新确认本人 HUD。切换接续选项或点击停止会撤销本局捕获。选人记录与局内头像冲突、画面不明或超时会清空；不确定时仍可人工纠正。尚未识别本人头像时，评级会注明选人来源。详见 [选人衔接范围](CHAMPION_SELECTION.md)。

## 数据与隐私

资料来自[虎牙官方公开 wiki](https://gametool.huya.com/league-of-legends/wiki/index.html?embed=1)。评级使用对应英雄的原始记录；资料卡标注来源日期、数据包与游戏资料版本。来源日期和获取时间分别记录，便于判断资料时效。格式与字段说明见 [DATA.md](DATA.md)。

自动模式仅绑定核验身份的同一英雄联盟安装目录，采集前台目标窗口的可见客户区；高级手动诊断需要明确指定窗口并点击开始。客户端与游戏接续核对安装路径、窗口身份和进程创建时间。仅处理屏幕像素，不读取游戏进程内存。正常监测截图在本机内存中处理，不保存或上传；显式合成诊断可保存测试图。应用主动联网用于公开数据、Riot Data Dragon 头像缓存与软件更新；截图不发送给这些服务。头像为 Riot 所有，不随源码或 EXE 打包。

v0.4.4 在 ONNX Runtime 导入/初始化前设置 `ORT_DISABLE_TELEMETRY=1`，同时保留 API 退出设置。[官方 ORT 1.31.0 文档](https://github.com/microsoft/onnxruntime/blob/v1.31.0/docs/Privacy.md)说明 API 可能晚于最小初始化。这是退出设置加固，不推断此前是否发生传输，也不是网络防火墙或完整出站审计。

## 预览版与兼容性

[v0.4.5 Windows 发布验证](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38447380079)已通过全部门禁并发布预览版。EXE 为 **106,399,997 字节（101.47 MiB）**；保留既有离线模型和最小 OpenCV 构建配方。下载后请核对同版 SHA-256，完整身份见[体积与哈希记录](WINDOWS_PACKAGE_SIZE.md)。

新增的真实 Windows 源码测试通过自动等待、客户端/游戏接续、已有游戏、重启、窗口重建、最小化恢复、空白回退和遮挡拦截；捕获与原创测试图的平均通道误差均为 0.0。发行商信任仅对测试自产文件注入，不能据此证明真实游戏签名或兼容性。同次构建还通过七项原生缓存共享锁/诊断测试，以及最终 EXE 的 100%/150%/200% 应用缩放、OCR、选人衔接和本地更新事务验收。历史 WinError 5 的具体占用者/原因仍未确定；新增“头像缓存诊断”只提供本机诊断，不自动上传。

测试范围见[验证记录](reports/VALIDATION.md)；历次体积与性能结果保留在[构建配方记录](WINDOWS_MINIMAL_OPENCV_EXPERIMENT.md)和[变更日志](CHANGELOG.md)，不代表真实对局性能。

v0.4.2 修正已确认的 Qt 逻辑坐标与 Win32 物理坐标不一致，以及固定叠加布局造成的小窗口问题：按叠加窗口自身的 Qt 缩放计算物理位置，空间不足时采用紧凑资料卡，保留三个名称、评级和来源。新鲜资料可随同一窗口平移；尺寸变化后等待重新识别。

[Windows EXE 发布测试](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38281910029)在同一 EXE、固定 960×600 像素的原创模拟窗口中通过了 100%、150%、200% 应用进程缩放检查，覆盖捕获/OCR、自动英雄与三候选、资料卡边界与文字布局、状态清除及关闭清理；选人识别与本局接续检查也已通过。同次构建的源码测试通过了 100%–250% 缩放下的 35 个窗口用例，包括过小窗口隐藏与恢复。实际系统 DPI、多显示器切换、4K 完整可见布局及用户报告的具体报错原因仍未确认。

v0.4.5 源码在 Linux 官方 wheel 上实际重跑的公开截图小样本中，3 个本人英雄样例识别 2 个（莎弥拉、卡特琳娜），米利欧头像未匹配而停止自动判断；3 个死亡/记分板、观战、竖向裁剪负例均停止判断。不能据此宣称总体识别率或自编译 Windows 包的识别表现。详见 [自动识别范围](AUTO_RECOGNITION.md) 和 [逐例结果](reports/hero-recognition-genuine.json)。

以下为 **v0.3.0 历史基线**，不证明新版自动英雄在 Windows 对局中已通过：

- [原生 EXE 测试](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38235785410)：窗口捕获、OCR、评级显示、鼠标穿透与进程生命周期。
- [更新事务测试](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38239627458)：同一 EXE 的本地替换、健康检查、并发锁与失败回滚。

真实 LoL/Vanguard、独占全屏及干净 Windows 10/11 环境尚未验证；v0.4.5 已通过同二进制原生更新成功/并发/回滚测试；跨版本在线升级和应用内确认交接仍待测试。公开快照评级可能与虎牙私有实时模型不同，评级方法与适用游戏政策仍有未核实之处，本项目未获 Riot/腾讯批准。详细范围见 [WINDOWS_TESTING.md](WINDOWS_TESTING.md)。

EXE 尚无 Authenticode 签名，Windows 可能提示未知发布者。请核对文件哈希并保留系统安全防护。

## 开发与贡献

欢迎通过 [Issues](https://github.com/Junming-Liang/vga-aram-helper/issues) 报告问题，或提交改进。

- [开发环境与测试](CONTRIBUTING.md)
- [Windows 构建](WINDOWS_EXECUTABLE.md)
- [数据来源](SOURCE_NOTES.md)与[验证记录](reports/VALIDATION.md)

## 许可

原创代码、图标和合成测试数据采用 [MIT License](LICENSE)。Qt/PySide/Shiboken 使用适用的 LGPLv3 选项；OCR 依赖、模型及其他第三方组件遵循各自许可。Release 附完整许可、对应 Qt 源码和同提交应用源码，详见[第三方声明](THIRD_PARTY_NOTICES.md)。第三方游戏资料不在本项目 MIT 许可范围内。

使用前请阅读并同意 [Release 许可包](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.4.5/third-party-licenses.zip)中的微软运行库条款。这些条款仅适用于所列微软 DLL，不限制 MIT 应用源码或 Qt LGPL 权利。自编译 OpenCV 的 `/MT` 还包含微软发行版 CRT 对象代码，适用微软条款独立于 OpenCV/Qt 许可，更新这部分需要重建；详见[运行库范围说明](THIRD_PARTY_NOTICES.md#microsoft-windows-runtime-components)。

本项目为独立实现，与 Riot Games、英雄联盟及虎牙无官方关联。
