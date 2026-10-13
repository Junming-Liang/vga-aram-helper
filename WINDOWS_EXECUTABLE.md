# Windows 便携版

Windows 便携版的目标平台为 Windows 10/11 x64。单文件 EXE 包含 Python 运行时、QtWidgets 原生界面、RapidOCR、ONNX Runtime 和本地模型，无需另装 Python 或配置 API key。

**Windows 便携版目前以预览版提供，尚非稳定正式版。** 发布文件请以 [Releases](https://github.com/Junming-Liang/vga-aram-helper/releases) 为准；构建结果可在 [Actions](https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/windows-build.yml) 查看。

## 运行

取得构建产物后：

运行前请阅读并同意同一 Release 的 `third-party-licenses.zip` 中 `microsoft-runtime/MICROSOFT_VISUAL_CPP_2015_2022_RUNTIME_TERMS.txt`。微软运行库条款只适用于所列五个微软 DLL，不限制 MIT 应用源码或 Qt 的 LGPL 修改/重建权利。

1. 将 `vga-aram-helper-版本-windows-x64.exe` 放到自己有写入权限的文件夹。也可重命名为 `VGA-Aram-Helper.exe`。
2. 双击后直接打开原生控制窗口，无需打开浏览器或输入网址。窗口先显示加载状态，再检查公开数据。
3. 在列表中明确选择目标窗口并点击开始监测。默认自动识别本人英雄和三个候选；稳定高置信画面后显示资料，不确定时保留人工纠正。
4. 资料显示在透明置顶叠加层中；默认鼠标穿透，`Ctrl+Alt+O` 可切换。关闭主控制窗口会停止监测并关闭叠加层。

首次启动需要解压内置依赖并检查数据，可能稍慢。请使用普通用户权限运行，避免放入系统目录。Windows ARM64、32 位和 Windows 7/8 暂不支持，Wine 未验证。

### 叠加与识别的范围

初版面向窗口/无边框模式，独占全屏、受保护画面和真实 LoL/Vanguard 兼容性尚未验证。仅使用普通系统窗口信息及所选前台窗口的可见像素，不读取游戏进程内存、不注入、不装输入钩子，也不自动选牌。切出、遮挡、窗口关闭或候选变化时暂停显示旧资料。

当前原生叠加显示候选名称、机制描述、条件提醒及当前英雄的虎牙公开源评级（原始 T1–T4）。缺失/未知评级显示“暂无评级”；保留三个输入槽位，不展示胜率、不自行换算等级或输出唯一最佳选择。公开资料快照不等于虎牙私有云端实时模型。自动英雄和 OCR 都有不确定性；无法确认时隐藏旧结果并保留人工纠正，不应盲目信任识别结果。

### 文件与更新

数据缓存、更新暂存及日志保存在 `%LOCALAPPDATA%\VGAAramHelper\`。软件检查新版本后会先显示提示，由你确认安装；源码运行模式不提供应用内安装。更新原理与恢复路径见 [UPDATES.md](UPDATES.md)。

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

脚本在项目目录创建 `.venv-build`，从官方 PyPI 安装固定顶层版本的依赖，构建并运行 EXE 冒烟测试。微软 DLL 来自实际安装的 Community 发行目录；其签名、版本、依赖和逐字节来源均需验证，不能以 CI 预装运行库代替。托管 runner 的官方安装失败或要求重启时停止构建，不自动重启。

- EXE：`dist\VGA-Aram-Helper.exe`
- 发布文件：`dist\release\`
- 模型：随官方 wheel 提供，构建前和 EXE 自检时校验 SHA-256
- 依赖记录：构建证据包含实际安装的版本和可用许可文件

构建前后会拒绝未提交或未跟踪的源码/资源输入，以保证 EXE 与分发的同提交源码相符。正常生成的构建输出和 Windows 测试日志不属于源码输入。若从发布源码 ZIP 重建，先在解压目录初始化 Git 并提交源码，或直接克隆仓库并检出对应提交。

修改 LGPL 库后重建：在构建虚拟环境中先安装 ABI/架构兼容的修改版 Qt/PySide/Shiboken，再直接运行 `python scripts/build_windows.py`。不要重新运行会覆盖修改库的依赖安装步骤。版本信息需与相应许可/source 清单一致；修改源码和构建材料应一并保留。普通官方库打包流程已配置测试，完整修改版 Qt 源码编译/重建尚未验证。

顶层版本已固定，传递依赖仍以构建记录为准；当前构建不是逐文件哈希锁定的可复现构建。

## 原生预览版发布

`Build and publish native preview` 是另一条手动标准 Windows 工作流：重新构建、完成全部 EXE/OCR/原生源评级测试并校验后，在同一任务的最后一步直接上传 GitHub 预发布版。它不再创建大型 Actions EXE/源码 artifact，只保留预算允许的小型测试证据；不删除已有产物。`GH_TOKEN` 仅用于最后的发布步骤，不持久保存凭据。

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
