<!-- project-header:start -->
<p align="center"><a href="README.md">简体中文</a> | <a href="README.en.md">English</a></p>
<p align="center">
  <img src="assets/branding/vga-icon-128.png" width="112" height="112" alt="VGA乱斗助手图标">
</p>
<h1 align="center">VGA乱斗助手</h1>
<p align="center"><strong>英雄专属三选一 · 本地截图识别 · 公开数据参考</strong></p>
<p align="center">
  <a href="https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/build-native-preview.yml"><img src="https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/build-native-preview.yml/badge.svg?branch=main&amp;event=workflow_dispatch" alt="Windows CI：最近一次手动构建与测试"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-16a34a" alt="License: MIT"></a>
  <a href="app_version.py"><img src="https://img.shields.io/badge/source-v0.3.0-0891b2" alt="源码版本 v0.3.0"></a>
  <a href="https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.3.0"><img src="https://img.shields.io/badge/status-preview-d97706" alt="v0.3.0 预览版"></a>
</p>
<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="WINDOWS_EXECUTABLE.md">Windows 指南</a> ·
  <a href="DATA.md">推荐与统计</a> ·
  <a href="CONTRIBUTING.md">参与贡献</a> ·
  <a href="https://github.com/Junming-Liang/vga-aram-helper/issues">反馈问题</a>
</p>
<!-- project-header:end -->

Windows 原生控制面板与游戏叠加层，为海克斯三选一提供英雄专属评级、机制说明与条件提醒。通过本地 OCR 识别候选，核对后即可在目标窗口上查看资料。

## 功能

- **英雄专属评级**：展示虎牙公开源的 T1–T4 评级，保留三个候选的原始顺序；缺失数据标为“暂无评级”。
- **本地 OCR**：识别海克斯名称，支持手动修正与三候选确认。
- **透明叠加层**：置顶显示资料卡，支持鼠标穿透和 `Ctrl+Alt+O` 快捷切换。
- **数据刷新与缓存**：启动时检查公开资料，离线时使用已验证缓存。
- **软件更新**：检查稳定版 GitHub Release，确认后下载并校验安装。

## 界面预览

v0.3.0 实际 Qt 界面，使用原创虚构数据在 Linux 离屏环境渲染。以下为界面演示，非实战截图；Windows 外观可能略有不同。

![原生控制面板，展示英雄选择、截图范围和三个候选的核对](docs/images/control-panel.png)

*控制面板：英雄与候选核对。演示环境未启用窗口采集。*

![透明叠加层，按原始顺序展示三个虚构候选的 T1、T2、T3 评级与说明](docs/images/overlay-preview.png)

*评级叠加层：三个候选的评级、效果和条件提醒。*

## 快速开始

### Windows

1. 下载 [v0.3.0 Windows x64 EXE](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.3.0/vga-aram-helper-0.3.0-windows-x64.exe)，核对 [SHA-256](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.3.0/SHA256SUMS.txt)。
2. 将 EXE 放入有写入权限的文件夹，双击启动。
3. 选择目标窗口和英雄，开始监测；核对三个候选后确认显示。

单文件 EXE 已集成 QtWidgets、OCR 运行时与模型。安装说明见 [Windows 指南](WINDOWS_EXECUTABLE.md)，许可与使用条款见下方[许可](#许可)。[Release 页面](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.3.0)提供测试证据和对应源码。

当前预览版需手动下载；稳定版更新机制见 [UPDATES.md](UPDATES.md)。

### 从源码运行

使用 Python 3.12 x64，在项目目录的虚拟环境中运行：

```sh
python -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-build.txt
python launcher.py
```

`python launcher.py --demo` 可载入合成演示数据。开发配置和测试命令见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 使用方法

- 手动选择英雄并开始监测，然后切回目标窗口。
- 核对 OCR 提取的左、中、右三个名称，必要时修正后确认。
- 更换英雄或候选后重新确认。切出、最小化、画面变化或捕获失败时，旧资料会隐藏。
- `Ctrl+Alt+O` 切换鼠标穿透；停止监测或关闭主窗口即可结束捕获。

## 数据与隐私

资料来自[虎牙官方公开 wiki](https://gametool.huya.com/league-of-legends/wiki/index.html?embed=1)。评级使用对应英雄的原始记录；资料卡标注来源日期、数据包与游戏资料版本。来源日期和获取时间分别记录，便于判断资料时效。格式与字段说明见 [DATA.md](DATA.md)。

采集范围为所选前台窗口的可见客户区，仅处理屏幕像素，不读取游戏进程内存。正常监测截图在本机内存中处理，不保存或上传；显式合成诊断可保存测试图。联网用于公开数据刷新与软件更新。

## 预览版与兼容性

v0.3.0 面向 Windows 10/11 x64 的窗口及无边框模式。目前验证基于 Windows Server 2022 上的原创模拟窗口：

- [原生 EXE 测试](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38235785410)：窗口捕获、OCR、评级显示、鼠标穿透与进程生命周期。
- [更新事务测试](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38239627458)：同一 EXE 的本地替换、健康检查、并发锁与失败回滚。

真实 LoL/Vanguard、独占全屏及干净 Windows 10/11 环境尚未验证；跨版本在线升级和应用内确认交接仍待测试。公开快照评级可能与虎牙私有实时模型不同，评级方法与适用游戏政策仍有未核实之处，本项目未获 Riot/腾讯批准。详细范围见 [WINDOWS_TESTING.md](WINDOWS_TESTING.md)。

EXE 尚无 Authenticode 签名，Windows 可能提示未知发布者。请核对文件哈希并保留系统安全防护。

## 开发与贡献

欢迎通过 [Issues](https://github.com/Junming-Liang/vga-aram-helper/issues) 报告问题，或提交改进。

- [开发环境与测试](CONTRIBUTING.md)
- [Windows 构建](WINDOWS_EXECUTABLE.md)
- [数据来源](SOURCE_NOTES.md)与[验证记录](reports/VALIDATION.md)

## 许可

原创代码、图标和合成测试数据采用 [MIT License](LICENSE)。Qt/PySide/Shiboken 使用适用的 LGPLv3 选项；OCR 依赖、模型及其他第三方组件遵循各自许可。Release 附完整许可、对应 Qt 源码和同提交应用源码，详见[第三方声明](THIRD_PARTY_NOTICES.md)。第三方游戏资料不在本项目 MIT 许可范围内。

使用前请阅读并同意 [Release 许可包](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.3.0/third-party-licenses.zip)中的微软运行库条款。这些条款仅适用于所列微软 DLL，不限制 MIT 应用源码或 Qt LGPL 权利。

本项目为独立实现，与 Riot Games、英雄联盟及虎牙无官方关联。
