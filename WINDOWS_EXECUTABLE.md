# Windows 便携版

## 下载与发布状态

[v0.4.11 预览版](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.11) 已于 2026-10-17 发布。[下载 Windows x64 EXE](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.4.11/vga-aram-helper-0.4.11-windows-x64.exe)，并核对同版 [SHA-256](https://github.com/Junming-Liang/vga-aram-helper/releases/download/v0.4.11/SHA256SUMS.txt)。

- 完整发布运行：[Windows 验收与发布](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/39025025768)，全部必需门禁通过。
- 源码 / 标签：`a33045e981b84d33eabdc4c8bdf9dca55ace0da8` / `v0.4.11`；树：`968d50746c1e7d3133fc729befb96569cd77d713`。
- EXE：**107,044,393 字节**；SHA-256：`60d147ba8ba975885060eec8ad8fe597967cef91e2b53855ba9f9ddf3eff3d3f`。
- 15 项发布资产；保持 prerelease / 非 latest，稳定 `/releases/latest` OTA 不自动发现，需手动下载。受控 Windows 验收不代表真实 LoL/Vanguard 或用户对局验证。

### v0.4.6 已发布预览版（历史构建说明）

本次增加随应用打包的原创 Windows Graphics Capture 辅助程序。在支持的 Windows 上使用明确 HWND 捕获；没有另行安装驱动/运行库的用户步骤。源码直接启动时若尚未编译辅助程序，则使用已有严格客户区 GDI 路径。

维护者应先按本文既有流程准备已同意条款的 Community 工具链，再运行 `python scripts/build_wgc_capture.py`，随后执行原有构建。脚本固定 Windows SDK 10.0.26100.0，验证微软签名编译器与辅助程序/源文件对应关系，并记录编译器和 SDK 头文件哈希；缺失、签名不符或来源不一致会停止构建，不自动安装其他工具。最终发布必须通过 `tests/windows_wgc_capture.py` 源码检查和 `--exe dist/VGA-Aram-Helper.exe` 同字节检查。见[实现、隐私边界与门禁](REFERENCE_OPTIMIZATION.md)。[Windows 运行 #23](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38531070525) 已通过这些门禁并发布同一最终 EXE；范围仅为原创受控窗口，不代表真实 LoL/Vanguard 验证。


Windows 便携版的目标平台为 Windows 10/11 x64。单文件 EXE 包含 Python 运行时、QtWidgets 原生界面、RapidOCR、ONNX Runtime 和本地模型，无需另装 Python 或配置 API key。

**Windows 便携版目前以预览版提供，尚非稳定正式版。** 当前下载 [v0.4.11](https://github.com/Junming-Liang/vga-aram-helper/releases/tag/v0.4.11)，并核对同版 SHA-256；构建结果见 [Windows 完整发布运行](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/39025025768)。

## 运行

本局英雄只读核验默认开启，可关闭；独立的选人客户端 API 仍默认关闭。检测到客户端后，主界面“开启本机选人识别”按钮提供仅本次启动的明确授权；接口读取不再依赖截图成功，失败后另行安排截图回退。同一核验游戏会话中的可靠英雄可跨死亡倒计时保留，候选仍需新鲜确认。见[实现范围](DEATH_IDENTITY_AND_CARD_BADGES.md)。

取得构建产物后：

运行前请阅读并同意同一 Release 的 `third-party-licenses.zip` 中 `microsoft-runtime/MICROSOFT_VISUAL_CPP_2015_2022_RUNTIME_TERMS.txt`。微软运行库条款只适用于所列五个微软 DLL，不限制 MIT 应用源码或 Qt 的 LGPL 修改/重建权利。

1. 将 `vga-aram-helper-版本-windows-x64.exe` 放到自己有写入权限的文件夹。也可重命名为 `VGA-Aram-Helper.exe`。
2. 双击后直接打开原生控制窗口，无需打开浏览器或输入网址。窗口先显示加载状态，再检查公开数据。
3. v0.4.11 默认使用“自动识别英雄联盟”，点击开始即可。开始后自动最小化默认关闭，可在设置中开启；先开助手后开游戏、已在对局、同目录重启和窗口重建均自动检测。默认自动识别本人英雄和三个候选；稳定高置信画面后显示资料，不确定时保留人工纠正。需要选人接口时，点击主界面“开启本机选人识别”。
4. v0.4.11 评级与可用搭配提示显示在三个候选卡片上方；候选评级始终鼠标穿透；`Ctrl+Alt+O` 切换交互/参考模式设置，不会让候选评级拦截点击。关闭主控制窗口会停止监测并关闭叠加层。

首次启动需要解压内置依赖并检查数据，可能稍慢。请使用普通用户权限运行，避免放入系统目录。Windows ARM64、32 位和 Windows 7/8 暂不支持，Wine 未验证。

v0.4.6 已发布 EXE：**106,553,042 字节（101.62 MiB）**，SHA-256 `0c2aef8e7759c149d6da90348d2ba065590c7e39b5f1522906d7e658b1b08d3a`；源码/标签 `f7ce587ee9a93fc509fd4b4e5b6a1cce150b2423`。稳定 OTA 不包含此预览版，请手动下载并核对同版清单。

### 当前操作

- 仪表盘显示本局英雄、监测状态和左/中/右三个候选，主按钮随状态切换“开始监测 / 停止监测”。“设置”管理连接、本人英雄和截图范围；“核对资料”用于人工纠正、明确确认和完整说明查阅；“关于”提供来源日期、数据包/游戏资料版本、许可和兼容性限制。次级页面仍能停止，按“返回”回到仪表盘。
- 三个不透明评级区域突出原始 T1–T4、身份来源与可用搭配文字；完整名称和说明在控制台查看。选人阶段另有公开源英雄整体 T1–T5 条，明确“仍可交换，HUD未复核”，不生成强化候选。
- “核对资料”保留单条内存记录“上次候选 · 最终选择未知”；它不会恢复当前确认或自动重新叠加，也不证明最终选中了哪一项。停止、新目标身份或不同已知英雄会清除记录。
- `Ctrl+Alt+O` 切换交互/参考模式设置，候选评级仍保持穿透。用户明确选择交互设置后，先退役持续会话并完成清理，下一次请求改走严格隐藏的单次交互兼容路径。普通排除校验失败不会自动进入这个路径；首次初始化确实缺失/不支持时可用原有安全回退，已启动会话的身份、前台、几何或读回校验失效则拒绝结果，不偷偷回退绕过。
- 四秒过期仍隐藏旧资料，但不取消授权未变且自身仍新鲜的在途推理；真正的失焦、身份/几何/权限变化与停止仍撤销。仪表盘显示规范英雄 ID 对应的已核验缓存头像及公开源评级；头像呈现不代表自动识别证明。
- 正常监测保留 Windows 捕获边框。默认可见捕获只在精确属于助手的不透明叠加 HWND、令牌/样式、`WDA_EXCLUDEFROMCAPTURE=0x11` 及身份/前台/ROI 运行时证明有效时保留标注的旧资料；新鲜识别完成后报告候选/英雄身份变化或不确定时隐藏；识别身份不变的无害 ROI 动画不要求隐藏。旧有严格隐藏路径与拒绝边界不变。空闲 GPU 帧池与异步退出限制见[隐私与验证边界](PLAY_FEEDBACK_FIXES.md)。

### 叠加与识别的范围

初版面向窗口/无边框模式，独占全屏、受保护画面和真实 LoL/Vanguard 兼容性尚未验证。仅使用普通系统窗口信息及所选前台窗口的可见像素，不读取游戏进程内存、不注入、不装输入钩子，也不自动选牌。切出、遮挡、窗口关闭或候选变化时暂停显示旧资料。

v0.4.8 的原生叠加保留三个完整候选名称、当前英雄的公开源原始 T1–T4 和可见来源标记；完整机制、条件与日期/版本在控制台查阅。无法清晰排版或超过客户区一半高度时隐藏。叠加中的缺失评级显示“暂无评级”；仪表盘评级胶囊显示“—”并提供“暂无评级”可访问说明；不展示胜率、不换算等级、不输出唯一最佳选择。查阅不代表监测识别或确认。公开快照不等于虎牙私有实时模型；自动英雄与 OCR 不确定时隐藏旧结果并保留人工纠正。

### 文件与更新

数据缓存、更新暂存及日志保存在 `%LOCALAPPDATA%\VGAAramHelper\`。软件检查新版本后会先显示提示，由你确认安装；源码运行模式不提供应用内安装。更新原理与恢复路径见 [UPDATES.md](UPDATES.md)。

### 本地调试与导出

1. 在“设置”勾选“本地调试日志（仅本次启动）”，再复现问题；每次重新启动默认关闭。
2. 点击“导出调试 ZIP”，保存到 `%LOCALAPPDATA%\VGAAramHelper\debug-exports\VGA-debug.zip`；界面显示实际本机位置，再次导出只替换上一份 ZIP。
3. 日志位于 `%LOCALAPPDATA%\VGAAramHelper\local-debug\`，最多三份 256 KiB 文件。关闭记录后已有日志和导出仍保留，可继续导出。

只记录白名单状态、计数、耗时和安全设置；窗口/进程身份使用每次启动随机化的别名，不包含截图、识别文字、名称、账号、令牌或私有路径。没有自动上传，导出不等于发送。若写入失败会停止记录并提示，不中断监测。

### 常用参数

```powershell
.\VGA-Aram-Helper.exe --version-file version.json
.\VGA-Aram-Helper.exe --self-test --report report.json
.\VGA-Aram-Helper.exe --licenses-file licenses.txt
.\VGA-Aram-Helper.exe --demo
```

窗口化 EXE 不附带控制台，诊断结果写入指定文件。`--headless`（旧别名 `--no-browser`）仅供开发者运行本机 HTTP 诊断；正常启动不建立网页界面。`--demo` 使用虚构演示数据。`--no-updates` 只跳过本次软件更新检查；数据检查仍按正常启动流程进行。

### 下载安全

EXE 尚未进行 Authenticode 签名，Windows SmartScreen 或安全软件可能显示未知发布者提示。请从本仓库获取文件，并核对发布页的 SHA-256；遇到拦截时保留防护设置，向维护者提供文件版本与提示内容。

SHA-256 可检查文件损坏或不一致，但不能替代代码签名，也不能防御发布账号被入侵。

## 从源码构建

构建必须在原生 Windows x64 上进行。Linux 无法用本项目的 PyInstaller 配置交叉生成 Windows EXE。

### GitHub Actions

1. 打开 [Build and test Windows EXE](https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/windows-build.yml)，手动选择目标提交。
2. 保留 `run_browser_test`，运行显式 HTTP/浏览器诊断；另有不可跳过的原生窗口、所选模拟窗口捕获、实际 OCR、鼠标穿透及退出测试。
3. 成功后下载 `vga-aram-helper-windows-x64-提交SHA`，解压取得 EXE 和配套文件。
4. 下载 `windows-test-evidence-提交SHA`，检查报告和 UI 截图。

工作流仅支持手动触发；当前构建测试流程使用标准 `windows-2022` runner 和只读仓库权限，不创建 Release。EXE artifact 仅在测试成功后上传；产物和证据保留一天。上传前会读取本仓库已有 artifact 大小，并计算本次 EXE、源码与证据总量；超过 500 MB 项目上限（另留 10 MB 余量）则拒绝上传。此检查不代表整个账号其他仓库的用量。

[GitHub 的标准 runner 运行在公开仓库中免费](https://docs.github.com/en/billing/concepts/product-billing/github-actions)，artifact 存储仍需关注账户配额。运行前检查可用存储，不使用收费的 larger runner。

### 本地构建

安装 Python 3.12 x64 和 Git，使用干净的 Git checkout（全部构建输入已提交）。打包前还需在有效的 [Visual Studio Community 2022 许可](https://visualstudio.microsoft.com/license-terms/vs2022-ga-community/) 下准备 `build/microsoft-runtime`：五个受支持的发行 DLL 与验证来源清单。自动准备脚本 `scripts/install-community-runtime.ps1 -AcceptCommunityLicense` 目前明确限于临时 GitHub 托管 Windows runner；不在个人电脑上自动安装。维护者可在自己的公开源码分支手动运行所附工作流，或在自己的有效许可下参考该开源脚本适配本地准备步骤，保留签名、依赖与来源验证。普通 EXE 使用者不需要执行这些步骤。

```powershell
.\scripts\build-windows.ps1
```

上述本地脚本在项目目录创建 `.venv-build`，从官方 PyPI 安装固定顶层版本的依赖，用于官方 wheel 的源码/打包诊断，构建并运行 EXE 冒烟测试。它不等同于 v0.4.4 已采用的自编译 OpenCV 发布配方；正式预览发布路径见下节。微软 DLL 来自实际安装的 Community 发行目录；其签名、版本、依赖和逐字节来源均需验证，不能以 CI 预装运行库代替。托管 runner 的官方安装失败或要求重启时停止构建，不自动重启。

- EXE：`dist\VGA-Aram-Helper.exe`
- 发布文件：`dist\release\`
- 模型：随官方 wheel 提供，构建前和 EXE 自检时校验 SHA-256
- 依赖记录：构建证据包含实际安装的版本和可用许可文件

构建前后会拒绝未提交或未跟踪的源码/资源输入，以保证 EXE 与分发的同提交源码相符。正常生成的构建输出和 Windows 测试日志不属于源码输入。若从发布源码 ZIP 重建，先在解压目录初始化 Git 并提交源码，或直接克隆仓库并检出对应提交。

修改 LGPL 库后重建：在构建虚拟环境中先安装 ABI/架构兼容的修改版 Qt/PySide/Shiboken，再直接运行 `python scripts/build_windows.py`。不要重新运行会覆盖修改库的依赖安装步骤。版本信息需与相应许可/source 清单一致；修改源码和构建材料应一并保留。普通官方库打包流程已配置测试，完整修改版 Qt 源码编译/重建尚未验证。

顶层版本已固定，传递依赖仍以构建记录为准；当前构建不是逐文件哈希锁定的可复现构建。

## 原生预览版发布

`Build and publish native preview` 是另一条手动标准 Windows 工作流：重新构建、完成全部 EXE/OCR/原生源评级测试并校验后，在同一任务的最后一步直接上传 GitHub 预发布版。它不再创建大型 Actions EXE/源码 artifact，只保留预算允许的小型测试证据；不删除已有产物。`GH_TOKEN` 仅用于最后的发布步骤，不持久保存凭据。

v0.4.4 发布工作流明确设置 `VGA_RELEASE_PACKAGE_PROFILE=minimal-opencv-v1`，从已固定哈希的官方 OpenCV 源码及审查过的补丁构建自编译 `5.0.0.93+vga1`（原生版本 `5.0.0`）；此二进制不是官方 PyPI wheel。它重新执行官方/自编译同机对比、精确版本 EXE 全部门禁，并校验补充许可 ZIP 与源码/配方/二进制到对比证据的绑定。仅设置环境变量或运行上述官方 wheel 诊断不能替代这些证明。全部原始离线模型、Qt/CRT 条款及对应源码供应保持不变。最终 v0.4.4 已通过[发布运行 #10](https://github.com/Junming-Liang/vga-aram-helper/actions/runs/38417923065)并发布预览版；配方、维护成本与实测范围见 [OpenCV 验证记录](WINDOWS_MINIMAL_OPENCV_EXPERIMENT.md)。

自编译 `cv2.pyd` 的 `/MT` 静态链接还嵌入微软发行版 CRT 对象代码，适用微软条款独立于 OpenCV/Qt 许可；维护这部分需要重建并重新分发。既有五份 DLL 条款不变，详见[范围说明和微软官方参考](THIRD_PARTY_NOTICES.md#microsoft-windows-runtime-components)；这不是法律合规认证。

预发布版标记为 prerelease，不设为 latest，稳定更新接口不会推送它。版本 tag 与内置 manifest 一致；已有 tag 或 Release 会使发布失败，不覆盖旧文件。

## Release 文件

版本号维护在 `app_version.py`，对应 tag 为 `v版本`。每个 Release 包含：

- `vga-aram-helper-版本-windows-x64.exe`
- `update-manifest.json`
- `SHA256SUMS.txt`
- `third-party-licenses.zip`，含 Qt/PySide/Shiboken 完整许可与来源记录
- `vga-aram-helper-版本-source.zip`，与构建提交一致的应用源码
- Qt/PySide 6.11.2 的四份官方对应源码归档及 `source-access.json`（逐个文件的大小、SHA-256 与来源）

构建脚本根据实际 EXE 生成清单的版本、下载地址、大小与 SHA-256。EXE 与 Manifest 必须来自同一次构建；上传 CI artifact 不会使清单中的 Release 下载地址生效。

使用者无需下载源码归档即可运行 EXE；源码为许可、修改和重建用途。Qt 采用适用的 LGPLv3 选项，修改库后重建的说明见 `third-party-licenses.zip` 中 `qt-licenses/SOURCE_AND_RELINKING.txt`。无签名密钥或付费工具授权要求。

发布步骤见 [检查表](PUBLICATION_CHECKLIST.md)，验收范围见 [Windows 测试](WINDOWS_TESTING.md)。原生 Windows OTA 替换、重启和失败回滚需要独立验证。

## 参考

- [PyInstaller 运行时资源](https://pyinstaller.org/en/stable/runtime-information.html)
- [PyInstaller 官方发行包](https://pypi.org/project/pyinstaller/6.22.3/)
- [RapidOCR 模型许可](https://rapidai.github.io/RapidOCRDocs/main/en/model_licenses/)

## Package-size candidate validation

See [WINDOWS_PACKAGE_SIZE.md](WINDOWS_PACKAGE_SIZE.md) for the verified v0.4.2
size baseline, reviewed package-only removals, measured archive report and
regression ceiling. The manual read-only `test-windows-package-size.yml` workflow
runs the full frozen-EXE acceptance suite plus all supported image formats and
native same-binary OTA transactions. It does not modify existing releases.

## v0.4.5 自动连接与捕获边界

正常路径不需要指定 HWND。每次“开始”绑定一个安装目录，自动核对窗口类、系统报告的完整可执行文件路径、PID 创建时间、Windows 离线 Authenticode 信任及签名文件的游戏产品身份。支持根目录客户端与国服 `LeagueClient` 子目录，游戏必须位于同根目录的 `Game` 中。多个安装或同类窗口时等待，不猜测。

未知签名/产品身份不会偷偷放行；任务栏提示用户打开控制台，查看具体程序并明确确认自己的安装目录。该确认只对当前监测有效，停止即撤销；不修改 Windows 信任或安全设置。当前中国/国际客户端所有发行商变体尚未实机覆盖。

游戏为空白、切出、最小化、被其他窗口遮挡或窗口重建时自动等待/重试。HWND GDI 不返回可用像素时，后备方式仅分配并复制目标客户区内的像素，不创建整桌面图像；捕获前后检查前台、窗口身份、完整显示器内范围以及所有更高窗口的相交情况。跨屏或部分移出屏幕的客户区会等待。控制台仅在开始成功后最小化，不操作游戏输入。

头像完整下载并校验后，即使本地缓存写入被其他进程短暂锁住，也可在当前运行使用内存中的模板；缓存状态会如实说明。不会要求以管理员身份启动或关闭防护软件。

这些是针对已收到错误和源码复现的修复。Windows 原创模拟窗口、真实文件共享锁与原生签名 API 测试仍不等于真实 LoL/Vanguard 对局验证。
