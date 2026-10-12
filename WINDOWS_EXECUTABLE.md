# Windows 便携版

Windows 便携版的目标平台为 Windows 10/11 x64。单文件 EXE 包含 Python 运行时、RapidOCR、ONNX Runtime 和本地模型，无需另装 Python 或配置 API key。

**目前尚未正式发布 Windows 便携版。** 发布文件请以 [Releases](https://github.com/Junming-Liang/vga-aram-helper/releases) 为准；构建结果可在 [Actions](https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/windows-build.yml) 查看。

## 运行

取得构建产物后：

1. 将 `vga-aram-helper-版本-windows-x64.exe` 放到自己有写入权限的文件夹。也可重命名为 `VGA-Aram-Helper.exe`。
2. 双击启动，等待数据检查完成。默认浏览器会打开本机页面。
3. 关闭控制台窗口或按 `Ctrl+C` 退出。仅关闭网页不会停止后台服务。

首次启动需要解压内置依赖并检查数据，可能稍慢。请使用普通用户权限运行，避免放入系统目录。Windows ARM64、32 位和 Windows 7/8 暂不支持，Wine 未验证。

### 文件与更新

数据缓存、更新暂存及日志保存在 `%LOCALAPPDATA%\VGAAramHelper\`。软件检查新版本后会先显示提示，由你确认安装；源码运行模式不提供应用内安装。更新原理与恢复路径见 [UPDATES.md](UPDATES.md)。

### 常用参数

```powershell
.\VGA-Aram-Helper.exe --version
.\VGA-Aram-Helper.exe --self-test --report report.json
.\VGA-Aram-Helper.exe --licenses
.\VGA-Aram-Helper.exe --no-browser
```

`--demo` 使用虚构演示数据。`--no-updates` 只跳过本次软件更新检查；数据检查仍按正常启动流程进行。

### 下载安全

EXE 尚未进行 Authenticode 签名，Windows SmartScreen 或安全软件可能显示未知发布者提示。请从本仓库获取文件，并核对发布页的 SHA-256；遇到拦截时保留防护设置，向维护者提供文件版本与提示内容。

SHA-256 可检查文件损坏或不一致，但不能替代代码签名，也不能防御发布账号被入侵。

## 从源码构建

构建必须在原生 Windows x64 上进行。Linux 无法用本项目的 PyInstaller 配置交叉生成 Windows EXE。

### GitHub Actions

1. 打开 [Build and test Windows EXE](https://github.com/Junming-Liang/vga-aram-helper/actions/workflows/windows-build.yml)，手动选择目标提交。
2. 保留 `run_browser_test`，运行实际 EXE 的 OCR、HTTP 和浏览器检查。
3. 成功后下载 `vga-aram-helper-windows-x64-提交SHA`，解压取得 EXE 和配套文件。
4. 下载 `windows-test-evidence-提交SHA`，检查报告和 UI 截图。

工作流仅支持手动触发；当前构建测试流程使用标准 `windows-2022` runner 和只读仓库权限，不创建 Release。EXE artifact 仅在测试成功后上传；产物和证据保留一天。

[GitHub 的标准 runner 运行在公开仓库中免费](https://docs.github.com/en/billing/concepts/product-billing/github-actions)，artifact 存储仍需关注账户配额。运行前检查可用存储，不使用收费的 larger runner。

### 本地构建

安装 Python 3.12 x64，在 PowerShell 中运行：

```powershell
.\scripts\build-windows.ps1
```

脚本在项目目录创建 `.venv-build`，从官方 PyPI 安装固定顶层版本的依赖，构建并运行 EXE 冒烟测试。

- EXE：`dist\VGA-Aram-Helper.exe`
- 发布文件：`dist\release\`
- 模型：随官方 wheel 提供，构建前和 EXE 自检时校验 SHA-256
- 依赖记录：构建证据包含实际安装的版本和可用许可文件

顶层版本已固定，传递依赖仍以构建记录为准；当前构建不是逐文件哈希锁定的可复现构建。

## Release 文件

版本号维护在 `app_version.py`，对应 tag 为 `v版本`。每个 Release 包含：

- `vga-aram-helper-版本-windows-x64.exe`
- `update-manifest.json`
- `SHA256SUMS.txt`
- `third-party-licenses.zip`

构建脚本根据实际 EXE 生成清单的版本、下载地址、大小与 SHA-256。EXE 与 Manifest 必须来自同一次构建；上传 CI artifact 不会使清单中的 Release 下载地址生效。

发布步骤见 [检查表](PUBLICATION_CHECKLIST.md)，验收范围见 [Windows 测试](WINDOWS_TESTING.md)。原生 Windows OTA 替换、重启和失败回滚需要独立验证。

## 参考

- [PyInstaller 运行时资源](https://pyinstaller.org/en/stable/runtime-information.html)
- [PyInstaller 官方发行包](https://pypi.org/project/pyinstaller/6.22.3/)
- [RapidOCR 模型许可](https://rapidai.github.io/RapidOCRDocs/main/en/model_licenses/)
