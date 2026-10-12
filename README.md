<!-- project-header:start -->
<p align="center"><a href="README.md">简体中文</a> | <a href="README.en.md">English</a></p>
<p align="center">
  <img src="assets/branding/vga-icon-128.png" width="112" height="112" alt="VGA乱斗助手图标">
</p>
<h1 align="center">VGA乱斗助手</h1>
<p align="center"><strong>英雄专属三选一 · 本地截图识别 · 公开数据参考</strong></p>
<p align="center">
  <a href="https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/windows-build.yml"><img src="https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/windows-build.yml/badge.svg?branch=main&amp;event=workflow_dispatch" alt="Windows CI：最近一次手动构建与测试"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-16a34a" alt="License: MIT"></a>
  <a href="app_version.py"><img src="https://img.shields.io/badge/source-v0.3.0-0891b2" alt="源码版本 v0.3.0"></a>
  <a href="WINDOWS_EXECUTABLE.md"><img src="https://img.shields.io/badge/status-in%20development-d97706" alt="开发中，尚未正式发布"></a>
</p>
<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="WINDOWS_EXECUTABLE.md">Windows 指南</a> ·
  <a href="DATA.md">推荐与统计</a> ·
  <a href="CONTRIBUTING.md">参与贡献</a> ·
  <a href="https://github.com/Junming-Liang/vga-aram-helper/issues">反馈问题</a>
</p>
<!-- project-header:end -->

双击 Windows EXE 打开原生控制窗口，在你明确选择的窗口上显示透明资料叠加。截图识别在本机运行，无需 Python 安装、AI 订阅或 API key。当前没有正式 Release，最新原生版本仍待 Windows 实际 EXE 验收。

CI 徽章对应最近一次手动构建与测试，不代表游戏内适配已经验收。

## 功能

- **原生控制窗口与叠加层**：QtWidgets 界面；普通系统置顶窗口，默认鼠标穿透，可用 `Ctrl+Alt+O` 切换。
- **显式窗口监测**：由你选择目标、开启监测；仅采集所选前台窗口的可见客户区像素，不读取游戏进程内存、不注入、不装输入钩子。
- **本地候选识别**：RapidOCR 提取海克斯名称，人工核对英雄与三个候选后显示资料；不自动选牌。
- **公开资料与离线缓存**：启动检查虎牙官方公开 wiki；网络不可用时使用已验证缓存，没有缓存则明确提示不可用。
- **确认后软件更新**：检查 GitHub Releases，由你确认后才下载、校验和安装。

当前原生叠加保留截图中三个槽位的原始顺序，展示名称、机制描述、条件提醒，以及所选英雄的“虎牙公开源评级”（原始 T1/T2/T3/T4）。评级直接取该英雄的公开记录；缺失、空值或未知格式显示“暂无评级”，不拿全局评级补值，不从胜率自行换算，也不映射为 S/A/B/C。不会按评级重排卡片、显示胜率或输出唯一最佳选项。叠加同时注明来源日期、数据包与游戏资料版本。

这是公开资料快照的评级，不是复刻虎牙私有云端实时模型，不保证与其当前客户端结果相同。评级算法及适用政策仍存在未核实之处；本项目不声称获得 Riot/腾讯批准或已确认合规。英雄需手动选择。初版面向窗口/无边框模式，独占全屏和真实 LoL/Vanguard 兼容性尚未验证。公开数据可访问或不读内存，并不意味着获得游戏厂商批准。

## 快速开始

### Windows

便携版尚未正式发布，可在 [Releases](https://github.com/Junming-Liang/vga-aram-helper/releases) 查看状态，或关注 [Windows 构建](https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/windows-build.yml)。目标平台为 Windows 10/11 x64，单文件 EXE 包含 Python、QtWidgets、OCR 运行时和模型。

取得经验证的构建产物后，放入自己有写入权限的文件夹并双击。正常使用无需浏览器或本地网址；关闭主控制窗口即可退出。详见 [Windows 指南](WINDOWS_EXECUTABLE.md)。

### 从源码运行

开发者安装 Python 3.12 x64，在项目目录的虚拟环境中运行：

```sh
python -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-build.txt
python launcher.py
```

`python launcher.py --demo` 使用明确标注的虚构测试数据。真实窗口采集与叠加仅支持 Windows；其他系统可运行纯逻辑与 offscreen 控件测试。

历史 HTTP 界面保留为显式开发诊断：`python launcher.py --headless --demo`，默认仅监听 `127.0.0.1:8765`。它不是正常用户入口，浏览器测试也不能代替原生窗口验收。

## 使用方法

1. 启动后等待公开资料检查，明确选择需要监测的目标窗口。
2. 手动搜索或选择英雄，点击开始监测，然后切回目标窗口。
3. 本地 OCR 生成候选后，核对左、中、右三个名称；无法识别时可手动修正。
4. 确认后显示三张资料卡。换英雄、改候选或窗口状态变化时，旧资料会失效并隐藏，需重新确认。
5. `Ctrl+Alt+O` 切换鼠标穿透；停止监测或关闭主窗口即可停止捕获。

请使用窗口/无边框模式，避免其他窗口遮挡。切出、最小化或捕获失败会暂停显示；短时误识别、画面变化和不同分辨率仍需要人工核对。数据格式及历史诊断页面的统计字段解释见 [数据说明](DATA.md)。

## 数据与隐私

资料来自[虎牙官方公开 wiki](https://gametool.huya.com/league-of-legends/wiki/index.html?embed=1)。程序区分来源日期与获取时间；下载成功不代表资料适配最新游戏版本。

正常监测的截图仅在内存中处理，不写盘、不上传云端。联网请求用于公开数据与软件更新；启动监测和软件安装均需要用户明确操作。只有显式合成诊断会保存本程序自建窗口的测试图。更新机制见 [UPDATES.md](UPDATES.md)。

## 开发与贡献

欢迎通过 [Issues](https://github.com/Junming-Liang/vga-aram-helper/issues) 报告问题，或提交改进。

- [开发环境与测试](CONTRIBUTING.md)
- [Windows 构建](WINDOWS_EXECUTABLE.md)与[测试范围](WINDOWS_TESTING.md)
- [数据来源](SOURCE_NOTES.md)与[验证记录](reports/VALIDATION.md)

原生 Windows CI 使用原创模拟窗口，检查真实捕获、OCR、焦点、鼠标穿透与生命周期；它不能证明真实游戏效果或反作弊兼容性。请勿据此声称工具经过 Riot/Vanguard 批准或保证账号安全。

## 许可

原始项目代码、图标和合成测试数据采用 [MIT License](LICENSE)。Qt/PySide/Shiboken 使用适用的 LGPLv3 选项，OCR 依赖和模型遵循各自许可，见[第三方声明](THIRD_PARTY_NOTICES.md)。发布文件附完整许可、对应 Qt 源码和同提交应用源码，供查阅、修改和重建。第三方游戏资料不在本项目 MIT 许可范围内。

本项目为独立实现，与 Riot Games、英雄联盟及虎牙无官方关联。EXE 尚无 Authenticode 签名；下载后核对 SHA-256，不应关闭安全防护来绕过警告。
